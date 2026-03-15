"""
src/db/connection.py
Database connection and session management.
All other modules import get_session() from here — single source of truth.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://otto:otto@localhost:5432/otto")

# create_engine sets up the connection pool.
# pool_pre_ping=True checks the connection is alive before using it —
# prevents stale connection errors after the DB restarts.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


def get_session():
    """Yield a database session and close it when done."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
