"""Funnel steps count the visitors who got there through every earlier step.

A visitor who landed straight on /checkout used to count at checkout, so a
later step could hold more people than the first and a funnel could convert
at more than 100%.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.funnel import Funnel
from app.services.funnel_stats import funnel_stats

NOW = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
STEPS = [
    {"step": 1, "name": "Product", "path": "/product"},
    {"step": 2, "name": "Cart", "path": "/cart"},
    {"step": 3, "name": "Checkout", "path": "/checkout"},
]


def make_funnel(db, website_id):
    funnel = Funnel(website_id=website_id, name="Checkout", steps=STEPS, is_active=True)
    db.add(funnel)
    db.commit()
    return funnel


def reach(db, funnel, visitor, step, ago=timedelta(days=1)):
    db.execute(
        text('INSERT INTO funnel_events (funnel_id, visitor_id, step_number, step_name, path, "timestamp", completed) '
             "VALUES (:f, :v, :s, 'x', '/', :t, false)"),
        {"f": funnel.id, "v": visitor, "s": step, "t": NOW - ago},
    )
    db.commit()


def counts(stats):
    return [s["visitors"] for s in stats["steps"]]


def test_each_step_counts_only_visitors_through_every_earlier_step(db, website):
    f = make_funnel(db, website["id"])
    for v in ("a", "b", "c"):
        reach(db, f, v, 1)
    for v in ("a", "b"):
        reach(db, f, v, 2)
    reach(db, f, "a", 3)
    reach(db, f, "searcher", 3)          # straight to checkout
    reach(db, f, "skipper", 1)
    reach(db, f, "skipper", 3)           # past the cart without it
    stats = funnel_stats(db, f, now=NOW)
    assert counts(stats) == [4, 2, 1]
    assert stats["total_visitors"] == 4
    assert [s["conversion_rate"] for s in stats["steps"]] == [100.0, 50.0, 25.0]


def test_the_period_is_respected(db, website):
    f = make_funnel(db, website["id"])
    reach(db, f, "old", 1, ago=timedelta(days=40))
    reach(db, f, "new", 1)
    assert counts(funnel_stats(db, f, days=30, now=NOW)) == [1, 0, 0]


def test_nobody_yet(db, website):
    f = make_funnel(db, website["id"])
    stats = funnel_stats(db, f, now=NOW)
    assert counts(stats) == [0, 0, 0]
    assert [s["conversion_rate"] for s in stats["steps"]] == [0, 0, 0]
