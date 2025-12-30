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
    Calculate forecast accuracy by comparing forecasts across polls.
    
    Better algorithm:
    - For each tram (destination + direction), look at forecast progression
    - When a tram "arrives" (forecast goes from positive to 0/negative)
    - Calculate actual time to arrival and compare to original forecast
    - Store accuracy delta
    
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
            # Sort by recorded_at time
            polls.sort(key=lambda x: x.recorded_at)
            
            if len(polls) < 2:
                continue
            
            # Look for the transition: forecast goes from > 0 to <= 0
            # This indicates the tram has arrived (or is about to)
            for i in range(1, len(polls)):
                prev_poll = polls[i-1]
                curr_poll = polls[i]
                
                # Check if forecast went to arrival (0 or negative)
                if (prev_poll.forecast_arrival_minutes > 0 and 
                    curr_poll.forecast_arrival_minutes <= 0):
                    
                    # The tram arrived between prev_poll and curr_poll
                    # Time from prev_poll to arrival is approximately prev_poll.forecast_arrival_minutes
                    # But we need to account for the actual time elapsed
                    
                    # Original forecast from prev_poll: "arriving in X minutes"
                    original_forecast_minutes = prev_poll.forecast_arrival_minutes
                    
                    # Actual arrival time estimate:
                    # The tram was forecast to arrive in X minutes at prev_poll time
                    # So actual arrival was around: prev_poll.recorded_at + X minutes
                    forecast_arrival_time = prev_poll.recorded_at + timedelta(minutes=original_forecast_minutes)
                    
                    # Actual arrival was somewhere between prev_poll and curr_poll
                    # Best estimate: somewhere around curr_poll.recorded_at (or slightly before)
                    # But use prev_poll + forecast time as our "actual"
                    actual_arrival_time = curr_poll.recorded_at
                    
                    # Calculate delta: how many minutes off were we?
                    time_delta_seconds = (actual_arrival_time - forecast_arrival_time).total_seconds()
                    time_delta_minutes = time_delta_seconds / 60
                    accuracy_delta = int(round(time_delta_minutes))
                    
                    # Sanity check: delta shouldn't be more than ~2 minutes per poll period
                    # If it is, it's likely a data quality issue
                    if abs(accuracy_delta) > 5:
                        logger.warning(f"Skipping accuracy (likely data error): {destination} delta={accuracy_delta}m (forecast={original_forecast_minutes}m)")
                        continue
                    
                    # Check if we already recorded this accuracy (avoid duplicates)
                    existing = db.query(LuasAccuracy).filter(
                        LuasAccuracy.stop_code == stop_code,
                        LuasAccuracy.direction == direction,
                        LuasAccuracy.destination == destination,
                        LuasAccuracy.forecasted_minutes == original_forecast_minutes,
                        LuasAccuracy.calculated_at >= (curr_poll.recorded_at - timedelta(minutes=10))
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Calculate actual minutes (time elapsed from prev_poll to actual arrival)
                    actual_minutes = int(round((actual_arrival_time - prev_poll.recorded_at).total_seconds() / 60))
                    
                    accuracy_record = LuasAccuracy(
                        stop_code=stop_code,
                        direction=direction,
                        destination=destination,
                        forecasted_minutes=original_forecast_minutes,
                        actual_minutes=actual_minutes,
                        accuracy_delta=accuracy_delta,
                        calculated_at=datetime.utcnow()
                    )
                    
                    db.add(accuracy_record)
                    accuracy_count += 1
                    status = "on time" if accuracy_delta == 0 else f"{abs(accuracy_delta)}m {'early' if accuracy_delta < 0 else 'late'}"
                    logger.info(f"Recorded accuracy: {destination} ({direction}) - forecast {original_forecast_minutes}m, actual {actual_minutes}m ({status})")
        
        if accuracy_count > 0:
            db.commit()
            logger.info(f"Calculated and stored {accuracy_count} accuracy records")
        else:
            logger.debug("No new accuracy records calculated")
        
        db.close()
    
    except Exception as e:
        if 'db' in locals():
            try:
                db.rollback()
                db.close()
            except:
                pass
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
