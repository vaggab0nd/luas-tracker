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
    # GREEN LINE (35 stops - Broombridge to Brides Glen)
    "bro": {"name": "Broombridge", "line": "Green"},
    "cab": {"name": "Cabra", "line": "Green"},
    "phi": {"name": "Phibsborough", "line": "Green"},
    "gra": {"name": "Grangegorman", "line": "Green"},
    "brd": {"name": "Broadstone - University", "line": "Green"},
    "dom": {"name": "Dominick", "line": "Green"},
    "par": {"name": "Parnell", "line": "Green"},
    "mar": {"name": "Marlborough", "line": "Green"},
    "tri": {"name": "Trinity", "line": "Green"},
    "oup": {"name": "O'Connell Upper", "line": "Green"},
    "ogp": {"name": "O'Connell - GPO", "line": "Green"},
    "wes": {"name": "Westmoreland", "line": "Green"},
    "daw": {"name": "Dawson", "line": "Green"},
    "sts": {"name": "St. Stephen's Green", "line": "Green"},
    "har": {"name": "Harcourt", "line": "Green"},
    "cha": {"name": "Charlemont", "line": "Green"},
    "ran": {"name": "Ranelagh", "line": "Green"},
    "bee": {"name": "Beechwood", "line": "Green"},
    "cow": {"name": "Cowper", "line": "Green"},
    "mil": {"name": "Milltown", "line": "Green"},
    "win": {"name": "Windy Arbour", "line": "Green"},
    "dun": {"name": "Dundrum", "line": "Green"},
    "bal": {"name": "Balally", "line": "Green"},
    "kil": {"name": "Kilmacud", "line": "Green"},
    "sti": {"name": "Stillorgan", "line": "Green"},
    "san": {"name": "Sandyford", "line": "Green"},
    "cpk": {"name": "Central Park", "line": "Green"},
    "gle": {"name": "Glencairn", "line": "Green"},
    "gal": {"name": "The Gallops", "line": "Green"},
    "leo": {"name": "Leopardstown Valley", "line": "Green"},
    "baw": {"name": "Ballyogan Wood", "line": "Green"},
    "car": {"name": "Carrickmines", "line": "Green"},
    "lau": {"name": "Laughanstown", "line": "Green"},
    "che": {"name": "Cherrywood", "line": "Green"},
    "bri": {"name": "Brides Glen", "line": "Green"},

    # RED LINE (32 stops - Saggart/Tallaght to The Point)
    "sag": {"name": "Saggart", "line": "Red"},
    "tal": {"name": "Tallaght", "line": "Red"},
    "hos": {"name": "Hospital", "line": "Red"},
    "coo": {"name": "Cookstown", "line": "Red"},
    "for": {"name": "Fortunestown", "line": "Red"},
    "cit": {"name": "Citywest Campus", "line": "Red"},
    "cvn": {"name": "Cheeverstown", "line": "Red"},
    "fet": {"name": "Fettercairn", "line": "Red"},
    "bel": {"name": "Belgard", "line": "Red"},
    "kin": {"name": "Kingswood", "line": "Red"},
    "red": {"name": "Red Cow", "line": "Red"},
    "kyl": {"name": "Kylemore", "line": "Red"},
    "blu": {"name": "Bluebell", "line": "Red"},
    "blh": {"name": "Blackhorse", "line": "Red"},
    "dri": {"name": "Drimnagh", "line": "Red"},
    "gol": {"name": "Goldenbridge", "line": "Red"},
    "sui": {"name": "Suir Road", "line": "Red"},
    "ria": {"name": "Rialto", "line": "Red"},
    "fat": {"name": "Fatima", "line": "Red"},
    "jam": {"name": "James's", "line": "Red"},
    "heu": {"name": "Heuston", "line": "Red"},
    "mus": {"name": "Museum", "line": "Red"},
    "smi": {"name": "Smithfield", "line": "Red"},
    "fou": {"name": "Four Courts", "line": "Red"},
    "jer": {"name": "Jervis", "line": "Red"},
    "abb": {"name": "Abbey Street", "line": "Red"},
    "bus": {"name": "Busáras", "line": "Red"},
    "con": {"name": "Connolly", "line": "Red"},
    "gdk": {"name": "George's Dock", "line": "Red"},
    "mys": {"name": "Mayor Square - NCI", "line": "Red"},
    "sdk": {"name": "Spencer Dock", "line": "Red"},
    "tpt": {"name": "The Point", "line": "Red"},
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
    Returns stops organized by line with their codes in route order.
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
            "green": green_line,  # Maintains insertion order from dict (route order)
            "red": red_line
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
async def get_accuracy_summary(db: Session = Depends(get_db), stop_code: str = "cab", hours: int = 24):
    """
    Get forecast accuracy metrics for a specific stop.
    Parameters:
    - stop_code: Stop code (e.g., bro, cab, sts, tal, jer, con, etc. - see /stops for full list)
    - hours: Number of hours to look back (default 24)
    """
    logger.info(f"GET /accuracy/summary called with stop_code={stop_code}, hours={hours}")

    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        logger.info(f"Cutoff time: {cutoff_time.isoformat()}")

        # First, check total records for debugging
        total_records = db.query(func.count(LuasAccuracy.id)).scalar()
        logger.info(f"Total accuracy records in database: {total_records}")

        # Check records for this stop (no time filter)
        stop_records = db.query(func.count(LuasAccuracy.id)).filter(
            LuasAccuracy.stop_code == stop_code
        ).scalar()
        logger.info(f"Total accuracy records for stop {stop_code}: {stop_records}")

        # Check records for this stop within time window
        recent_records = db.query(func.count(LuasAccuracy.id)).filter(
            LuasAccuracy.stop_code == stop_code,
            LuasAccuracy.calculated_at >= cutoff_time
        ).scalar()
        logger.info(f"Accuracy records for stop {stop_code} in last {hours}h: {recent_records}")

        # Query accuracy data grouped by destination/direction for the specified stop
        accuracy_data = db.query(
            LuasAccuracy.destination,
            LuasAccuracy.direction,
            func.count(LuasAccuracy.id).label("count"),
            func.avg(LuasAccuracy.accuracy_delta).label("avg_delta"),
            func.min(LuasAccuracy.accuracy_delta).label("min_delta"),
            func.max(LuasAccuracy.accuracy_delta).label("max_delta")
        ).filter(
            LuasAccuracy.stop_code == stop_code,
            LuasAccuracy.calculated_at >= cutoff_time
        ).group_by(
            LuasAccuracy.destination,
            LuasAccuracy.direction
        ).all()

        logger.info(f"Grouped accuracy data returned {len(accuracy_data)} rows")

        if not accuracy_data:
            # Get sample records to help debug
            sample = db.query(LuasAccuracy).limit(5).all()
            sample_info = [
                {
                    "stop_code": s.stop_code,
                    "calculated_at": s.calculated_at.isoformat(),
                    "destination": s.destination
                }
                for s in sample
            ]

            return {
                "stop_code": stop_code,
                "period_hours": hours,
                "message": f"No accuracy data found for stop '{stop_code}' in the last {hours} hours",
                "debug_info": {
                    "total_records_in_db": total_records,
                    "records_for_this_stop": stop_records,
                    "sample_records": sample_info
                },
                "data": []
            }

        return {
            "stop_code": stop_code,
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
        logger.error(f"Error in accuracy/summary: {e}", exc_info=True)
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


@router.get("/debug/accuracy/by-stop")
async def debug_accuracy_by_stop(db: Session = Depends(get_db)):
    """Debug endpoint to see accuracy records by stop"""
    from collections import defaultdict

    # Get all unique stop codes and their counts
    stop_counts = db.query(
        LuasAccuracy.stop_code,
        func.count(LuasAccuracy.id).label("count")
    ).group_by(LuasAccuracy.stop_code).all()

    logger.info(f"Found accuracy data for {len(stop_counts)} unique stops")
    for stop, count in stop_counts:
        logger.info(f"  {stop}: {count} records")

    all_records = db.query(LuasAccuracy).order_by(desc(LuasAccuracy.calculated_at)).limit(100).all()

    by_stop = defaultdict(list)
    for record in all_records:
        by_stop[record.stop_code].append({
            "destination": record.destination,
            "direction": record.direction,
            "delta": record.accuracy_delta,
            "calculated_at": record.calculated_at.isoformat()
        })

    return {
        "total_records": len(all_records),
        "stop_counts": {stop: count for stop, count in stop_counts},
        "by_stop": {
            stop: records[:5]  # First 5 for each stop
            for stop, records in by_stop.items()
        }
    }


@router.get("/debug/accuracy/count")
async def debug_accuracy_count(db: Session = Depends(get_db)):
    """Debug endpoint to see how many accuracy records exist"""
    total_count = db.query(func.count(LuasAccuracy.id)).scalar()
    recent_count = db.query(func.count(LuasAccuracy.id)).filter(
        LuasAccuracy.calculated_at >= (datetime.utcnow() - timedelta(hours=24))
    ).scalar()

    # Also check snapshots table for comparison
    total_snapshots = db.query(func.count(LuasSnapshot.id)).scalar()
    recent_snapshots = db.query(func.count(LuasSnapshot.id)).filter(
        LuasSnapshot.recorded_at >= (datetime.utcnow() - timedelta(hours=24))
    ).scalar()

    # Get sample records
    samples = db.query(LuasAccuracy).order_by(desc(LuasAccuracy.calculated_at)).limit(5).all()

    return {
        "luas_accuracy_table": {
            "total_records": total_count,
            "records_in_last_24h": recent_count,
            "sample_records": [
                {
                    "stop_code": s.stop_code,
                    "destination": s.destination,
                    "direction": s.direction,
                    "forecasted": s.forecasted_minutes,
                    "actual": s.actual_minutes,
                    "delta": s.accuracy_delta,
                    "calculated_at": s.calculated_at.isoformat()
                }
                for s in samples
            ]
        },
        "luas_snapshots_table": {
            "total_records": total_snapshots,
            "records_in_last_24h": recent_snapshots,
        }
    }


@router.get("/debug/snapshots/transitions")
async def debug_snapshot_transitions(db: Session = Depends(get_db), stop_code: str = "cab", minutes: int = 30):
    """
    Debug endpoint to see forecast transitions for a specific stop.
    Shows how forecasts change over time to diagnose why accuracy isn't being calculated.
    """
    from collections import defaultdict

    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)

    # Get recent snapshots for this stop
    snapshots = db.query(LuasSnapshot).filter(
        LuasSnapshot.stop_code == stop_code,
        LuasSnapshot.recorded_at >= cutoff_time
    ).order_by(LuasSnapshot.recorded_at.desc()).all()

    # Group by destination/direction to track tram progression
    tram_history = defaultdict(list)
    for snapshot in snapshots:
        key = (snapshot.destination, snapshot.direction)
        tram_history[key].append({
            "forecast_minutes": snapshot.forecast_arrival_minutes,
            "recorded_at": snapshot.recorded_at.isoformat()
        })

    # Analyze transitions for each tram route
    transitions = {}
    for (dest, direction), history in tram_history.items():
        # Sort by time (oldest first)
        history.sort(key=lambda x: x["recorded_at"])

        # Find transitions
        found_transitions = []
        for i in range(1, len(history)):
            prev = history[i-1]["forecast_minutes"]
            curr = history[i]["forecast_minutes"]
            if prev != curr:
                found_transitions.append({
                    "from": prev,
                    "to": curr,
                    "time": history[i]["recorded_at"]
                })

        transitions[f"{dest} ({direction})"] = {
            "total_snapshots": len(history),
            "forecast_range": f"{min(h['forecast_minutes'] for h in history)}-{max(h['forecast_minutes'] for h in history)} minutes",
            "transitions_found": len(found_transitions),
            "sample_transitions": found_transitions[:10]
        }

    return {
        "stop_code": stop_code,
        "period_minutes": minutes,
        "total_snapshots": len(snapshots),
        "unique_routes": len(tram_history),
        "routes": transitions
    }


