"""A funnel step is recorded once per visitor, as the role production runs as.

The recording service looked for an existing funnel_events row before adding
one. The tracking context may insert into that table and may not read it, so
the lookup never found anything and every pageview on a step path added a row.
Development connects as the table owner, where the policies are inert, so
nothing there could tell.

The insert-if-absent now happens in a SECURITY DEFINER function, like the
scroll depth one. This connects as the unprivileged role and checks that the
dedup holds, that the context still cannot read the table, and that the
function does not take a funnel that belongs to another website.
"""
import os
import uuid

import pytest
from app.config import pin_psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
            text("SELECT tableowner FROM pg_tables WHERE tablename = 'funnel_events'")
        ).scalar()
        assert owner != role, f"{role} owns funnel_events; policies never apply to an owner."
    return engine


@pytest.fixture
def two_funnels(engine):
    """Two websites with one funnel each, committed for real."""
    made = []
    for label in ("a", "b"):
        suffix = uuid.uuid4().hex[:8]
        owner = f"funnel-{label}-{suffix}@example.com"
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
                    "n": f"Funnel {label} {suffix}",
                    "d": f"https://funnel-{label}-{suffix}.example.com",
                    "o": owner,
                    "tc": uuid.uuid4().hex[:8],
                    "vt": f"tok-{suffix}",
                },
            ).scalar()
            funnel_id = conn.execute(
                text(
                    "INSERT INTO funnels (website_id, name, steps, is_active, created_at) "
                    "VALUES (:w, 'F', CAST(:s AS json), true, now()) RETURNING id"
                ),
                {
                    "w": website_id,
                    "s": '[{"step":1,"name":"One","path":"/one"},{"step":2,"name":"Two","path":"/two"}]',
                },
            ).scalar()
        made.append({"owner": owner, "website_id": website_id, "funnel_id": funnel_id})

    yield made[0], made[1]

    with engine.begin() as conn:
        for site in made:
            conn.execute(text("DELETE FROM funnel_events WHERE funnel_id = :f"), {"f": site["funnel_id"]})
            conn.execute(text("DELETE FROM funnels WHERE id = :f"), {"f": site["funnel_id"]})
            conn.execute(text("DELETE FROM websites WHERE id = :w"), {"w": site["website_id"]})
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": site["owner"]})


def _count(engine, funnel_id):
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT count(*) FROM funnel_events WHERE funnel_id = :f"),
            {"f": funnel_id},
        ).scalar()


def _as_tracking(session, website_id):
    session.execute(
        text(
            "SELECT set_config('app.context', 'tracking', true),"
            "       set_config('app.website_id', :w, true)"
        ),
        {"w": str(website_id)},
    )


def _record_via_service(unprivileged_engine, site, visitor, path):
    """The real recording path, in a fresh tracking-context transaction."""
    from app.services.analytics_recording_service import AnalyticsRecordingService

    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, site["website_id"])
        AnalyticsRecordingService(session)._record_funnel_steps(
            site["website_id"], path, visitor
        )
        session.commit()
    finally:
        session.close()


def test_a_repeat_visit_to_a_step_adds_no_row(unprivileged_engine, engine, two_funnels):
    site, _ = two_funnels
    for _ in range(3):
        _record_via_service(unprivileged_engine, site, "visitor-1", "/one")

    assert _count(engine, site["funnel_id"]) == 1


def test_each_step_and_each_visitor_still_gets_a_row(unprivileged_engine, engine, two_funnels):
    """The dedup must not swallow what it should keep."""
    site, _ = two_funnels
    _record_via_service(unprivileged_engine, site, "visitor-1", "/one")
    _record_via_service(unprivileged_engine, site, "visitor-1", "/two")
    _record_via_service(unprivileged_engine, site, "visitor-2", "/one")

    assert _count(engine, site["funnel_id"]) == 3
    with engine.begin() as conn:
        completed = conn.execute(
            text(
                "SELECT completed FROM funnel_events "
                "WHERE funnel_id = :f AND step_number = 2"
            ),
            {"f": site["funnel_id"]},
        ).scalar()
    assert completed is True, "the last step must still mark the funnel completed"


def test_the_function_refuses_another_websites_funnel(unprivileged_engine, engine, two_funnels):
    """The funnel id is a parameter, so the function checks it against the context."""
    mine, theirs = two_funnels
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, mine["website_id"])
        result = session.execute(
            text("SELECT argus_record_funnel_step(:f, 'v', 1, 'One', '/one', false)"),
            {"f": theirs["funnel_id"]},
        ).scalar()
        session.commit()
    finally:
        session.close()

    assert result is False
    assert _count(engine, theirs["funnel_id"]) == 0


def test_the_function_refuses_with_no_context(unprivileged_engine, engine, two_funnels):
    site, _ = two_funnels
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        result = session.execute(
            text("SELECT argus_record_funnel_step(:f, 'v', 1, 'One', '/one', false)"),
            {"f": site["funnel_id"]},
        ).scalar()
        session.commit()
    finally:
        session.close()

    assert result is False
    assert _count(engine, site["funnel_id"]) == 0


def test_the_tracking_context_still_cannot_read_funnel_events(unprivileged_engine, two_funnels):
    """The fix must not have been a SELECT policy."""
    site, _ = two_funnels
    _record_via_service(unprivileged_engine, site, "visitor-1", "/one")
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, site["website_id"])
        rows = session.execute(
            text("SELECT count(*) FROM funnel_events WHERE funnel_id = :f"),
            {"f": site["funnel_id"]},
        ).scalar()
    finally:
        session.close()

    assert rows == 0
