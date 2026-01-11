# CLAUDE.MD - Luas Tracker Project Guide

This document provides comprehensive context about the Luas Real-Time Tracker project for AI assistance.

## Project Overview

A full-stack learning project that tracks real-time arrivals for Dublin's Luas tram network. The system polls the Luas API every 30 seconds, stores forecast data, calculates accuracy metrics, and serves this data through a REST API.

**Primary Goals:**
- Learn full-stack development with real API integration
- Track how Luas arrival forecasts change over time
- Measure forecast accuracy by comparing predictions to actual arrivals
- Provide a clean API for frontend consumption

## Tech Stack

- **Backend**: Python 3.9+ with FastAPI
- **Database**: PostgreSQL (production) / SQLite (development)
- **ORM**: SQLAlchemy 2.0
- **Scheduling**: APScheduler (background jobs)
- **HTTP Client**: httpx (async)
- **Testing**: pytest with pytest-asyncio
- **ASGI Server**: uvicorn

## Project Structure

```
luas-tracker/
├── main.py              # FastAPI app entry point, CORS, lifespan management
├── database.py          # SQLAlchemy models (LuasSnapshot, LuasAccuracy), engine setup
├── routes.py            # API endpoints (arrivals, accuracy, debug endpoints)
├── luas_client.py       # Luas API client, XML parsing
├── scheduler.py         # Background jobs (polling, accuracy calculation)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── test_luas_tracker.py # Test suite
├── pytest.ini           # pytest configuration
├── TESTING.md           # Testing documentation
└── README.md            # User-facing documentation
```

## Architecture & Data Flow

### 1. Background Polling (scheduler.py)

**Job: `poll_luas_and_store`** (runs every 30 seconds)
- Polls 12 stops across both Luas lines (Green and Red)
- Calls `fetch_luas_forecast()` for each stop
- Stores raw forecast data in `luas_snapshots` table
- Handles API errors gracefully and logs failures

**Stops monitored:**
- Green Line: Broombridge, Cabra, St. Stephen's Green, Ranelagh, Sandyford, Brides Glen
- Red Line: Tallaght, Red Cow, Heuston, Jervis, Connolly, The Point

### 2. Luas API Integration (luas_client.py)

**Endpoint:** `https://luasforecasts.rpa.ie/xml/get.ashx`

**XML Structure:**
```xml
<stopInfo>
  <direction name="Inbound">
    <tram dueMins="5" destination="Broombridge"/>
    <tram dueMins="DUE" destination="Phibsborough"/>
  </direction>
  <direction name="Outbound">
    <tram dueMins="12" destination="Brides Glen"/>
  </direction>
</stopInfo>
```

**Key Functions:**
- `fetch_luas_forecast(stop_code)`: Fetches and parses forecast data
- `parse_luas_xml(xml_content)`: Parses XML to Python dicts
- Handles "DUE" (0 minutes) and numeric values
- Filters out "No trams forecast" entries

### 3. Accuracy Calculation (scheduler.py)

**Job: `calculate_accuracy_from_snapshots`** (runs every 1 minute)

**Algorithm:**
1. Groups last 2 hours of snapshots by (stop, direction, destination)
2. Looks for forecast transitions that indicate arrival:
   - **1→0** (imminent arrival) - most reliable
   - **2→1** (near arrival) - fairly reliable
   - **3→2** (approaching) - less reliable but useful
3. Calculates accuracy delta: `actual_minutes - forecasted_minutes`
   - Negative = arrived early
   - Positive = arrived late
   - Zero = on time
4. Stores results in `luas_accuracy` table

**Important Notes:**
- Without unique tram IDs, only small transitions (1-3 minutes) are reliable
- Large transitions (e.g., 12→0) likely represent different trams
- Polls must be within 2 minutes of each other to be valid
- Deduplicates records within 2-minute windows

## Database Schema

### Table: `luas_snapshots`

Stores raw API poll data. Each record = one forecast at one point in time.

