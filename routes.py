from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel
import logging

from database import get_db, LuasSnapshot, LuasAccuracy

logger = logging.getLogger(__name__)

router = APIRouter()

# Luas stops data - Green and Red lines
LUAS_STOPS = {
    # Green Line
    "bri": {"name": "Broombridge", "line": "Green"},
    "cab": {"name": "Cabra", "line": "Green"},
    "con": {"name": "Connolly", "line": "Green"},
    "bus": {"name": "Busáras", "line": "Green"},
    "jer": {"name": "Jervis", "line": "Green"},
    "tem": {"name": "Temple Bar", "line": "Green"},
    "pow": {"name": "Powercourt", "line": "Green"},
    "dro": {"name": "Drury Street", "line": "Green"},
    "fou": {"name": "Four Courts", "line": "Green"},
    "sim": {"name": "Smithfield", "line": "Green"},
    "mus": {"name": "Museum", "line": "Green"},
    "kil": {"name": "Kilmainham", "line": "Green"},
    "sun": {"name": "Suir Road", "line": "Green"},
    "gol": {"name": "Goldenbridge", "line": "Green"},
    "dri": {"name": "Drimnagh", "line": "Green"},
    "bla": {"name": "Blackhorse", "line": "Green"},
    "kyo": {"name": "Kylemore", "line": "Green"},
    "red": {"name": "Red Cow", "line": "Green"},
    "tal": {"name": "Tallaght", "line": "Green"},
    
    # Red Line
    "che": {"name": "Cheeverstown", "line": "Red"},
    "cit": {"name": "City West", "line": "Red"},
    "for": {"name": "Fortunestown", "line": "Red"},
    "bly": {"name": "Bluebell", "line": "Red"},
    "kni": {"name": "Knocknaheown", "line": "Red"},
    "bay": {"name": "Ballyogan", "line": "Red"},
    "dup": {"name": "Dupont", "line": "Red"},
    "lep": {"name": "Leopardstown", "line": "Red"},
}


class ForecastResponse(BaseModel):
    destination: str
    direction: str
    due_minutes: int
    due_time: str
    
    class Config:
        from_attributes = True


class CurrentArrivalsResponse(BaseModel):
    stop_code: str
    last_updated: str
    next_arrivals: List[ForecastResponse]


@router.get("/stops")
async def get_stops():
    """
    Get list of all available Luas stops.
    Returns stops organized by line with their codes.
    """
    green_line = [
        {"code": code, "name": stop["name"], "line": stop["line"]}
        for code, stop in LUAS_STOPS.items()
        if stop["line"] == "Green"
    ]
    red_line = [
        {"code": code, "name": stop["name"], "line": stop["line"]}
        for code, stop in LUAS_STOPS.items()
        if stop["line"] == "Red"
    ]
    
    return {
        "stops": {
            "green": sorted(green_line, key=lambda x: x["name"]),
            "red": sorted(red_line, key=lambda x: x["name"])
        }
    }


