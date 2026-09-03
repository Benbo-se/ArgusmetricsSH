"""
Database configuration and session management using SQLAlchemy.
Handles connection pooling, session lifecycle, and database dependencies.
"""
import logging
from typing import Generator, Optional
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


# --- Row-level security context ------------------------------------------
#
# Every request declares who it is acting as, so database policies can enforce
# tenant isolation instead of trusting each query to remember its WHERE clause.
#
# Nothing reads these yet: the policies come later, one table at a time. This
# is the plumbing, landed first so it can be verified while it is still inert.
#
# Contexts:
#   user     an authenticated request, carries the user's email
#   tracking the public /track endpoints; may INSERT events, never SELECT
#   public   an anonymous public dashboard, carries the one website id
#   job      the scheduler and cleanup tasks, which have no user
#
# The value is applied per transaction, never per connection. With a pooled
# connection a plain SET would outlive the request and leak one tenant's
# identity into whoever borrows the connection next, which would be worse than
# having no policies at all.

RLS_INFO_KEY = "rls_context"


def set_rls_context(
    db: Session,
    context: str,
    user_email: Optional[str] = None,
    website_id: Optional[int] = None,
) -> None:
    """Declare what this session is acting as, for row-level security.

    Applies to the current transaction and to any later one on the same
    session, so a mid-request commit does not silently drop the context.
    """
    db.info[RLS_INFO_KEY] = {
        "context": context,
        "user_email": user_email or "",
        "website_id": str(website_id) if website_id is not None else "",
    }
    # Getting the connection begins a transaction if none is open, which fires
    # after_begin and applies the values. If one is already open that event has
    # been and gone, so apply directly as well. Doing both is harmless.
    _apply_rls_context(db.connection(), db.info[RLS_INFO_KEY])
    # Useful when a policy starts returning nothing: the first question is
    # always whether the context was set at all, and for whom.
    logger.debug(
        f"RLS context set: context={context} "
        f"website_id={website_id if website_id is not None else '-'}"
    )


def _apply_rls_context(connection, values: dict) -> None:
    """Push the declared context into the current transaction.

    Writes through the Connection rather than the Session on purpose: a
    Session.execute here would begin a transaction, fire after_begin, and call
    straight back into this function.
    """
    # set_config(..., is_local=true) is SET LOCAL, but unlike SET LOCAL it takes
    # bind parameters, so the value is never spliced into SQL text.
    connection.execute(
        text(
            "SELECT set_config('app.context', :context, true),"
            "       set_config('app.user_email', :user_email, true),"
            "       set_config('app.website_id', :website_id, true)"
        ),
        values,
    )


@event.listens_for(SessionLocal, "after_begin")
def _reapply_rls_context(session, transaction, connection):
    """Re-apply the context whenever a new transaction starts.

    Without this, code that commits mid-request and then keeps querying would
    continue on a transaction with no context, and once policies exist those
    queries would quietly return nothing.
    """
    values = session.info.get(RLS_INFO_KEY)
    if values:
        _apply_rls_context(connection, values)


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
    """Reset session state before the connection goes back to the pool.

    The RLS context is set per transaction and so clears itself on commit or
    rollback. This is the second layer: if any code path ever sets a session
    variable without LOCAL, or a transaction ends in an unexpected way, the
    value must not survive to the next request that borrows this connection.
    A leaked tenant identity would be worse than having no policies at all,
    so this does not rely on the first layer being perfect.
    """
    try:
        with dbapi_conn.cursor() as cur:
            cur.execute("RESET ALL")
    except Exception as e:  # never let cleanup break connection return
        logger.warning(f"Could not reset session state on checkin: {e}")
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
