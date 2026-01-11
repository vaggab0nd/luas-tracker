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
    # Green Line major stops
    "bro",  # Broombridge
    "cab",  # Cabra
    "sts",  # St. Stephen's Green
    "ran",  # Ranelagh
    "san",  # Sandyford
    "bri",  # Brides Glen

    # Red Line major stops
    "tal",  # Tallaght
    "red",  # Red Cow
    "heu",  # Heuston
    "jer",  # Jervis
    "con",  # Connolly
    "tpt",  # The Point
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

        logger.info(f"Accuracy calculation: Retrieved {len(recent_snapshots)} snapshots from last 2 hours")

        if not recent_snapshots:
            logger.info("No snapshots to calculate accuracy from - database may be empty or too new")
            db.close()
            return
        
        # Group by (stop, direction, destination) to track same tram across polls
        from collections import defaultdict
        tram_history = defaultdict(list)

        for snapshot in recent_snapshots:
            # Group by stop/direction/destination to track tram progression
            key = (snapshot.stop_code, snapshot.direction, snapshot.destination)
            tram_history[key].append(snapshot)

        logger.info(f"Accuracy calculation: Grouped into {len(tram_history)} unique tram routes")

        accuracy_count = 0
        
        # For each tram type, look for ones that "arrived"
        for (stop_code, direction, destination), polls in tram_history.items():
            # Sort by recorded_at time
            polls.sort(key=lambda x: x.recorded_at)

            # Debug logging for all stops
            logger.info(f"Analyzing {stop_code}: {destination} ({direction}) - {len(polls)} polls found")
            if len(polls) >= 2:
                latest_forecasts = [p.forecast_arrival_minutes for p in polls[-5:]]
                logger.info(f"  Latest 5 forecasts: {latest_forecasts}")

            if len(polls) < 2:
                continue
            
            # Look for trams that went from being tracked to arriving (forecast decreased to 0)
            # Strategy: Find a tram that had a forecast, then in a later poll shows as "DUE" (0 minutes)
            # Also track near-arrivals (2→1, 1→0) to get more granular data
            for i in range(1, len(polls)):
                prev_poll = polls[i-1]
                curr_poll = polls[i]

                # Skip if polls are too far apart (more than 2 minutes = missed polls)
                time_between_polls = (curr_poll.recorded_at - prev_poll.recorded_at).total_seconds() / 60
                if time_between_polls > 2:
                    logger.debug(f"DEBUG {stop_code}: Skipping {destination} - polls {time_between_polls:.1f}m apart (>2m threshold)")
                    continue

                # Track small forecast decrements to measure accuracy:
                # 1→0: Most reliable (tram just arrived)
                # 2→1: Fairly reliable (tram arriving soon)
                # 3→2: Less reliable but gives more data points

                is_arrival = False
                transition_type = None

                # NOTE: Without unique tram IDs, we can't reliably track the same tram across polls
                # A transition like 12→0 likely represents TWO DIFFERENT trams, not forecast accuracy
                # Only use small transitions where we're confident it's the same tram

                # Primary: Imminent arrival (1 to 0) - most reliable
                if (prev_poll.forecast_arrival_minutes == 1 and
                    curr_poll.forecast_arrival_minutes == 0):
                    is_arrival = True
                    transition_type = "imminent_arrival_1to0"
                    logger.info(f"DEBUG {stop_code}: Imminent arrival detected (1→0): {destination} ({direction})")

                # Secondary: Near-arrival tracking (2 to 1) - fairly reliable
                elif (prev_poll.forecast_arrival_minutes == 2 and
                      curr_poll.forecast_arrival_minutes == 1):
                    is_arrival = True
                    transition_type = "near_arrival_2to1"
                    logger.info(f"DEBUG {stop_code}: Near-arrival detected (2→1): {destination} ({direction})")

                # Tertiary: 3 to 2 transition - less reliable but still useful
                elif (prev_poll.forecast_arrival_minutes == 3 and
                      curr_poll.forecast_arrival_minutes == 2):
                    is_arrival = True
                    transition_type = "near_arrival_3to2"
                    logger.info(f"DEBUG {stop_code}: Near-arrival detected (3→2): {destination} ({direction})")

                if is_arrival:
                    # The tram transitioned between prev_poll and curr_poll
                    # Original forecast from prev_poll: "arriving in X minutes"
                    original_forecast_minutes = prev_poll.forecast_arrival_minutes

                    # For X→(X-1) transitions, assume tram arrived at midpoint of polling interval
                    # This gives us a reasonable estimate of actual arrival time
                    estimated_actual_minutes = time_between_polls / 2

                    # Calculate accuracy delta
                    # Positive = arrived later than forecast, Negative = arrived earlier
                    accuracy_delta = int(round(estimated_actual_minutes - original_forecast_minutes))

                    # Sanity check: for 1-3 minute forecasts with 30s polls, delta should be within ±2 minutes
                    if abs(accuracy_delta) > 2:
                        logger.debug(f"Skipping accuracy (unexpected delta): {destination} delta={accuracy_delta}m")
                        continue
                    
                    # Check if we already recorded this (only in last 2 minutes to avoid duplicates)
                    # Use a 2-minute window since job runs every 1 minute
                    existing = db.query(LuasAccuracy).filter(
                        LuasAccuracy.stop_code == stop_code,
                        LuasAccuracy.direction == direction,
                        LuasAccuracy.destination == destination,
                        LuasAccuracy.forecasted_minutes == original_forecast_minutes,
                        LuasAccuracy.calculated_at >= (datetime.utcnow() - timedelta(minutes=2))
                    ).first()
                    
                    if existing:
                        logger.debug(f"Duplicate accuracy record skipped: {destination}")
                        continue

                    accuracy_record = LuasAccuracy(
                        stop_code=stop_code,
                        direction=direction,
                        destination=destination,
                        forecasted_minutes=original_forecast_minutes,
                        actual_minutes=int(round(estimated_actual_minutes)),
                        accuracy_delta=accuracy_delta,
                        calculated_at=datetime.utcnow()
                    )
                    
                    db.add(accuracy_record)
                    accuracy_count += 1
                    status = "on time" if accuracy_delta == 0 else f"{abs(accuracy_delta)}m {'early' if accuracy_delta < 0 else 'late'}"
                    logger.info(f"✓ Accuracy [{transition_type}]: {destination} ({direction}) at {stop_code} - forecast {original_forecast_minutes}m, actual {int(round(estimated_actual_minutes))}m ({status})")

        logger.info(f"Accuracy calculation complete: Analyzed {len(tram_history)} routes, found {accuracy_count} accuracy records")
        logger.info(f"About to commit {accuracy_count} accuracy records...")
        if accuracy_count > 0:
            try:
                logger.info(f"Attempting db.commit() with {accuracy_count} pending records...")
                db.commit()
                logger.info(f"✓ SUCCESS: db.commit() completed. Records should now be in database.")
            except Exception as commit_error:
                logger.error(f"❌ COMMIT FAILED: {type(commit_error).__name__}: {commit_error}", exc_info=True)
                try:
                    db.rollback()
                    logger.info("Rollback completed")
                except:
                    logger.error("Rollback also failed")
        else:
            logger.info("No accuracy records to commit this cycle")
        
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
    try:
        scheduler.add_job(
            poll_luas_and_store,
            "interval",
            seconds=30,
            id="luas_polling",
            name="Poll Luas API and store forecasts for all stops",
            replace_existing=True
        )
        logger.info("✓ Luas polling job scheduled (every 30 seconds)")
    except Exception as e:
        logger.error(f"❌ FAILED to schedule luas_polling: {e}", exc_info=True)
    
    # Add accuracy calculation job
    try:
        scheduler.add_job(
            calculate_accuracy_from_snapshots,
            "interval",
            minutes=1,
            id="accuracy_calculation",
            name="Calculate forecast accuracy from snapshots",
            replace_existing=True
        )
        logger.info("✓ Accuracy calculation job scheduled (every 1 minute)")
    except Exception as e:
        logger.error(f"❌ FAILED to schedule accuracy_calculation: {e}", exc_info=True)