@router.get("/arrivals/{stop_code}", response_model=CurrentArrivalsResponse)
async def get_arrivals(stop_code: str, db: Session = Depends(get_db), limit: int = 3):
    """
    Get the next N upcoming trams for a given stop.
    Returns the most recent forecast for each unique destination/direction combo.
    
    Parameters:
    - stop_code: Luas stop code (e.g., 'cab' for Cabra, 'tal' for Tallaght)
    - limit: Number of arrivals to return (default 3)
    """
    # Normalize stop code to lowercase
    stop_code = stop_code.lower()
    
    # Validate stop code
    if stop_code not in LUAS_STOPS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stop code: {stop_code}. See /stops for valid codes."
        )
    
    try:
        # Get the most recent snapshot timestamp for this stop
        latest_snapshot = db.query(func.max(LuasSnapshot.recorded_at)).filter(
            LuasSnapshot.stop_code == stop_code
        ).scalar()
        
        if not latest_snapshot:
            # Return empty arrivals if no data yet
            return CurrentArrivalsResponse(
                stop_code=stop_code,
                last_updated=datetime.utcnow().isoformat(),
                next_arrivals=[]
            )
        
        # Get forecasts from the latest snapshot, ordered by arrival time
        # Using >= instead of == to handle any timing issues with multiple records
        # Within the same second
        forecasts = db.query(LuasSnapshot).filter(
            LuasSnapshot.recorded_at >= latest_snapshot - timedelta(seconds=1),
            LuasSnapshot.recorded_at <= latest_snapshot + timedelta(seconds=1),
            LuasSnapshot.stop_code == stop_code
        ).order_by(
            LuasSnapshot.forecast_arrival_minutes
        ).limit(limit).all()
        
        arrivals = [
            ForecastResponse(
                destination=f.destination,
                direction=f.direction,
                due_minutes=f.forecast_arrival_minutes,
                due_time=f.forecast_arrival_time.isoformat()
            )
            for f in forecasts
        ]
        
        stop_name = LUAS_STOPS.get(stop_code, {}).get("name", stop_code)
        
        return CurrentArrivalsResponse(
            stop_code=stop_code,
            last_updated=latest_snapshot.isoformat(),
            next_arrivals=arrivals
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/arrivals/cabra", response_model=CurrentArrivalsResponse)
async def get_cabra_arrivals(db: Session = Depends(get_db), limit: int = 3):
    """
    Get the next N upcoming trams for Cabra stop.
    Returns the most recent forecast for each unique destination/direction combo.
    (Kept for backwards compatibility)
    """
    return await get_arrivals("cab", db, limit)


@router.get("/accuracy/summary")
async def get_accuracy_summary(db: Session = Depends(get_db), hours: int = 24):
    """
    Get forecast accuracy metrics for the last N hours.
    Shows average accuracy by destination/direction.
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Query accuracy data grouped by destination/direction
        accuracy_data = db.query(
            LuasAccuracy.destination,
            LuasAccuracy.direction,
            func.count(LuasAccuracy.id).label("count"),
            func.avg(LuasAccuracy.accuracy_delta).label("avg_delta"),
            func.min(LuasAccuracy.accuracy_delta).label("min_delta"),
            func.max(LuasAccuracy.accuracy_delta).label("max_delta")
        ).filter(
            LuasAccuracy.stop_code == "cab",
            LuasAccuracy.calculated_at >= cutoff_time
        ).group_by(
            LuasAccuracy.destination,
            LuasAccuracy.direction
        ).all()
        
        if not accuracy_data:
            return {
                "message": "No accuracy data available yet",
                "data": []
            }
        
        return {
            "period_hours": hours,
            "data": [
                {
                    "destination": row.destination,
                    "direction": row.direction,
                    "measurements": row.count,
                    "avg_accuracy_minutes": round(row.avg_delta, 2),
                    "best_case_minutes": row.min_delta,
                    "worst_case_minutes": row.max_delta
                }
                for row in accuracy_data
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accuracy/calculate")
async def calculate_accuracy(db: Session = Depends(get_db)):
    """
    Calculate forecast accuracy by comparing forecasts across polls.
    
    Algorithm:
    1. For each unique tram (destination + direction)
    2. Look at forecasts from previous polls
    3. When a tram "arrives" (forecast_arrival_minutes approaches 0)
    4. Compare original forecast to actual time taken
    5. Store accuracy delta
    
    This runs periodically to populate LuasAccuracy table.
    """
    try:
        # Get snapshots from the last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        snapshots = db.query(LuasSnapshot).filter(
            LuasSnapshot.recorded_at >= one_hour_ago
        ).all()
        
        if not snapshots:
            return {"message": "No data to calculate accuracy from", "calculated": 0}
        
        accuracy_records = []
        
        # Group snapshots by stop, direction, destination, and forecast arrival time
        # This helps us track the same "train" across multiple polls
        from collections import defaultdict
        tram_history = defaultdict(list)
        
        for snapshot in snapshots:
            key = (snapshot.stop_code, snapshot.direction, snapshot.destination)
            tram_history[key].append(snapshot)
        
        # For each tram, look for ones that "arrived" (forecast went to 0 or negative)
        for (stop_code, direction, destination), poll_history in tram_history.items():
            # Sort by recorded_at to see progression
            poll_history.sort(key=lambda x: x.recorded_at)
            
            # Look for trams that went from predicted to arriving
            for i in range(1, len(poll_history)):
                prev = poll_history[i-1]
                curr = poll_history[i]
                
                # Check if this is the same "train" (similar forecast times)
                # and it's getting closer to arrival
                if (prev.forecast_arrival_minutes > 0 and 
                    curr.forecast_arrival_minutes == 0):
                    
                    # Time elapsed between forecasts
                    time_elapsed = (curr.recorded_at - prev.recorded_at).total_seconds() / 60
                    
                    # Original forecast was prev.forecast_arrival_minutes minutes
                    # Actual time to arrival was approximately time_elapsed
                    accuracy_delta = int(time_elapsed - prev.forecast_arrival_minutes)
                    
                    accuracy = LuasAccuracy(
                        stop_code=stop_code,
                        direction=direction,
                        destination=destination,
                        forecasted_minutes=prev.forecast_arrival_minutes,
                        actual_minutes=int(time_elapsed),
                        accuracy_delta=accuracy_delta,
                        calculated_at=datetime.utcnow()
                    )
                    accuracy_records.append(accuracy)
        
        # Store all accuracy records
        if accuracy_records:
            db.add_all(accuracy_records)
            db.commit()
            logger.info(f"Calculated and stored {len(accuracy_records)} accuracy records")
        
        return {
            "message": "Accuracy calculation complete",
            "calculated": len(accuracy_records),
            "period": "last 1 hour"
        }
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error calculating accuracy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/accuracy")
async def get_accuracy_metrics(db: Session = Depends(get_db), stop_code: str = "cab", hours: int = 24):
    """
    Get accuracy metrics for a specific stop over a time period.
    
    Returns:
    - Overall accuracy
    - By destination
    - By direction
    - Trend over time
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get all accuracy records for this stop and period
        accuracy_data = db.query(LuasAccuracy).filter(
            LuasAccuracy.stop_code == stop_code,
            LuasAccuracy.calculated_at >= cutoff_time
        ).all()
        
        if not accuracy_data:
            return {
                "stop_code": stop_code,
                "period_hours": hours,
                "message": "No accuracy data available yet",
                "overall": None,
                "by_destination": [],
                "trend": []
            }
        
        # Calculate overall metrics
        all_deltas = [a.accuracy_delta for a in accuracy_data]
        avg_delta = sum(all_deltas) / len(all_deltas) if all_deltas else 0
        
        # Count on-time, early, late
        on_time_count = sum(1 for d in all_deltas if d == 0)
        early_count = sum(1 for d in all_deltas if d < 0)
        late_count = sum(1 for d in all_deltas if d > 0)
        
        # Metrics by destination
        from collections import defaultdict
        by_dest = defaultdict(list)
        for record in accuracy_data:
            by_dest[record.destination].append(record.accuracy_delta)
        
        dest_metrics = []
        for destination, deltas in by_dest.items():
            dest_metrics.append({
                "destination": destination,
                "measurements": len(deltas),
                "avg_accuracy_minutes": round(sum(deltas) / len(deltas), 2),
                "min_delta": min(deltas),
                "max_delta": max(deltas),
                "on_time_pct": round(sum(1 for d in deltas if d == 0) / len(deltas) * 100, 1)
            })
        
        # Sort by measurements count (most tested destinations first)
        dest_metrics.sort(key=lambda x: x["measurements"], reverse=True)
        
        # Hourly trend
        hourly_data = defaultdict(list)
        for record in accuracy_data:
            hour_key = record.calculated_at.strftime("%Y-%m-%d %H:00")
            hourly_data[hour_key].append(record.accuracy_delta)
        
        trend = []
        for hour_key in sorted(hourly_data.keys()):
            deltas = hourly_data[hour_key]
            trend.append({
                "timestamp": hour_key,
                "avg_accuracy": round(sum(deltas) / len(deltas), 2),
                "measurements": len(deltas)
            })
        
        return {
            "stop_code": stop_code,
            "period_hours": hours,
            "total_measurements": len(accuracy_data),
            "overall": {
                "avg_accuracy_minutes": round(avg_delta, 2),
                "on_time_pct": round(on_time_count / len(accuracy_data) * 100, 1),
                "early_pct": round(early_count / len(accuracy_data) * 100, 1),
                "late_pct": round(late_count / len(accuracy_data) * 100, 1),
                "interpretation": (
                    "On time" if abs(avg_delta) < 1 else
                    f"Average {abs(avg_delta):.1f}m {'early' if avg_delta < 0 else 'late'}"
                )
            },
            "by_destination": dest_metrics,
            "trend": trend
        }
    
    except Exception as e:
        logger.error(f"Error getting accuracy metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))