@router.get("/debug/data-collection")
async def debug_data_collection(db: Session = Depends(get_db)):
    """
    Debug endpoint to check if data collection (polling) is working.
    Returns status of the background polling job.
    """
    try:
        # Check when the last snapshot was recorded
        latest_snapshot = db.query(LuasSnapshot).order_by(
            desc(LuasSnapshot.recorded_at)
        ).first()

        if not latest_snapshot:
            return {
                "status": "no_data",
                "healthy": False,
                "message": "No data collected yet - polling may not have started",
                "last_poll": None,
                "seconds_ago": None
            }

        # Calculate how long ago the last poll was
        now = datetime.utcnow()
        time_since_last_poll = (now - latest_snapshot.recorded_at).total_seconds()

        # Polling runs every 30 seconds, so if last poll was >90 seconds ago, something is wrong
        is_healthy = time_since_last_poll < 90

        return {
            "status": "healthy" if is_healthy else "stale",
            "healthy": is_healthy,
            "message": (
                "Data collection is active" if is_healthy
                else f"Last poll was {int(time_since_last_poll)}s ago - polling may have stopped"
            ),
            "last_poll": latest_snapshot.recorded_at.isoformat(),
            "seconds_ago": int(time_since_last_poll),
            "last_stop_polled": latest_snapshot.stop_code,
            "polling_interval_seconds": 30
        }

    except Exception as e:
        logger.error(f"Error checking data collection status: {e}")
        return {
            "status": "error",
            "healthy": False,
            "message": f"Error checking data collection: {str(e)}",
            "last_poll": None,
            "seconds_ago": None
        }


