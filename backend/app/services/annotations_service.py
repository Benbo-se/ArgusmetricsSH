"""Notes on the traffic graph: reading them for a range, and the one limit.

Writing is three lines each in the router. What lives here is the part two
callers share (the dashboard page and the CSV export) and the part that has
to agree with the graph: which days a range covers.
"""
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.utils.date_helpers import DateWindow, local_date

#: Notes one website can hold. Far more than a graph can show, and enough to
#: keep a script that loops on the endpoint from filling the table.
MAX_PER_WEBSITE = 500


def window_days(window: DateWindow) -> Tuple[date, date]:
    """The first and last calendar day a range covers, in the website's zone.

    The same two days the time series walks between (see
    _get_timeseries_data), so a note is listed exactly when the graph has a
    point for its day. That holds for a rolling range too, whose first day is
    only partly inside it.
    """
    return local_date(window.start, window.tz), local_date(window.end, window.tz)


def annotations_between(
    db: Session, website_id: int, first_day: Optional[date], last_day: Optional[date]
) -> List[Dict]:
    """A website's notes from first_day to last_day inclusive, oldest first.

    Either bound may be None for no bound. Each is {"id", "day", "note"} with
    the day as 'YYYY-MM-DD', which is the first ten characters of the date on
    every point of the graph, daily or hourly.
    """
    query = db.query(Annotation).filter(Annotation.website_id == website_id)
    if first_day is not None:
        query = query.filter(Annotation.day >= first_day)
    if last_day is not None:
        query = query.filter(Annotation.day <= last_day)
    rows = query.order_by(Annotation.day, Annotation.id).limit(MAX_PER_WEBSITE).all()
    return [{"id": row.id, "day": row.day.isoformat(), "note": row.note} for row in rows]


def annotations_in_window(db: Session, website_id: int, window: DateWindow) -> List[Dict]:
    first_day, last_day = window_days(window)
    return annotations_between(db, website_id, first_day, last_day)


def has_room(db: Session, website_id: int) -> bool:
    """Whether the website may hold one more note."""
    held = db.query(Annotation.id).filter(Annotation.website_id == website_id).count()
    return held < MAX_PER_WEBSITE
