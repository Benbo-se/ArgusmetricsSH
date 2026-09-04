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
$COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F= -c "
SELECT relname, n_live_tup
  FROM pg_stat_user_tables
 ORDER BY relname"' > "$MANIFEST"
{
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
