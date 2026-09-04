#!/usr/bin/env bash
#
# Take a backup of the production database.
#
# Runs on the server. The deploy workflow already takes a dump before each
# deployment, which is useful and not a backup strategy: it only happens when
# someone deploys, so three quiet weeks means a three week old copy.
#
# What this adds beyond `pg_dump | gzip`:
#
#   * it verifies the archive is readable before calling it a success, because
#     a truncated write produces a file of exactly the shape you expect and
#     discovering that during a restore is the worst possible time
#   * it records the row counts at the moment of the dump, so a restore can be
#     checked against something rather than eyeballed
#   * it encrypts, if a recipient is configured, because a dump holds every
#     customer's email address and every visitor hash
#   * it rotates, so the disk does not fill and take the database with it
#
# Usage, from the directory holding docker-compose.prod.yml:
#
#     BACKUP_DIR=~/backups/argusmetrics scripts/backup.sh
#
# Set BACKUP_GPG_RECIPIENT to encrypt. Without it the script warns and
# continues, since an unencrypted backup beats no backup, but it should be set
# in production.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/argusmetrics/daily}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
COMPOSE="${COMPOSE:-docker compose -f docker/docker-compose.prod.yml}"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
ARCHIVE="$BACKUP_DIR/argusmetrics-$STAMP.sql.gz"
TABLE_LIST="$(mktemp)"
trap 'rm -f "$TABLE_LIST"' EXIT
MANIFEST="$BACKUP_DIR/argusmetrics-$STAMP.manifest"

mkdir -p "$BACKUP_DIR"

echo "==> Dumping to $ARCHIVE"
# --clean --if-exists so the dump can be restored over an existing database
# without hand-editing it first. Under pressure is not when to discover that.
$COMPOSE exec -T postgres sh -c \
  'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip -9 > "$ARCHIVE"

echo "==> Verifying the archive is readable"
# A dump that cannot be decompressed is not a backup, and this is the cheapest
# moment to find out.
if ! gzip -t "$ARCHIVE"; then
    echo "FAILED: $ARCHIVE is corrupt; removing it rather than leaving a file
that looks like a backup" >&2
    rm -f "$ARCHIVE"
    exit 1
fi

SIZE=$(stat -c %s "$ARCHIVE")
if [ "$SIZE" -lt 10000 ]; then
    echo "FAILED: $ARCHIVE is only $SIZE bytes, which is not a real database" >&2
    rm -f "$ARCHIVE"
    exit 1
fi

echo "==> Recording row counts, so a restore can be checked against them"
# -F sets the field separator, so the SQL never has to quote a separator at all.
# The previous version built the line by concatenating a double-quoted equals
# sign in SQL, where double quotes mean an identifier rather than a string:
# psql looked for a column by that name, errored out, and left a zero-byte
# manifest behind. Since the manifest is the only thing verify-backup.sh has to
# compare a restore against, that quietly disarmed the row-count check.
#
# Exact counts, and only tables in the public schema. The previous version read
# n_live_tup from pg_stat_user_tables, which was wrong twice over once the
# traffic tables became hypertables:
#
#   * a hypertable's rows live in its chunks, so the parent reports zero. On a
#     database holding 3569 pageviews the manifest recorded pageviews=0, and a
#     restore that came back empty compared 0 against 0 and passed. Those are
#     exactly the tables a broken TimescaleDB restore empties, so the check was
#     blind to the only failure it exists to catch.
#   * pg_stat_user_tables also lists every chunk, so the manifest filled with
#     _hyper_2_7_chunk lines that verify-backup.sh could not resolve and
#     counted as compared anyway.
#
# Counted one table at a time rather than in a single clever statement. The
# clever version needed a string literal nested inside psql -c inside sh -c,
# and got a zero-length identifier instead. A loop is slower and readable.
#
# Each psql gets its own /dev/null on stdin, and the table list is read on
# fd 3, for the reason verify-backup.sh documents: `docker compose exec -T`
# reads stdin even with the TTY off, and a loop fed on stdin runs once.
: > "$MANIFEST"
$COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "
SELECT table_name FROM information_schema.tables
 WHERE table_schema = '"'"'public'"'"' AND table_type = '"'"'BASE TABLE'"'"'
 ORDER BY table_name"' </dev/null | tr -d '\r' > "$TABLE_LIST"

while read -r table <&3; do
    [ -n "$table" ] || continue
    COUNT=$($COMPOSE exec -T postgres sh -c \
        "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"SELECT count(*) FROM $table\"" \
        </dev/null | tr -d '\r')
    echo "$table=$COUNT" >> "$MANIFEST"
done 3< "$TABLE_LIST"

# Two counts that are not tables and that a restore can lose silently. The
# chunks are where every traffic row actually lives, and the policies are the
# isolation between customers: a restore that brings back rows without them is
# a database anyone can read across.
CHUNKS=$($COMPOSE exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM timescaledb_information.chunks"' \
    </dev/null | tr -d '\r')
POLICIES=$($COMPOSE exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM pg_policies"' \
    </dev/null | tr -d '\r')

{
    echo "chunks=$CHUNKS"
    echo "policies=$POLICIES"
    echo "archive=$(basename "$ARCHIVE")"
    echo "bytes=$SIZE"
    echo "sha256=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
    echo "taken_at=$STAMP"
} >> "$MANIFEST"

if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
    echo "==> Encrypting for $BACKUP_GPG_RECIPIENT"
    gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" "$ARCHIVE"
    rm -f "$ARCHIVE"
    ARCHIVE="$ARCHIVE.gpg"
else
    echo "WARNING: BACKUP_GPG_RECIPIENT is not set, so this dump is unencrypted."
    echo "         It contains every customer's email address and every visitor"
    echo "         hash. Set it in production."
fi

echo "==> Rotating anything older than $KEEP_DAYS days"
find "$BACKUP_DIR" -name 'argusmetrics-*' -mtime "+$KEEP_DAYS" -print -delete

echo "==> Done: $(basename "$ARCHIVE") ($(numfmt --to=iec "$SIZE" 2>/dev/null || echo "$SIZE bytes"))"
echo
echo "This backup is on the same machine as the database it protects, which"
echo "covers a bad migration and not a disk failure. Copy it somewhere else."
