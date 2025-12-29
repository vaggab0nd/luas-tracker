# Luas Real-Time Tracker

A real-time public transport tracking system for Dublin's Luas tram network. Built to learn full-stack development with real API integration, data pipelines, and time-series analytics.

## Project Overview

This is a learning project that tracks Luas arrivals at the Cabra stop on the Green Line. It demonstrates:

- **API Integration**: Consuming real-time data from Dublin's Luas Automatic Vehicle Location System
- **Data Pipeline**: Scheduled polling, data transformation, and storage
- **Time-Series Analytics**: Tracking forecast accuracy over time
- **Full-Stack Architecture**: Backend API, database, frontend integration

## Tech Stack

- **Backend**: Python with FastAPI
- **Database**: PostgreSQL (for time-series data)
- **Scheduling**: APScheduler for background polling
- **Async**: httpx for non-blocking API calls

## Setup

### Prerequisites

- Python 3.9+
- PostgreSQL (or you can use SQLite for local development)
- pip

### Installation

1. Clone/create the project directory
```bash
cd luas-tracker
```

2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up database
```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your database connection
nano .env
```

5. Initialize the database
```bash
python -c "from database import init_db; init_db()"
```

6. Run the server
```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Get Next Arrivals
```
GET /arrivals/cabra?limit=3
```
Returns the next 3 upcoming trams for Cabra stop.

**Example Response:**
```json
{
  "stop_code": "cab",
  "last_updated": "2024-01-15T14:30:45.123456",
  "next_arrivals": [
    {
      "destination": "The Point",
      "direction": "Inbound",
      "due_minutes": 3,
      "due_time": "2024-01-15T14:33:45.123456"
    },
    {
      "destination": "Tallaght",
      "direction": "Outbound",
      "due_minutes": 7,
      "due_time": "2024-01-15T14:37:45.123456"
    }
  ]
}
```

### Get Forecast Accuracy
```
GET /accuracy/summary?hours=24
```
Get forecast accuracy metrics for the last N hours (default 24).

### Health Check
```
GET /health
```
Simple health check endpoint.

### Stats
```
GET /stats
```
Get general system statistics.

## How It Works

1. **Polling Loop**: Every 30 seconds, the backend calls the Luas API
2. **Data Storage**: Raw forecast snapshots are stored in PostgreSQL
3. **API Serving**: The frontend calls `/arrivals/cabra` to get the latest forecasts
4. **Accuracy Tracking**: As new forecasts come in, we compare them to old ones to measure accuracy

## Database Schema

### luas_snapshots
Stores raw API responses at each poll interval. Useful for:
- Serving current forecasts
- Calculating accuracy over time
- Trending analysis

### luas_accuracy
Stores calculated accuracy metrics. Useful for:
- Understanding forecast quality
- Identifying problem routes/times
- Time-series analysis

## Development Notes

- The Luas API has rate limits and may have IP-based restrictions
- The backend acts as a proxy to work around CORS restrictions on the frontend
- Times are stored as UTC in the database; convert to local timezone in the frontend
- The polling job runs in a background thread managed by APScheduler

## Deployment

### Railway (Recommended)

1. Connect your GitHub repo to Railway
2. Set `DATABASE_URL` environment variable
3. Deploy

### Render

1. Create a new Web Service
2. Point to your repo
3. Set environment variables
4. Deploy

## Next Steps / Future Features

- Accuracy calculation (comparing old forecasts to new ones)
- Frontend dashboard with real-time updates
- WebSocket support for live updates
- Predictive analytics
- Multi-stop support

## Learning Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
- [APScheduler](https://apscheduler.readthedocs.io/)
- [Dublin Open Data - Luas API](https://data.gov.ie)
