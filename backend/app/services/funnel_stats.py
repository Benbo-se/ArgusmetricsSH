"""How far visitors got through a funnel.

A step counts the visitors who reached it and every step before it. It used
to count everyone who reached the step at all, so a visitor who landed on
/checkout from a search result counted as having been through the product
page and the cart, and a later step could hold more people than the first:
a funnel reading 120% at checkout.

The order the steps were reached in is not checked. Only a visitor's first
arrival at each step is recorded (analytics_recording_service), so someone
who looked at the cart, went back to the product and then checked out has a
cart row older than the product row, and requiring the order would drop a
visitor who did go through every step.
"""
from datetime import datetime, timedelta, timezone

from app.models.funnel import Funnel, FunnelEvent


def funnel_stats(db, funnel: Funnel, days: int = 30, now: datetime = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    steps = sorted(funnel.steps or [], key=lambda s: s.get("step") or 0)

    reached = {}
    rows = db.query(FunnelEvent.visitor_id, FunnelEvent.step_number).filter(
        FunnelEvent.funnel_id == funnel.id,
        FunnelEvent.timestamp >= since,
    ).distinct()
    for visitor, step in rows:
        reached.setdefault(visitor, set()).add(step)

    # Visitors still in after each step: the ones who reached it and every
    # step before it.
    remaining = set(reached)
    counts = []
    for step in steps:
        remaining = {v for v in remaining if step.get("step") in reached[v]}
        counts.append(len(remaining))

    entered = counts[0] if counts else 0
    return {
        "funnel_id": funnel.id,
        "funnel_name": funnel.name,
        "total_visitors": entered,
        "steps": [
            {
                "step": step.get("step"),
                "name": step.get("name"),
                "visitors": n,
                "conversion_rate": round(n / entered * 100, 2) if entered else 0,
            }
            for step, n in zip(steps, counts)
        ],
    }
