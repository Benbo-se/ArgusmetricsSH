"""The goals page counts over the period and the filters in its address.

It read neither. Whatever the address said, the cards showed thirty days of
the whole site, so "?range=7d&utm_campaign=spring" answered with every
conversion there was while the analytics page, given the same address,
answered with the campaign's. Two pages, one question, two numbers, and
nothing on the second page said it had not listened.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.filters import FilterSet
from app.services.site_activity import goal_activity
from app.utils.date_helpers import resolve_range


def _seed(db, website_id):
    """Four visitors this week, one of them from the campaign. The campaign's
    visitor orders once, two others order three times between them, and one
    order is from three weeks ago."""
    now = datetime.now(timezone.utc)
    goal_id = db.execute(
        text("INSERT INTO goals (website_id, name, event_name, created_at) "
             "VALUES (:w, 'Order', 'order', now()) RETURNING id"),
        {"w": website_id},
    ).scalar()
    for visitor, campaign in (("ad", "spring"), ("b", None), ("c", None), ("d", None)):
        db.execute(
            text('INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", utm_campaign) '
                 "VALUES (:w, '/', :h, :t, :c)"),
            {"w": website_id, "h": visitor, "t": now - timedelta(days=2), "c": campaign},
        )
    db.execute(
        text('INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", utm_campaign) '
             "VALUES (:w, '/', 'old', :t, 'spring')"),
        {"w": website_id, "t": now - timedelta(days=21)},
    )
    for visitor, days in (("ad", 2), ("b", 2), ("b", 1), ("c", 1), ("old", 21)):
        db.execute(
            text('INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, "timestamp") '
                 "VALUES (:g, :w, :h, :t)"),
            {"g": goal_id, "w": website_id, "h": visitor, "t": now - timedelta(days=days, minutes=-5)},
        )
    db.commit()
    return goal_id


def _cards(response):
    island = re.search(r'id="goals-data">(.*?)</script>', response.text, re.S).group(1)
    return {goal["event_name"]: goal for goal in json.loads(island)}


def test_the_numbers_and_the_line_are_the_filtered_visitors(db, website):
    goal_id = _seed(db, website["id"])
    week = resolve_range("7d", "UTC")

    everybody = goal_activity(db, website["id"], window=week)
    campaign = goal_activity(db, website["id"], window=week,
                             filters=FilterSet.of(utm_campaign="spring"))

    assert everybody["visitors"] == 4 and everybody["goals"][goal_id]["conversions"] == 4
    assert campaign["visitors"] == 1
    assert campaign["goals"][goal_id]["conversions"] == 1
    assert campaign["goals"][goal_id]["rate"] == 100.0
    # The line is drawn from its own query. The campaign's one conversion
    # lifts it on one day; everybody's four lift it on two.
    def lifted(activity):
        points = activity["goals"][goal_id]["spark"]["line"].split()
        floor = max(float(point.split(",")[1]) for point in points)
        return sum(1 for point in points if float(point.split(",")[1]) < floor)

    assert lifted(everybody) == 2
    assert lifted(campaign) == 1, "the line is not of the same visitors as the number"


def test_the_period_in_the_address_is_the_period_counted(owner_client, db, website):
    _seed(db, website["id"])
    page = f"/dashboard/website/{website['id']}/goals"

    assert _cards(owner_client.get(page + "?range=7d"))["order"]["conversions"] == 4
    assert _cards(owner_client.get(page + "?range=30d"))["order"]["conversions"] == 5
    assert _cards(owner_client.get(page))["order"]["conversions"] == 5, "the bare address is thirty days, as before"
    assert _cards(owner_client.get(page + "?range=nonsense"))["order"]["conversions"] == 5


def test_a_filter_in_the_address_is_applied_and_shown(owner_client, db, website):
    _seed(db, website["id"])
    page = f"/dashboard/website/{website['id']}/goals"

    response = owner_client.get(page + "?range=7d&utm_campaign=spring")

    assert response.status_code == 200, response.text[:300]
    card = _cards(response)["order"]
    assert card["conversions"] == 1 and card["rate"] == 100.0
    basis = re.sub(r"\s+", " ", re.search(r"data-goal-basis>(.*?)</p>", response.text, re.S).group(1))
    assert "last 7 days, out of 1 matching visitor" in basis
    assert 'data-dimension-chip="utm_campaign"' in response.text, "a filter is applied and nothing says so"
    # Removing the only filter leaves the period.
    assert 'href="?range=7d" class="chip-remove"' in response.text
    # Every other period keeps the filter.
    assert 'href="?range=30d&amp;utm_campaign=spring"' in response.text


def test_arriving_conversions_are_only_added_to_cards_that_count_everybody_until_now(owner_client, db, website):
    _seed(db, website["id"])
    page = f"/dashboard/website/{website['id']}/goals"

    assert 'x-data="liveConversions"' in owner_client.get(page + "?range=7d").text
    assert 'x-data="liveConversions"' not in owner_client.get(page + "?range=7d&utm_campaign=spring").text
    assert 'x-data="liveConversions"' not in owner_client.get(page + "?range=yesterday").text


def test_the_analytics_page_hands_its_period_and_filters_to_the_goals_page(owner_client, db, website):
    _seed(db, website["id"])

    overview = owner_client.get(f"/dashboard/website/{website['id']}?range=7d&utm_campaign=spring")

    assert f'/dashboard/website/{website["id"]}/goals?range=7d&utm_campaign=spring"' in overview.text
