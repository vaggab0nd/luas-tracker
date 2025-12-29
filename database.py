from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Use SQLite for local development (no external dependencies)
# For production, change to: postgresql+psycopg://user:password@localhost/luas_tracker
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./luas_tracker.db")

if "sqlite" in DATABASE_URL:
    # SQLite needs check_same_thread=False for background threads
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class LuasSnapshot(Base):
    """
    Raw snapshot of Luas forecast data at a point in time.
    Stores each poll of the API to track how forecasts change and compare to actuals.
    """
    __tablename__ = "luas_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    stop_code = Column(String, index=True)  # "cab" for Cabra
    tram_id = Column(String, nullable=True)  # Unique tram identifier if available
    direction = Column(String)  # "Inbound" or "Outbound"
    destination = Column(String)  # Final destination
    forecast_arrival_minutes = Column(Integer)  # Minutes until arrival
    forecast_arrival_time = Column(DateTime)  # Calculated arrival time
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)  # When we fetched this data

    def __repr__(self):
        return f"<LuasSnapshot stop={self.stop_code} destination={self.destination} in {self.forecast_arrival_minutes}m>"


class LuasAccuracy(Base):
    """
    Calculated accuracy metrics.
    Compares past forecasts to actual arrivals to measure forecast quality.
    """
    __tablename__ = "luas_accuracy"

    id = Column(Integer, primary_key=True, index=True)
    stop_code = Column(String, index=True)
    tram_id = Column(String, nullable=True)
    direction = Column(String)
    destination = Column(String)
    forecasted_minutes = Column(Integer)  # Original forecast
    actual_minutes = Column(Integer)  # Actual arrival time
    accuracy_delta = Column(Integer)  # Difference (negative = early, positive = late)
    calculated_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        status = "early" if self.accuracy_delta < 0 else "late" if self.accuracy_delta > 0 else "on time"
        return f"<Accuracy {self.destination} was {abs(self.accuracy_delta)}m {status}>"


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
