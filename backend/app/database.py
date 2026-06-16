"""
Database configuration and session management using SQLAlchemy.
Handles connection pooling, session lifecycle, and database dependencies.
"""
import logging
from typing import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine with connection pooling
engine_kwargs = {
    "poolclass": QueuePool if not settings.DEBUG else NullPool,
    "echo": settings.DB_ECHO,  # Log SQL queries when enabled
    "future": True,  # Use SQLAlchemy 2.0 style
}

# Only add pool settings if using QueuePool (not NullPool)
if not settings.DEBUG:
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,  # Verify connections before using
        "pool_recycle": 3600,  # Recycle connections after 1 hour
    })

engine = create_engine(
    settings.sqlalchemy_database_uri,
    **engine_kwargs
)

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # Prevent lazy loading errors after commit
)

# Base class for all database models
Base = declarative_base()


# Event listeners for connection pool monitoring
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Log when a new database connection is established."""
    logger.debug("Database connection established")


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when a connection is checked out from the pool."""
    logger.debug("Database connection checked out from pool")


@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """Log when a connection is returned to the pool."""
    logger.debug("Database connection returned to pool")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Yields a SQLAlchemy session that is automatically closed after use.
    Handles transaction rollback on exceptions.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    Yields:
        Session: SQLAlchemy database session

    Raises:
        SQLAlchemyError: If database operation fails
    """
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected error during database operation: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions outside of FastAPI request context.

    Usage:
        with get_db_context() as db:
            user = db.query(User).first()

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database error in context: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in database context: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize database by creating all tables.

    This should be called during application startup.
    In production, use Alembic migrations instead.
    """
    try:
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def check_db_connection() -> bool:
    """
    Check if database connection is healthy.

    Returns:
        bool: True if connection is healthy, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection is healthy")
        return True
    except SQLAlchemyError as e:
        logger.error(f"Database connection check failed: {e}")
        return False


async def close_db_connection() -> None:
    """
    Close all database connections in the pool.

    Should be called during application shutdown.
    """
    try:
        engine.dispose()
        logger.info("Database connections closed successfully")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")
        raise
