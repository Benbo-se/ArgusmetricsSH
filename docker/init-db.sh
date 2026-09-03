#!/bin/bash
# Runs ONCE when the postgres volume is first initialized (docker-entrypoint-initdb.d).
#
# Creates a least-privilege application role. The app connects as `argus_app`
# (DML only, owns nothing); migrations run as the database owner
# ($POSTGRES_USER) via MIGRATION_DATABASE_URL. A logic bug or SQL injection in
# the web process can then read/write rows but never DROP tables, alter
# schema, or reach superuser abilities.
#
# APP_DB_PASSWORD unset => the role is not created and the app runs as the
# owner (the simple self-host mode; dev compose does this).
set -e

if [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "init-db: APP_DB_PASSWORD not set - skipping app-role creation (app will run as the DB owner)"
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE argus_app LOGIN PASSWORD '${APP_DB_PASSWORD}';
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO argus_app;
    GRANT USAGE ON SCHEMA public TO argus_app;

    -- Tables are created later by Alembic as the owner; default privileges
    -- make every future table/sequence usable by the app role automatically.
    ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO argus_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO argus_app;
EOSQL

echo "init-db: created least-privilege role argus_app"
