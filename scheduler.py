import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from luas_client import fetch_luas_forecast, LuasAPIError
from database import SessionLocal, LuasSnapshot

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
    Start the background polling job.
    Polls the Luas API every 30 seconds for all configured stops.
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
