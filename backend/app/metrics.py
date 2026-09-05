"""Numbers a monitoring system can scrape, in Prometheus exposition format.

/health already answers "is this instance alive", which is what an uptime
check needs. It does not answer "is it doing less work than yesterday", and
that is the failure that goes unnoticed: tracking quietly stops for one site
because a DNS record changed, or the retention job falls behind, and nothing
is down.

Hand-written rather than pulling in prometheus_client. The exposition format
is a handful of lines of text, this exports nine metrics, and a dependency is
a thing to keep patched forever.

Everything here is counted from the database rather than kept in memory,
because the app may run as several workers and an in-memory counter would then
report one worker's share and look like a drop in traffic.
"""
import logging
from typing import Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _line(name: str, value, help_text: str, kind: str = "gauge", labels: str = "") -> List[str]:
    """One metric, with the HELP and TYPE lines a scraper expects."""
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {kind}",
        f"{name}{labels} {value}",
    ]


def _scalar(db: Session, sql: str, default=0):
    """Query one number, and never let monitoring take the app down.

    A metrics endpoint that raises turns a question about the system into an
    outage of its own. Anything that fails is simply absent from the output,
    and an absent metric is visible in a dashboard as a gap.
    """
    try:
        value = db.execute(text(sql)).scalar()
        return default if value is None else value
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Metric query failed, omitting it: {e}")
        return None


def render(db: Session, started_at: float) -> str:
    """The whole exposition, as one text body.

    `started_at` is a monotonic reading, not a wall clock: it is what main.py
    already keeps for /health, and subtracting a wall clock from it produces a
    unix timestamp that looks like an uptime of fifty-six years.
    """
    import time

    out: List[str] = []

    out += _line(
        "argus_uptime_seconds",
        int(time.monotonic() - started_at),
        "Seconds since this process started",
        "counter",
    )

    # Ingest. The number worth alerting on is the last hour against the same
    # hour yesterday: a site that stops sending looks like nothing at all in
    # an absolute count.
    # HELP and TYPE go once per metric name, not once per label. Prometheus
    # rejects a body that repeats them, so the two windows share one header.
    windows = []
    for window, label in (("1 hour", "hour"), ("24 hours", "day")):
        value = _scalar(
            db,
            f"SELECT count(*) FROM pageviews "
            f" WHERE \"timestamp\" > now() - INTERVAL '{window}'",
        )
        if value is not None:
            windows.append((label, value))

    if windows:
        out += [
            "# HELP argus_pageviews_recent Pageviews recorded in the recent past",
            "# TYPE argus_pageviews_recent gauge",
        ]
        out += [f'argus_pageviews_recent{{window="{l}"}} {v}' for l, v in windows]

    events = _scalar(
        db,
        "SELECT count(*) FROM custom_events "
        " WHERE \"timestamp\" > now() - INTERVAL '1 hour'",
    )
    if events is not None:
        out += _line(
            "argus_custom_events_recent",
            events,
            "Custom events recorded in the last hour",
        )

    # What the instance is carrying. A sudden change in either is worth
    # looking at even when nothing is broken.
    for name, sql, help_text in (
        ("argus_websites_total", "SELECT count(*) FROM websites WHERE is_active", "Active websites"),
        ("argus_websites_unverified", "SELECT count(*) FROM websites WHERE is_active AND NOT is_verified", "Active websites that record nothing because the domain is unverified"),
        ("argus_accounts_total", "SELECT count(*) FROM users WHERE is_verified", "Verified accounts"),
    ):
        value = _scalar(db, sql)
        if value is not None:
            out += _line(name, value, help_text)

    # Scheduled jobs, per job, as seconds since the last success. This is the
    # one that would have caught a job doing nothing for weeks.
    try:
        rows = db.execute(
            text(
                "SELECT job_name,"
                "       EXTRACT(EPOCH FROM (now() - last_success_at))::bigint,"
                "       consecutive_failures"
                "  FROM job_runs"
            )
        ).all()
        if rows:
            out += ["# HELP argus_job_last_success_seconds Seconds since this job last succeeded",
                    "# TYPE argus_job_last_success_seconds gauge"]
            for name, age, _failures in rows:
                if age is not None:
                    out.append(f'argus_job_last_success_seconds{{job="{name}"}} {age}')
            out += ["# HELP argus_job_consecutive_failures Failures since the last success",
                    "# TYPE argus_job_consecutive_failures gauge"]
            for name, _age, failures in rows:
                out.append(f'argus_job_consecutive_failures{{job="{name}"}} {failures or 0}')
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Job metrics unavailable: {e}")

    # Storage. The disk filling is the failure that takes the database with it,
    # and it is entirely predictable from a trend line.
    size = _scalar(db, "SELECT pg_database_size(current_database())")
    if size is not None:
        out += _line("argus_database_bytes", size, "Size of the database on disk")

    chunks = _scalar(db, "SELECT count(*) FROM timescaledb_information.chunks")
    if chunks is not None:
        out += _line("argus_hypertable_chunks", chunks, "Chunks across all hypertables")

    return "\n".join(out) + "\n"
