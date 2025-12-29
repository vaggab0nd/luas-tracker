from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel

from database import get_db, LuasSnapshot, LuasAccuracy

router = APIRouter()


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


@router.get("/arrivals/cabra", response_model=CurrentArrivalsResponse)
async def get_cabra_arrivals(db: Session = Depends(get_db), limit: int = 3):
    """
    Get the next N upcoming trams for Cabra stop.
    Returns the most recent forecast for each unique destination/direction combo.
    """
    try:
        # Get the most recent snapshot timestamp
        latest_snapshot = db.query(func.max(LuasSnapshot.recorded_at)).scalar()
        
        if not latest_snapshot:
            raise HTTPException(
                status_code=404,
                detail="No forecast data available yet. Polling will start soon."
            )
        
        # Get forecasts from the latest snapshot, ordered by arrival time
        forecasts = db.query(LuasSnapshot).filter(
            LuasSnapshot.recorded_at == latest_snapshot,
            LuasSnapshot.stop_code == "cab"
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
        
        return CurrentArrivalsResponse(
            stop_code="cab",
            last_updated=latest_snapshot.isoformat(),
            next_arrivals=arrivals
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
