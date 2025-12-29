from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel

from database import get_db, LuasSnapshot, LuasAccuracy

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


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """
    Get general stats about the system.
    """
    total_snapshots = db.query(func.count(LuasSnapshot.id)).scalar()
    latest_snapshot = db.query(func.max(LuasSnapshot.recorded_at)).scalar()
    
    return {
        "total_snapshots_stored": total_snapshots,
        "latest_poll": latest_snapshot.isoformat() if latest_snapshot else None
    }