```python
id                       INTEGER PRIMARY KEY
stop_code                STRING (index)      # "cab", "tal", etc.
tram_id                  STRING              # Not provided by API (nullable)
direction                STRING              # "Inbound" or "Outbound"
destination              STRING              # "Broombridge", "Brides Glen", etc.
forecast_arrival_minutes INTEGER             # Minutes until arrival
forecast_arrival_time    DATETIME            # Calculated arrival time
recorded_at              DATETIME (index)    # When we polled the API
```

**Usage:**
- Serves current forecasts to frontend
- Source data for accuracy calculations
- Historical trending analysis

### Table: `luas_accuracy`

Stores calculated accuracy metrics by comparing forecast progression.

```python
id                  INTEGER PRIMARY KEY
stop_code           STRING (index)
tram_id             STRING              # Nullable (not available)
direction           STRING
destination         STRING
forecasted_minutes  INTEGER             # Original forecast (1-3 minutes)
actual_minutes      INTEGER             # Estimated actual arrival time
accuracy_delta      INTEGER             # Difference (negative=early, positive=late)
calculated_at       DATETIME (index)    # When we calculated this
```

**Usage:**
- Measures forecast quality over time
- Identifies patterns (routes/times with poor accuracy)
- Powers analytics and metrics endpoints

## API Endpoints

### Core Endpoints

**`GET /arrivals/{stop_code}?limit=3`**
- Returns next N arrivals for any stop
- Uses most recent snapshot from database
- Example: `/arrivals/cab?limit=5`

**`GET /arrivals/cabra?limit=3`**
- Legacy endpoint (backwards compatible)
- Redirects to `/arrivals/cab`

**`GET /stops`**
- Returns all 67 Luas stops organized by line
- Includes stop codes, names, and line assignment

**`GET /accuracy/summary?stop_code=cab&hours=24`**
- Accuracy metrics grouped by destination/direction
- Average delta, min/max, measurement count
- Defaults to Cabra stop, last 24 hours

**`GET /metrics/accuracy?stop_code=cab&hours=24`**
- Detailed accuracy metrics with trends
- Overall stats, by-destination breakdown, hourly trend data
- Includes on-time/early/late percentages

### Debug Endpoints

**`GET /debug/accuracy/count`**
- Total and recent accuracy record counts
- Sample records for inspection
- Snapshot counts for comparison

**`GET /debug/accuracy/by-stop`**
- Accuracy records grouped by stop
- Shows which stops have data
- Last 100 records with samples

**`GET /debug/accuracy/stops-summary`**
- Quick breakdown by line (Red/Green)
- Record counts per stop

**`GET /debug/snapshots/transitions?stop_code=cab&minutes=30`**
- Shows forecast transitions for a stop
- Helps diagnose accuracy calculation issues
- Sample transitions with timestamps

**`GET /debug/data-collection`**
- Checks if polling is active
- Last poll timestamp
- Healthy if polled within 90 seconds

**`GET /debug/database`**
- Database connectivity check
- Record counts and recent writes
- Latest record timestamp

**`GET /health`**
- Simple health check
- Returns `{"status": "ok"}`

## Common Development Patterns

### 1. Database Sessions

Always use dependency injection for database access:

```python
@router.get("/endpoint")
async def endpoint(db: Session = Depends(get_db)):
    # db is automatically provided and closed after request
    records = db.query(Model).all()
    return records
```

### 2. Error Handling

The codebase uses structured logging and graceful degradation:

```python
try:
    # operation
except SpecificError as e:
    logger.error(f"Context: {e}")
    # graceful fallback or re-raise as HTTPException
```

### 3. Async vs Sync

- API endpoints: async (FastAPI best practice)
- Background jobs: sync (APScheduler context)
- HTTP calls: async with httpx
- Database: sync with SQLAlchemy (uses thread pool)

### 4. Time Handling

- All database times are UTC (`datetime.utcnow()`)
- Frontend should convert to local timezone
- Accuracy calculations use timedelta for comparisons

## Running the Application

### Local Development

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure database
cp .env.example .env
# Edit .env with DATABASE_URL

# Initialize database
python -c "from database import init_db; init_db()"

