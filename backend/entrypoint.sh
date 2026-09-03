#!/bin/sh
# Container entrypoint: bring the schema to head, then start the app.
#
# Two cases are handled before `alembic upgrade head`:
#   1. Fresh database          -> upgrade creates the full schema (baseline).
#   2. Pre-Alembic database    -> tables exist (created by the old create_all
#      path) but alembic_version doesn't; re-running create_table would fail,
#      so we adopt the schema by stamping the baseline first.
set -e

python <<'PY'
from sqlalchemy import create_engine, inspect
from app.config import settings
import subprocess

engine = create_engine(settings.DATABASE_URL)
tables = inspect(engine).get_table_names()
engine.dispose()

if "users" in tables and "alembic_version" not in tables:
    print("entrypoint: pre-Alembic schema detected -> alembic stamp head", flush=True)
    subprocess.run(["alembic", "stamp", "head"], check=True)
PY

echo "entrypoint: alembic upgrade head"
alembic upgrade head

exec "$@"
