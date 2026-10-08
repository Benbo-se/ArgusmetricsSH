"""How each website has been doing lately, for the cards on the websites list.

The list showed a name, a tracking code and a badge reading "Active" on every
site whatever was happening on it. This is what a card now says instead: how
many people came in the last seven days, against the seven before, a line for
the last fourteen, who is on the site right now, and when anyone last was.

One query for every site on the page, not one per card: someone with twelve
sites would otherwise wait for twelve.

Visitors per day are distinct visitor hashes per day. The hash is rebuilt
daily, so a week's visitors are the sum of its days, which is also what the
dashboard's own seven-day number counts.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

from sqlalchemy import text

DAYS = 14
ONLINE_WINDOW = timedelta(minutes=5)

# The sparkline's box, in SVG user units. The template scales it to the card.
SPARK_W, SPARK_H = 140, 36


def _change(now: int, before: int) -> Optional[float]:
    """Percent change, or None when there is nothing to compare with."""
    if not before:
        return None
    return (now - before) / before * 100


def _spark(days) -> Dict[str, str]:
    """Polyline points and a closed area under them, for an inline SVG."""
    top = max(days) or 1
    step = SPARK_W / (len(days) - 1)
    # A pixel of headroom so a flat line at the top is not cut by the edge.
    pts = [(i * step, SPARK_H - 1 - (v / top) * (SPARK_H - 2)) for i, v in enumerate(days)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return {
        "line": line,
        "area": f"M0,{SPARK_H} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{SPARK_W},{SPARK_H} Z",
    }


def ago(now: datetime, then: datetime) -> str:
    """'just now', '12 minutes ago', '3 hours ago', '5 days ago'."""
    seconds = max(0, (now - then).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def recent_activity(db, website_ids: Iterable[int], now: Optional[datetime] = None) -> Dict[int, dict]:
    ids = list(website_ids)
    if not ids:
        return {}
    now = now or datetime.now(timezone.utc)
    today = now.date()
    first = today - timedelta(days=DAYS - 1)

    per_day = db.execute(
        text(
            """
            SELECT website_id, date("timestamp") AS day, count(DISTINCT visitor_hash) AS visitors
            FROM pageviews
            WHERE website_id = ANY(:ids) AND "timestamp" >= :since
            GROUP BY website_id, date("timestamp")
            """
        ),
        {"ids": ids, "since": datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)},
    ).all()

    # Per site rather than one GROUP BY: the latest row of each site is an
    # index lookup, where max() over a grouped hypertable reads all of it.
    latest = db.execute(
        text(
            """
            SELECT w.id AS website_id,
                   (SELECT p."timestamp" FROM pageviews p WHERE p.website_id = w.id
                    ORDER BY p."timestamp" DESC LIMIT 1) AS last_seen,
                   (SELECT count(DISTINCT p.visitor_hash) FROM pageviews p
                    WHERE p.website_id = w.id AND p."timestamp" >= :online_since) AS online
            FROM unnest(CAST(:ids AS integer[])) AS w(id)
            """
        ),
        {"ids": ids, "online_since": now - ONLINE_WINDOW},
    ).all()

    counts = {i: [0] * DAYS for i in ids}
    for r in per_day:
        offset = (r.day - first).days
        if 0 <= offset < DAYS:
            counts[r.website_id][offset] = r.visitors
    seen = {r.website_id: r for r in latest}

    out = {}
    for i in ids:
        days = counts[i]
        week, prev = sum(days[7:]), sum(days[:7])
        r = seen.get(i)
        out[i] = {
            "days": days,
            "week": week,
            "change": _change(week, prev),
            "online": r.online if r else 0,
            "last_seen": ago(now, r.last_seen) if r and r.last_seen else None,
            "spark": _spark(days) if any(days) else None,
        }
    return out
