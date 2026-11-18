"""A row recorded by the tracker gets its owner and is counted, as the role
production runs as.

The owner is filled in by a trigger that looks the website up. Run with the
caller's rights, that lookup found nothing whenever the caller was the
tracking context, which reads no table: the row was stored without an owner
and the monthly counter skipped it. Development and the ordinary suite connect
as the table owner, where no policy applies, so every other test passed while
no tracked row in production had ever been counted.

So this connects as the unprivileged role, writes the way the tracker writes,
and reads the result back as the owner of the tables. It also checks that the
fix did not become a way for the tracking context to read: it still cannot
select from websites, and it cannot stamp a row with another website's owner.
"""
import os
import uuid

import pytest
from app.config import pin_psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

DB_URL = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason=(
        "RLS_TEST_DATABASE_URL not set; must point at a role that is neither "
        "the table owner nor a superuser. This runs in CI. If it is skipping "
        "there, it is testing nothing."
    ),
)


@pytest.fixture(scope="module")
def unprivileged_engine():
    engine = create_engine(pin_psycopg2(DB_URL), future=True)
    with engine.connect() as conn:
        role, is_super, bypasses = conn.execute(
            text(
                "SELECT current_user,"
                "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),"
                "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
            )
        ).one()
        assert not is_super, f"{role} is a superuser; policies would not apply."
        assert not bypasses, f"{role} has BYPASSRLS; policies would not apply."
        owner = conn.execute(
            text("SELECT tableowner FROM pg_tables WHERE tablename = 'pageviews'")
        ).scalar()
        assert owner != role, f"{role} owns pageviews; policies never apply to an owner."
    return engine


@pytest.fixture
def two_sites(engine):
    """Two websites owned by different people. Committed for real, because the
    code under test runs on another connection."""
    made = []
    for label in ("a", "b"):
        suffix = uuid.uuid4().hex[:8]
        owner = f"stamp-{label}-{suffix}@example.com"
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
                {"e": owner},
            )
            website_id = conn.execute(
                text(
                    "INSERT INTO websites (name, domain, user_email, tracking_code,"
                    "                      verification_token, is_verified, is_active,"
                    "                      email_reports_enabled, is_public,"
                    "                      public_password_enabled, created_at) "
                    "VALUES (:n, :d, :o, :tc, :vt, true, true, false, false, false, now()) "
                    "RETURNING id"
                ),
                {
                    "n": f"Stamp {label} {suffix}",
                    "d": f"https://stamp-{label}-{suffix}.example.com",
                    "o": owner,
                    "tc": uuid.uuid4().hex[:8],
                    "vt": f"tok-{suffix}",
                },
            ).scalar()
        made.append({"owner": owner, "website_id": website_id})

    yield made[0], made[1]

    with engine.begin() as conn:
        for site in made:
            for table in ("pageviews", "custom_events"):
                conn.execute(text(f"DELETE FROM {table} WHERE website_id = :w"), {"w": site["website_id"]})
            conn.execute(text("DELETE FROM account_usage WHERE owner_email = :e"), {"e": site["owner"]})
            conn.execute(text("DELETE FROM websites WHERE id = :w"), {"w": site["website_id"]})
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": site["owner"]})


def _as_tracking(conn, website_id):
    conn.execute(
        text(
            "SELECT set_config('app.context', 'tracking', true),"
            "       set_config('app.website_id', :w, true)"
        ),
        {"w": str(website_id)},
    )


def _track_pageview(unprivileged_engine, website_id, traffic_class=None):
    with unprivileged_engine.begin() as conn:
        _as_tracking(conn, website_id)
        conn.execute(
            text(
                'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", traffic_class) '
                "VALUES (:w, '/', :h, now(), :c)"
            ),
            {"w": website_id, "h": uuid.uuid4().hex, "c": traffic_class},
        )


def _usage(engine, owner):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "AND period_start = date_trunc('month', now())::date"
            ),
            {"e": owner},
        ).scalar() or 0


def test_a_tracked_pageview_gets_its_owner(unprivileged_engine, engine, two_sites):
    site, _ = two_sites
    _track_pageview(unprivileged_engine, site["website_id"])

    with engine.begin() as conn:
        owners = conn.execute(
            text("SELECT owner_email FROM pageviews WHERE website_id = :w"),
            {"w": site["website_id"]},
        ).scalars().all()

    assert owners == [site["owner"]]


def test_tracked_rows_are_counted_against_the_owners_month(unprivileged_engine, engine, two_sites):
    site, other = two_sites
    for _ in range(3):
        _track_pageview(unprivileged_engine, site["website_id"])
    with unprivileged_engine.begin() as conn:
        _as_tracking(conn, site["website_id"])
        conn.execute(
            text(
                'INSERT INTO custom_events (website_id, event_name, visitor_hash, "timestamp") '
                "VALUES (:w, 'signup', :h, now())"
            ),
            {"w": site["website_id"], "h": uuid.uuid4().hex},
        )
    # Labelled as from a hosting provider: stored, not charged (#103).
    _track_pageview(unprivileged_engine, site["website_id"], traffic_class="datacenter")

    assert _usage(engine, site["owner"]) == 4
    assert _usage(engine, other["owner"]) == 0


def test_the_tracking_context_still_reads_no_website(unprivileged_engine, two_sites):
    """The lookup runs with the owner's rights inside the trigger and hands
    nothing back. The context itself must be as blind as before."""
    site, _ = two_sites
    with unprivileged_engine.begin() as conn:
        _as_tracking(conn, site["website_id"])
        seen = conn.execute(text("SELECT count(*) FROM websites")).scalar()
        stored = conn.execute(text("SELECT count(*) FROM pageviews")).scalar()

    assert seen == 0
    assert stored == 0


def test_a_row_cannot_be_stamped_for_another_website(unprivileged_engine, engine, two_sites):
    """Pinned to one website, the tracking context may not write a row for
    another, so it cannot make the trigger look up somebody else's owner or
    charge somebody else's month."""
    site, other = two_sites
    with pytest.raises(DBAPIError):
        with unprivileged_engine.begin() as conn:
            _as_tracking(conn, site["website_id"])
            conn.execute(
                text(
                    'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
                    "VALUES (:w, '/', :h, now())"
                ),
                {"w": other["website_id"], "h": uuid.uuid4().hex},
            )

    assert _usage(engine, other["owner"]) == 0
