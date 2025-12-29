import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from luas_client import fetch_luas_forecast, LuasAPIError
from database import SessionLocal, LuasSnapshot

logger = logging.getLogger(__name__)


def poll_luas_and_store():
    """
    Background job that runs every 30 seconds.
    Fetches latest forecasts and stores them in the database.
    """
    try:
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        forecasts = loop.run_until_complete(fetch_luas_forecast())
        loop.close()
        
        # Store in database
        db = SessionLocal()
        try:
            for forecast in forecasts:
                snapshot = LuasSnapshot(
                    stop_code="cab",
                    direction=forecast["direction"],
                    destination=forecast["destination"],
                    forecast_arrival_minutes=forecast["due_minutes"],
                    forecast_arrival_time=datetime.fromisoformat(forecast["due_time"]),
                    recorded_at=datetime.utcnow()
                )
                db.add(snapshot)
            
            db.commit()
            logger.info(f"Stored {len(forecasts)} forecast snapshots")
        
        except Exception as e:
            db.rollback()
            logger.error(f"Error storing forecasts: {e}")
        finally:
            db.close()
    
    except LuasAPIError as e:
        logger.error(f"Luas API error during polling: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in polling job: {e}")


def start_luas_polling(scheduler: BackgroundScheduler):
    """
    Start the background polling job.
    Polls the Luas API every 30 seconds.
    """
    scheduler.add_job(
        poll_luas_and_store,
        "interval",
        seconds=30,
        id="luas_polling",
        name="Poll Luas API and store forecasts",
        replace_existing=True
    )
    logger.info("Luas polling job scheduled (every 30 seconds)")
