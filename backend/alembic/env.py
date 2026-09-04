"""
Alembic environment configuration for Argusmetrics database migrations.

This module configures Alembic to work with SQLAlchemy models and handles
both offline and online migration modes.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import the database Base and settings
from app.database import Base
from app.config import settings

# Import ALL models (via the package, which registers every model module)
# so they're registered with Base.metadata. This is critical: autogenerate
# diffs target_metadata against the DB, and any model missing here would be
# emitted as a drop_table for its live table.
import app.models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with the actual DATABASE_URL from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


# TimescaleDB creates and owns objects that the models know nothing about, and
# autogenerate would otherwise propose dropping them on every run.
#
# The clearest case: create_hypertable() adds a descending index on the
# partitioning column, named <table>_timestamp_idx. It belongs to the
# extension, dropping it would hurt exactly the queries the hypertable exists
# to speed up, and declaring it in the models would be describing something we
# do not manage. Chunks live in the extension's own schemas for the same
# reason.
#
# Without this, `alembic check` fails on a database that has been migrated
# correctly, which is a check that cries wolf and therefore stops being read.
TIMESCALE_SCHEMAS = (
    "_timescaledb_internal",
    "_timescaledb_catalog",
    "_timescaledb_config",
    "_timescaledb_cache",
    "timescaledb_information",
    "timescaledb_experimental",
)

#: The four tables turned into hypertables, and the index each conversion adds.
HYPERTABLE_INDEXES = {
    "pageviews_timestamp_idx",
    "custom_events_timestamp_idx",
    "goal_conversions_timestamp_idx",
    "funnel_events_timestamp_idx",
}


def include_object(object_, name, type_, reflected, compare_to):
    """Whether autogenerate should consider a database object.

    Only ever excludes things the extension owns. Anything this project
    created still shows up, so a genuinely forgotten migration still fails.
    """
    schema = getattr(object_, "schema", None)
    if schema in TIMESCALE_SCHEMAS:
        return False

    if type_ == "index" and name in HYPERTABLE_INDEXES:
        return False

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
