#!/usr/bin/env bash
#
# Restore a backup into a scratch database and check what came back.
#
# This is the half that was missing. Dumps were being taken before every
# deployment and nothing had ever restored one, so nobody knew whether they
# worked. A backup that has never been restored is a file, not a backup, and
# the ways dumps fail are quiet: a role that does not exist on the target, a
# missing extension, a write truncated when the disk filled.
#
# It restores into a throwaway database and drops it afterwards. It never
# touches the real one.
#
# Usage:
#
#     scripts/verify-backup.sh ~/backups/argusmetrics/daily/argusmetrics-....sql.gz
#
# With no argument it takes the newest archive it can find.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f docker/docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/argusmetrics/daily}"
SCRATCH_DB="${SCRATCH_DB:-argusmetrics_restore_check}"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    ARCHIVE=$(find "$BACKUP_DIR" -name 'argusmetrics-*.sql.gz' -printf '%T@ %p\n' 2>/dev/null \
              | sort -rn | head -1 | cut -d' ' -f2-)
fi

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "No archive to verify. Looked in $BACKUP_DIR" >&2
    exit 1
fi

echo "==> Verifying $ARCHIVE"

cleanup() {
    $COMPOSE exec -T postgres sh -c \
        "psql -U \"\$POSTGRES_USER\" -d postgres -c 'DROP DATABASE IF EXISTS $SCRATCH_DB'" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Creating $SCRATCH_DB"
cleanup
$COMPOSE exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d postgres -c 'CREATE DATABASE $SCRATCH_DB'" >/dev/null

echo "==> Restoring"
# TimescaleDB needs bracketing, and without it the restore fails in the worst
# way available: the schema is created, then the data load aborts on a
# conflict in Timescale's own catalog, leaving a database that has every table
# and no rows. Measured on a real dump before this was added:
#
#     users 677 -> 0, websites 510 -> 0, pageviews 2871 -> 0
#
# It looks like it worked unless you count something.
$COMPOSE exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -q -c \
     'CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();'" >/dev/null

gunzip -c "$ARCHIVE" | $COMPOSE exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -v ON_ERROR_STOP=1 -q" >/dev/null

$COMPOSE exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -q -c 'SELECT timescaledb_post_restore();'" >/dev/null

echo "==> Checking what came back"

# The tables that matter. An empty restore that reports success is the exact
# failure this script exists to catch, so absence is checked before contents.
REQUIRED="users websites pageviews custom_events ecommerce_events alembic_version"
for table in $REQUIRED; do
    if ! $COMPOSE exec -T postgres sh -c \
        "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -tAc \"SELECT to_regclass('public.$table') IS NOT NULL\"" \
        | grep -q t; then
        echo "FAILED: $table is not in the restored database" >&2
        exit 1
    fi
done

RESTORED_REVISION=$($COMPOSE exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -tAc 'SELECT version_num FROM alembic_version'")
LIVE_REVISION=$($COMPOSE exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"')

echo "    schema revision: $RESTORED_REVISION (live: $LIVE_REVISION)"
if [ "$RESTORED_REVISION" != "$LIVE_REVISION" ]; then
    echo "    note: the backup predates the current migrations, which is normal"
    echo "          for an older archive and worth knowing before relying on it"
fi

echo
echo "    table                 restored"
for table in users websites pageviews custom_events ecommerce_events; do
    COUNT=$($COMPOSE exec -T postgres sh -c \
        "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -tAc 'SELECT count(*) FROM $table'")
    printf "    %-20s %s\n" "$table" "$COUNT"
done

MANIFEST="${ARCHIVE%.sql.gz}.manifest"
if [ -f "$MANIFEST" ]; then
    echo
    echo "==> Comparing against the manifest taken with the dump"

    # A manifest that exists but holds nothing passes -f and then compares
    # nothing, which reads as success. That is how a broken backup.sh stayed
    # invisible: it errored out on the row-count query and left a zero-byte
    # file, and this block dutifully found no problems in it. An empty
    # manifest means the dump did not finish, so treat it as a failure.
    if [ ! -s "$MANIFEST" ]; then
        echo "FAILED: $MANIFEST is empty, so there is nothing to check the" >&2
        echo "        restore against. The dump that produced it did not run" >&2
        echo "        to completion; take a fresh backup before trusting this." >&2
        exit 1
    fi

    # The manifest is read on fd 3, not stdin. `docker compose exec -T` still
    # reads stdin even with the TTY off, so with the loop fed on stdin the
    # first psql call swallowed the rest of the file and the loop ran exactly
    # once. Every table after the first went unchecked, silently.
    COMPARED=0
    while IFS='=' read -r table expected <&3; do
        case "$table" in ''|archive|bytes|sha256|taken_at) continue ;; esac
        ACTUAL=$($COMPOSE exec -T postgres sh -c \
            "psql -U \"\$POSTGRES_USER\" -d $SCRATCH_DB -tAc \"SELECT count(*) FROM $table\"" \
            </dev/null 2>/dev/null || echo "missing")
        COMPARED=$((COMPARED + 1))
        # n_live_tup is an estimate, so this reports rather than fails. A
        # table that was populated and restored empty is the signal worth
        # seeing.
        if [ "$expected" != "0" ] && [ "$ACTUAL" = "0" ]; then
            echo "    FAILED: $table had roughly $expected rows and restored empty" >&2
            exit 1
        fi
    done 3< "$MANIFEST"

    # Non-empty but holding only the trailing metadata keys is the same
    # failure wearing a different hat.
    if [ "$COMPARED" -eq 0 ]; then
        echo "FAILED: $MANIFEST lists no tables, only metadata. The row-count" >&2
        echo "        query in backup.sh did not produce output." >&2
        exit 1
    fi

    echo "    no table that had rows came back empty ($COMPARED tables compared)"
fi

echo
echo "==> Restore verified. Dropping $SCRATCH_DB."
