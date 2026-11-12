"""How each website, and each goal, has been doing lately.

recent_activity is for the cards on the websites list, goal_activity for the
cards on the goals page.

The list showed a name, a tracking code and a badge reading "Active" on every
site whatever was happening on it. This is what a card now says instead: how
many people came in the last seven days, against the seven before, a line for
the last fourteen, who is on the site right now, and when anyone last was.

One query for every site on the page, not one per card: someone with twelve
sites would otherwise wait for twelve.

Visitors per day are distinct visitor hashes per day. The hash is rebuilt
daily, so a week's visitors are the sum of its days, which is also what the
dashboard's own seven-day number counts.

A day is a day in each website's own time zone, so "today" on one card may
have started hours before "today" on the next.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

from sqlalchemy import text

from app.services.goals_service import goal_conversion_stats
from app.utils.date_helpers import DEFAULT_TIMEZONE, day_start, local_date

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


def recent_activity(
    db,
    website_ids: Iterable[int],
    now: Optional[datetime] = None,
    zones: Optional[Dict[int, str]] = None,
) -> Dict[int, dict]:
    """`zones` maps a website id to its time zone; a site not in it is UTC."""
    ids = list(website_ids)
    if not ids:
        return {}
    now = now or datetime.now(timezone.utc)
    zones = zones or {}
    tzs = [zones.get(i) or DEFAULT_TIMEZONE for i in ids]
    # Each site's fourteen days end on its own today and start at its own
    # midnight thirteen days earlier.
    firsts = [local_date(now, tz) - timedelta(days=DAYS - 1) for tz in tzs]
    sinces = [day_start(first, tz) for first, tz in zip(firsts, tzs)]
    first_of = dict(zip(ids, firsts))

    # Still one query for every site. The zone and the start travel with the
    # id, and the earliest start is repeated as a plain bound so the planner
    # can leave old chunks alone before it looks at any site.
    per_day = db.execute(
        text(
            """
            SELECT p.website_id, date(timezone(w.tz, p."timestamp")) AS day,
                   count(DISTINCT p.visitor_hash) AS visitors
            FROM unnest(CAST(:ids AS integer[]), CAST(:tzs AS text[]),
                        CAST(:sinces AS timestamptz[])) AS w(id, tz, since)
            JOIN pageviews p ON p.website_id = w.id AND p."timestamp" >= w.since
            WHERE p."timestamp" >= :earliest
            GROUP BY p.website_id, date(timezone(w.tz, p."timestamp"))
            """
        ),
        {"ids": ids, "tzs": tzs, "sinces": sinces, "earliest": min(sinces)},
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
        offset = (r.day - first_of[r.website_id]).days
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


GOAL_DAYS = 30


def goal_activity(
    db, website_id: int, now: Optional[datetime] = None, tz: str = DEFAULT_TIMEZONE
) -> dict:
    """Per goal, the last thirty days: conversions, converters, a line.

    Days in `tz`, the website's time zone.

    `rate` is the share of the period's visitors who converted at least once,
    which cannot pass 100%. The overview's table uses the same function
    (goals_service.goal_conversion_stats), over the range chosen there.
    """
    now = now or datetime.now(timezone.utc)
    first = local_date(now, tz) - timedelta(days=GOAL_DAYS - 1)
    since = day_start(first, tz)

    shared = goal_conversion_stats(db, website_id, since)
    visitors = shared["visitors"]

    rows = db.execute(
        text(
            """
            SELECT goal_id, date(timezone(:tz, "timestamp")) AS day,
                   count(*) AS conversions
            FROM goal_conversions
            WHERE website_id = :w AND "timestamp" >= :since
            GROUP BY 1, 2
            """
        ),
        {"w": website_id, "since": since, "tz": tz},
    ).all()
    days = {}
    for r in rows:
        offset = (r.day - first).days
        if 0 <= offset < GOAL_DAYS:
            days.setdefault(r.goal_id, [0] * GOAL_DAYS)[offset] = r.conversions

    out = {}
    for goal_id, series in days.items():
        out[goal_id] = {
            "conversions": sum(series),
            "rate": shared["goals"][goal_id]["rate"] if visitors else None,
            "spark": _spark(series),
        }
    return {"visitors": visitors, "goals": out}
