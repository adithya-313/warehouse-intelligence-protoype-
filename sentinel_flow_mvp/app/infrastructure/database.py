"""Database connection and session management.

Provides dependency injection functions for FastAPI endpoints to access the database securely.
"""

import logging
import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/sentinel_db",
)

try:
    engine: Engine = create_engine(
        DATABASE_URI,
        pool_size=50,
        max_overflow=50,
        pool_timeout=30,
        echo=False,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as exception:
    logger.critical(f"Failed to initialize database engine: {str(exception)}")
    raise


def get_database_session() -> Generator[Session, None, None]:
    """Dependency generator that yields a database session.

    Ensures the session is properly closed after the HTTP request finishes.

    Yields:
        Session: An active SQLAlchemy database session.
    """
    database_session = SessionLocal()
    try:
        yield database_session
    except SQLAlchemyError as database_error:
        database_session.rollback()
        logger.error(f"Database transaction failed: {str(database_error)}")
        raise
    finally:
        database_session.close()