# Run server
uvicorn main:app --reload
```

### Environment Variables

```bash
DATABASE_URL=sqlite:///./luas_tracker.db  # or postgresql://...
```

The app auto-converts `postgres://` to `postgresql://` for compatibility.

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific test
pytest test_luas_tracker.py::test_name -v
```

See `TESTING.md` for detailed testing documentation.

## Debugging Tips

### Issue: No accuracy data appearing

1. Check if polling is running: `GET /debug/data-collection`
2. Verify snapshots are being stored: `GET /debug/database`
3. Check for transitions: `GET /debug/snapshots/transitions?stop_code=cab`
4. Look at accuracy logs: Check server logs for "GREEN LINE ANALYSIS"
5. Verify accuracy job is scheduled: Check startup logs for "✓ Accuracy calculation job scheduled"

### Issue: Empty arrival responses

1. Check last poll time: `GET /debug/data-collection`
2. Verify stop code is valid: `GET /stops`
3. Check if API is returning data: Look for "API Response" in logs
4. Verify snapshots exist: `GET /debug/database`

### Issue: API returning 500 errors

1. Check logs for exceptions
2. Verify database connectivity: `GET /debug/database`
3. Check if tables exist: `python -c "from database import init_db; init_db()"`
4. Look for SQL errors in logs

## Known Issues & Limitations

1. **No unique tram IDs**: The Luas API doesn't provide tram identifiers, making it impossible to definitively track the same tram across polls. Accuracy calculations use small forecast transitions (1-3 minutes) as a proxy.

2. **Accuracy timing assumptions**: Assumes trams arrive at the midpoint between polls for X→(X-1) transitions. With 30-second polling, this is reasonably accurate.

3. **API rate limits**: The Luas API may have undocumented rate limits or IP restrictions. Current 30-second polling across 12 stops (24 req/min) seems safe.

4. **CORS**: Backend acts as a proxy to work around CORS restrictions on the Luas API.

5. **Green Line vs Red Line data**: Historically, Green Line has had less accuracy data than Red Line. This may be due to route patterns, API response differences, or forecast stability.

## Recent Changes & Context

- Added comprehensive debug endpoints to diagnose accuracy calculation issues
- Implemented multi-stop polling (12 stops across both lines)
- Enhanced accuracy calculation with detailed logging and transition analysis
- Added stop validation and comprehensive stop list (67 total stops)
- Improved error handling and graceful degradation

## Contributing Guidelines

When making changes:

1. **Preserve existing patterns**: Follow the established sync/async patterns
2. **Add logging**: Use `logger.info()` for significant events, `logger.error()` for failures
3. **Update tests**: Add/update tests in `test_luas_tracker.py`
4. **Document API changes**: Update README.md and CLAUDE.MD
5. **Handle errors gracefully**: Don't let one stop failure break entire polling cycle
6. **Use UTC for database times**: Always use `datetime.utcnow()` for timestamps

## Useful Commands

```bash
# Check logs in production
tail -f logs/app.log

# Manual database query
python -c "from database import SessionLocal, LuasSnapshot; db = SessionLocal(); print(db.query(LuasSnapshot).count())"

# Reset database
rm luas_tracker.db
python -c "from database import init_db; init_db()"

# Test API endpoint
curl http://localhost:8000/arrivals/cab

# Check scheduler status
curl http://localhost:8000/debug/data-collection
```

## Quick Reference: File Purposes

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app initialization, CORS, scheduler lifecycle |
| `database.py` | SQLAlchemy models and database connection setup |
| `routes.py` | All HTTP endpoints (arrivals, accuracy, debug) |
| `luas_client.py` | External API integration and XML parsing |
| `scheduler.py` | Background jobs (polling and accuracy calculation) |
| `test_luas_tracker.py` | Test suite covering all major functionality |

## Learning Notes

This is a learning project demonstrating:

- **Real-time data pipelines**: Scheduled polling, transformation, storage
- **Time-series analytics**: Tracking how forecasts evolve over time
- **API design**: RESTful endpoints with proper error handling
- **Background jobs**: APScheduler integration with FastAPI
- **Database modeling**: Proper schema design for time-series data
- **Testing**: pytest with async support and mocking
- **Production patterns**: Logging, error handling, graceful degradation

The codebase prioritizes clarity and learning over optimization. It's designed to be readable and educational.