@router.get("/debug/database")
async def debug_database(db: Session = Depends(get_db)):
    """
    Debug endpoint to check database connectivity and health.
    Verifies the database is accessible and data is being written.
    """
    try:
        # Test 1: Basic connectivity - count snapshots
        snapshot_count = db.query(func.count(LuasSnapshot.id)).scalar()

        # Test 2: Count accuracy records
        accuracy_count = db.query(func.count(LuasAccuracy.id)).scalar()

        # Test 3: Check recent writes (last 5 minutes)
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        recent_snapshots = db.query(func.count(LuasSnapshot.id)).filter(
            LuasSnapshot.recorded_at >= five_minutes_ago
        ).scalar()

        # Test 4: Get latest record timestamp
        latest_record = db.query(LuasSnapshot).order_by(
            desc(LuasSnapshot.recorded_at)
        ).first()

        # Database is healthy if we can query it and have recent data
        is_healthy = snapshot_count > 0 and recent_snapshots > 0

        return {
            "status": "healthy" if is_healthy else "degraded",
            "healthy": is_healthy,
            "message": (
                "Database is connected and receiving data" if is_healthy
                else "Database connected but no recent data"
            ),
            "total_snapshots": snapshot_count,
            "total_accuracy_records": accuracy_count,
            "snapshots_last_5min": recent_snapshots,
            "latest_record_time": latest_record.recorded_at.isoformat() if latest_record else None,
            "connection": "ok"
        }

    except Exception as e:
        logger.error(f"Error checking database health: {e}")
        return {
            "status": "error",
            "healthy": False,
            "message": f"Database error: {str(e)}",
            "connection": "failed"
        }


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