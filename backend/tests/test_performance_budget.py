"""A budget on how many queries each page is allowed to issue.

Wall-clock budgets look like the obvious thing to measure and are the wrong
thing to assert on: a shared CI runner varies by a factor of several, so the
test either fails at random or is set so loose it catches nothing.

What actually makes an analytics dashboard slow as data grows is the number of
statements, not the milliseconds. A page that issues twelve queries stays fast
forever. A page that issues one per website, or one per row, is fine with
three websites and unusable with three hundred, and nobody notices the day it
changes because the page is still fast on a development database.

That is deterministic, so it can be a budget.

The numbers below are the counts as measured, rounded up with a little room.
They are not aspirations. When one is exceeded the question is what started
looping, and the fix is usually a join.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text


class QueryCounter:
    """Counts statements on one connection for the duration of a block."""

    def __init__(self, connection):
        self._connection = connection
        self.statements = []

    def __enter__(self):
        event.listen(self._connection, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self._connection, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        # The row-level security context is re-applied on every transaction,
        # which is correct and would otherwise dominate the count.
        if "set_config" in statement:
            return
        self.statements.append(statement)

    def __len__(self):
        return len(self.statements)

    def summary(self, limit=6):
        """The statements, shortened, so a failure says what started looping."""
        seen = {}
        for s in self.statements:
            key = " ".join(s.split())[:90]
            seen[key] = seen.get(key, 0) + 1
        worst = sorted(seen.items(), key=lambda kv: -kv[1])[:limit]
        return "\n  ".join(f"{n:>3}x  {s}" for s, n in worst)


@pytest.fixture
def busy_website(db, website):
    """A website with enough traffic and configuration to exercise the joins.

    Small enough to stay fast, varied enough that anything looping per row or
    per website shows up in the count.
    """
    now = datetime.now(timezone.utc)
    for i in range(120):
        db.execute(
            text(
                "INSERT INTO pageviews "
                "  (website_id, path, visitor_hash, timestamp, browser, device_type, country) "
                "VALUES (:w, :p, :h, :t, :b, :d, :c)"
            ),
            {
                "w": website["id"],
                "p": f"/page-{i % 20}",
                "h": uuid.uuid4().hex[:16],
                "t": now - timedelta(hours=i),
                "b": ["Chrome", "Firefox", "Safari"][i % 3],
                "d": ["desktop", "mobile", "tablet"][i % 3],
                "c": ["SE", "NO", "DK"][i % 3],
            },
        )
    for i in range(5):
        db.execute(
            text(
                "INSERT INTO goals (website_id, name, event_name, created_at) "
                "VALUES (:w, :n, :e, now())"
            ),
            {"w": website["id"], "n": f"Goal {i}", "e": f"event_{i}"},
        )
    db.commit()
    return website


# Measured on this fixture, then given modest headroom. A budget of 25 on a
# page that issues 2 queries catches nothing, which is what these were before
# I measured instead of guessing.
#
#   page        measured   budget
#   /              28        35
#   /goals          2         6
#   /funnels        2         6
#   /revenue       11        16
#   /team           1         5
#   /settings       2         6
#
# The sub-pages are cheap because they render a shell and fetch their contents
# from the API afterwards, so their budget guards the shell rather than the
# data. The main dashboard renders server-side and is where the work happens,
# which is where a regression would show.
BUDGETS = [
    ("", 35),
    ("/goals", 6),
    ("/funnels", 6),
    ("/revenue", 16),
    ("/team", 5),
    ("/settings", 6),
]


@pytest.mark.parametrize("page,budget", BUDGETS)
def test_a_dashboard_page_stays_within_its_query_budget(
    owner_client, db, busy_website, page, budget
):
    with QueryCounter(db.connection()) as counter:
        response = owner_client.get(f"/dashboard/website/{busy_website['id']}{page}")

    assert response.status_code == 200
    assert len(counter) <= budget, (
        f"{page or '/'} issued {len(counter)} queries, budget is {budget}.\n  "
        + counter.summary()
    )


def test_the_website_list_does_not_query_per_website(owner_client, db, website):
    """The classic one: a list page that fetches stats for each row.

    Fine with three websites, unusable with three hundred, and the change is
    invisible on a development database.
    """
    for i in range(5):
        db.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES (:n, :d, :e, :tc, :vt, true, true, false, false, false, now())"
            ),
            {
                "n": f"Site {i}",
                "d": f"https://extra-{uuid.uuid4().hex[:8]}.example.com",
                "e": website["email"],
                "tc": uuid.uuid4().hex[:8],
                "vt": uuid.uuid4().hex,
            },
        )
    db.commit()

    with QueryCounter(db.connection()) as counter:
        response = owner_client.get("/dashboard")

    assert response.status_code == 200
    # Three, measured, for six websites: it does not query per row.
    assert len(counter) <= 8, (
        f"the website list issued {len(counter)} queries for six websites, "
        f"which looks like one or more per row.\n  " + counter.summary()
    )


def test_the_tracking_endpoint_stays_cheap(client, db, website):
    """This one runs on every visitor of every customer site.

    It resolves the code, writes a pageview, and checks the funnels. A query
    added here is multiplied by all the traffic the product exists to record.
    """
    with QueryCounter(db.connection()) as counter:
        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/budget"},
        )

    assert response.status_code == 200
    # Five, measured: resolve the tracking code, take the id from the
    # sequence, insert, load the funnels, release the savepoint.
    assert len(counter) <= 8, (
        f"recording one pageview took {len(counter)} queries.\n  " + counter.summary()
    )
