#!/usr/bin/env bash
# Install the units in deploy/ as the current user's systemd timers.
#
# The schedule is infrastructure. Until this existed it lived only in one
# machine's systemd, which meant a rebuilt server would have come up with the
# application, the database, nginx and the certificates all restored -- and
# nothing taking backups. Silently, with the first sign being an empty backup
# directory on the day it was needed.
#
#   scripts/install-schedule.sh            install or update
#   scripts/install-schedule.sh --adopt    also disable a pre-existing timer or
#                                          cron line for this project
#
# Idempotent once adopted: run it as often as you like.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
ADOPT=0
[ "${1:-}" = "--adopt" ] && ADOPT=1

command -v systemctl >/dev/null || { echo "no systemctl on this machine" >&2; exit 1; }

# Something else already scheduling this project would run alongside these
# units: two dumps a night rather than one, competing for the same directory.
# Refuse rather than silently double the schedule.
existing_cron=$(crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -F 'backup.sh' || true)
existing_units=$(systemctl --user list-timers --all --no-legend 2>/dev/null \
    | grep -i argus | grep -v 'argusmetrics-backup.timer' || true)

if [ -n "$existing_cron$existing_units" ]; then
    if [ "$ADOPT" != "1" ]; then
        echo "Something already schedules a backup for this project:" >&2
        [ -n "$existing_cron" ]  && printf '  cron: %s\n' "$existing_cron" >&2
        [ -n "$existing_units" ] && printf '  unit: %s\n' "$existing_units" >&2
        echo >&2
        echo "Installing now would run that AND these units. Re-run with --adopt" >&2
        echo "to disable it, or remove it yourself first." >&2
        exit 1
    fi
    if [ -n "$existing_cron" ]; then
        echo "adopting: removing the cron line"
        crontab -l 2>/dev/null | grep -vF 'backup.sh' | crontab -
    fi
    for u in $(printf '%s\n' "$existing_units" | awk '{print $NF}'); do
        echo "adopting: disabling $u"
        systemctl --user disable --now "$u" || true
    done
fi

mkdir -p "$UNIT_DIR"
for f in argusmetrics-backup.service argusmetrics-backup.timer; do
    sed "s#%h/argusmetrics#$PROJECT_DIR#g" "$PROJECT_DIR/deploy/$f" > "$UNIT_DIR/$f"
    echo "wrote $UNIT_DIR/$f"
done

systemctl --user daemon-reload
systemctl --user enable --now argusmetrics-backup.timer

# A user timer does not run while nobody is logged in unless lingering is on.
# This is the step that makes the difference between a schedule and a schedule
# that only runs when someone happens to have an ssh session open.
if ! loginctl show-user "$USER" 2>/dev/null | grep -q '^Linger=yes'; then
    echo
    echo "WARNING: lingering is off for $USER, so this timer will not run"
    echo "         while nobody is logged in. Enable it with:"
    echo
    echo "           sudo loginctl enable-linger $USER"
    echo
fi

systemctl --user list-timers argusmetrics-backup.timer --no-pager
