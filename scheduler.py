import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from luas_client import fetch_luas_forecast, LuasAPIError
from database import SessionLocal, LuasSnapshot, LuasAccuracy

logger = logging.getLogger(__name__)

# Stops to poll - major stops on both lines
STOPS_TO_POLL = [
    "cab",  # Cabra
    "tal",  # Tallaght
    "con",  # Connolly
    "fou",  # Four Courts
    "jer",  # Jervis
    "bri",  # Broombridge
    "bus",  # Busáras
    "tem",  # Temple Bar
    "lep",  # Leopardstown
    "dro",  # Drury Street
]


def calculate_accuracy_from_snapshots():
    """
    Calculate forecast accuracy by comparing snapshots.
    
    Algorithm:
    - Look for the same tram (destination + direction) in consecutive polls
    - When forecast_arrival_minutes approaches 0, compare original forecast to elapsed time
    - Store accuracy delta in LuasAccuracy table
    
    Runs every 5 minutes to process recently arrived trams
    """
    try:
        db = SessionLocal()
        
        # Get snapshots from the last 2 hours
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        recent_snapshots = db.query(LuasSnapshot).filter(
            LuasSnapshot.recorded_at >= two_hours_ago
        ).all()
        
        if not recent_snapshots:
            logger.debug("No snapshots to calculate accuracy from")
            db.close()
            return
        
        # Group by (stop, direction, destination) to track same tram across polls
        from collections import defaultdict
        tram_history = defaultdict(list)
        
        for snapshot in recent_snapshots:
            key = (snapshot.stop_code, snapshot.direction, snapshot.destination)
            tram_history[key].append(snapshot)
        
        accuracy_count = 0
        
        # For each tram type, look for ones that "arrived"
        for (stop_code, direction, destination), polls in tram_history.items():
            # Sort by recorded_at
            polls.sort(key=lambda x: x.recorded_at)
            
            # Look for transitions from predicted to arriving (forecast_arrival_minutes going to 0 or negative)
            for i in range(1, len(polls)):
                prev_poll = polls[i-1]
                curr_poll = polls[i]
                
                # Check if this tram is arriving now (forecast went to 0 or negative)
                if (prev_poll.forecast_arrival_minutes > 0 and 
                    curr_poll.forecast_arrival_minutes <= 0):
                    
                    # Time elapsed between these two forecasts (in minutes)
                    time_elapsed_seconds = (curr_poll.recorded_at - prev_poll.recorded_at).total_seconds()
                    time_elapsed_minutes = time_elapsed_seconds / 60
                    
                    # Original forecast was prev_poll.forecast_arrival_minutes
                    # Actual time to arrival was approximately time_elapsed_minutes
                    # Accuracy delta: positive = late, negative = early
                    accuracy_delta = int(round(time_elapsed_minutes - prev_poll.forecast_arrival_minutes))
                    
                    # Don't record if it's impossible (more than 60 min difference = data error)
                    if abs(accuracy_delta) > 60:
                        logger.warning(f"Skipping accuracy (likely data error): {destination} delta={accuracy_delta}")
                        continue
                    
                    # Check if we already recorded this accuracy (avoid duplicates)
                    existing = db.query(LuasAccuracy).filter(
                        LuasAccuracy.stop_code == stop_code,
                        LuasAccuracy.direction == direction,
                        LuasAccuracy.destination == destination,
                        LuasAccuracy.forecasted_minutes == prev_poll.forecast_arrival_minutes,
                        LuasAccuracy.calculated_at >= (curr_poll.recorded_at - timedelta(seconds=60))
                    ).first()
                    
                    if existing:
                        continue
                    
                    accuracy_record = LuasAccuracy(
                        stop_code=stop_code,
                        direction=direction,
                        destination=destination,
                        forecasted_minutes=prev_poll.forecast_arrival_minutes,
                        actual_minutes=int(round(time_elapsed_minutes)),
                        accuracy_delta=accuracy_delta,
                        calculated_at=datetime.utcnow()
                    )
                    
                    db.add(accuracy_record)
                    accuracy_count += 1
                    logger.info(f"Recorded accuracy: {destination} ({direction}) - forecasted {prev_poll.forecast_arrival_minutes}m, actual {int(round(time_elapsed_minutes))}m (delta: {accuracy_delta}m)")
        
        if accuracy_count > 0:
            db.commit()
            logger.info(f"Calculated and stored {accuracy_count} accuracy records")
        
        db.close()
    
    except Exception as e:
        if 'db' in locals():
            db.rollback()
            db.close()
        logger.error(f"Error calculating accuracy: {e}")


def poll_luas_and_store():
    """
    Background job that runs every 30 seconds.
    Fetches latest forecasts for all configured stops and stores them in the database.
    """
    total_stored = 0
    
    for stop_code in STOPS_TO_POLL:
        try:
            # Run async function in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            forecasts = loop.run_until_complete(fetch_luas_forecast(stop_code))
            loop.close()
            
            # Store in database
            db = SessionLocal()
            try:
                for forecast in forecasts:
                    snapshot = LuasSnapshot(
                        stop_code=stop_code,
                        direction=forecast["direction"],
                        destination=forecast["destination"],
                        forecast_arrival_minutes=forecast["due_minutes"],
                        forecast_arrival_time=datetime.fromisoformat(forecast["due_time"]),
                        recorded_at=datetime.utcnow()
                    )
                    db.add(snapshot)
                
                db.commit()
                total_stored += len(forecasts)
                logger.info(f"Stored {len(forecasts)} forecast snapshots for stop {stop_code}")
            
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing forecasts for stop {stop_code}: {e}")
            finally:
                db.close()
        
        except LuasAPIError as e:
            logger.error(f"Luas API error polling {stop_code}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error polling {stop_code}: {e}")
    
    if total_stored > 0:
        logger.info(f"Polling cycle complete: stored {total_stored} total forecasts")


def start_luas_polling(scheduler: BackgroundScheduler):
    """
    Start the background polling jobs.
    - Polls the Luas API every 30 seconds for all configured stops
    - Calculates accuracy every 5 minutes
    """
    scheduler.add_job(
        poll_luas_and_store,
        "interval",
        seconds=30,
        id="luas_polling",
        name="Poll Luas API and store forecasts for all stops",
        replace_existing=True
    )
    logger.info("Luas polling job scheduled (every 30 seconds for multiple stops)")
    
    # Add accuracy calculation job
    scheduler.add_job(
        calculate_accuracy_from_snapshots,
        "interval",
        minutes=5,
        id="accuracy_calculation",
        name="Calculate forecast accuracy from snapshots",
        replace_existing=True
    )
    logger.info("Accuracy calculation job scheduled (every 5 minutes)")
