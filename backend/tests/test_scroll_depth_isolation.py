"""Completing a pageview's scroll depth, as the role production runs as.

The tracking context could insert into pageviews and nothing else, which is
what keeps a tracking code, public in every customer's page source, from
being a way to read that site's traffic. Filling in the scroll depth needs an
UPDATE, and an UPDATE policy is the first thing this context has ever been
given beyond inserting.

An UPDATE policy was the first attempt and it does not work: Postgres reads
the rows to evaluate an UPDATE's WHERE clause, that read obeys SELECT policies,
and the tracking context has none. The update matched nothing while every
security assertion passed. A SECURITY DEFINER function does it instead, which
is what this schema already does for every other unauthenticated lookup.

So this connects as the unprivileged role and checks both directions: that the
completion lands, and that it did not become a way to read, to reach another
website, or to write with no context at all. Development connects as the table
owner, where every policy here is inert, so none of the other tests can tell.
"""
import os
import uuid

import pytest
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
    engine = create_engine(DB_URL, future=True)
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
    """Two websites owned by different people, each with one pageview.

    Committed for real, because the code under test runs on another
    connection. Cleaned up by owner address afterwards.
    """
    made = []
    for label in ("a", "b"):
        suffix = uuid.uuid4().hex[:8]
        owner = f"scroll-{label}-{suffix}@example.com"
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, is_verified, created_at) "
                    "VALUES (:e, true, now())"
                ),
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
                    "n": f"Scroll {label} {suffix}",
                    "d": f"https://scroll-{label}-{suffix}.example.com",
                    "o": owner,
                    "tc": uuid.uuid4().hex[:8],
                    "vt": f"tok-{suffix}",
                },
            ).scalar()
            conn.execute(
                text(
                    'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
                    "VALUES (:w, :p, :h, now())"
                ),
                {"w": website_id, "p": "/read-me", "h": f"hash-{suffix}"},
            )
        made.append(
            {"owner": owner, "website_id": website_id, "hash": f"hash-{suffix}"}
        )

    yield made[0], made[1]

    with engine.begin() as conn:
        for site in made:
            conn.execute(
                text("DELETE FROM pageviews WHERE website_id = :w"),
                {"w": site["website_id"]},
            )
            conn.execute(
                text("DELETE FROM websites WHERE id = :w"), {"w": site["website_id"]}
            )
            conn.execute(
                text("DELETE FROM users WHERE email = :e"), {"e": site["owner"]}
            )


def _as_tracking(session, website_id):
    session.execute(
        text(
            "SELECT set_config('app.context', 'tracking', true),"
            "       set_config('app.website_id', :w, true)"
        ),
        {"w": str(website_id)},
    )


def _depth(engine, website_id):
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT scroll_depth FROM pageviews WHERE website_id = :w"),
            {"w": website_id},
        ).scalar()


def _complete(session, site, depth):
    return session.execute(
        text("SELECT argus_complete_scroll_depth(:w, :h, :p, :d)"),
        {"w": site["website_id"], "h": site["hash"], "p": "/read-me", "d": depth},
    ).scalar()


def test_the_update_lands(unprivileged_engine, engine, two_sites):
    """Without this the whole feature is decoration, again."""
    site, _ = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, site["website_id"])
        assert _complete(session, site, 73) is True
        session.commit()
    finally:
        session.close()

    assert _depth(engine, site["website_id"]) == 73


def test_it_only_goes_up(unprivileged_engine, engine, two_sites):
    """A visitor who comes back and leaves at the top keeps the deeper value."""
    site, _ = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, site["website_id"])
        _complete(session, site, 80)
        session.commit()
        assert _complete(session, site, 20) is False
        session.commit()
    finally:
        session.close()

    assert _depth(engine, site["website_id"]) == 80


def test_the_function_checks_the_declared_context(unprivileged_engine, engine, two_sites):
    """The website arrives as a parameter, so the function must not trust it.

    A SECURITY DEFINER function runs as the owner: a parameter it does not
    verify is one the caller may choose. Here a tracking context narrowed to
    one website asks it to write to another, with that website's own visitor
    hash, and it must refuse.
    """
    mine, theirs = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, mine["website_id"])
        result = _complete(session, theirs, 55)
        session.commit()
    finally:
        session.close()

    assert result is False
    assert _depth(engine, theirs["website_id"]) is None, (
        "the function wrote to a website the caller was not scoped to"
    )


def test_it_refuses_with_no_context_at_all(unprivileged_engine, engine, two_sites):
    site, _ = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        result = session.execute(
            text("SELECT argus_complete_scroll_depth(:w, :h, :p, :d)"),
            {"w": site["website_id"], "h": site["hash"], "p": "/read-me", "d": 42},
        ).scalar()
        session.commit()
    finally:
        session.close()

    assert result is False
    assert _depth(engine, site["website_id"]) is None


def test_a_direct_update_still_writes_nothing(unprivileged_engine, engine, two_sites):
    """There is no UPDATE policy on pageviews, and there must not be one.

    Adding one was the first attempt and it failed for an instructive reason:
    Postgres reads the rows to evaluate an UPDATE's WHERE clause, that read
    obeys SELECT policies, and the tracking context has none. The update
    matched nothing while every security assertion still passed. The function
    is the way in; a raw statement is not.
    """
    mine, theirs = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, mine["website_id"])
        session.execute(
            text("UPDATE pageviews SET scroll_depth = 99 WHERE website_id = :w"),
            {"w": theirs["website_id"]},
        )
        session.commit()
    finally:
        session.close()

    assert _depth(engine, theirs["website_id"]) is None, (
        "a tracking context reached another website's rows"
    )


def test_it_still_cannot_read(unprivileged_engine, two_sites):
    """The update must not have brought read access with it.

    An UPDATE policy governs which rows a statement may touch. It is not a
    SELECT policy, and the tracking context still has none.
    """
    site, _ = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    try:
        _as_tracking(session, site["website_id"])
        rows = session.execute(
            text("SELECT count(*) FROM pageviews WHERE website_id = :w"),
            {"w": site["website_id"]},
        ).scalar()
    finally:
        session.close()

    assert rows == 0, (
        "the tracking context can read pageviews, so a tracking code is now "
        "enough to read that website's traffic"
    )


def test_it_cannot_move_a_row_to_another_website(unprivileged_engine, engine, two_sites):
    """WITH CHECK, not only USING. Otherwise a row could be updated out."""
    mine, theirs = two_sites
    session = sessionmaker(bind=unprivileged_engine)()
    moved = True
    try:
        _as_tracking(session, mine["website_id"])
        try:
            session.execute(
                text("UPDATE pageviews SET website_id = :other WHERE website_id = :w"),
                {"other": theirs["website_id"], "w": mine["website_id"]},
            )
            session.commit()
        except Exception:
            session.rollback()
            moved = False
    finally:
        session.close()

    assert not moved or _depth(engine, mine["website_id"]) is None, (
        "a row was moved to another website"
    )
    with engine.begin() as conn:
        still_mine = conn.execute(
            text("SELECT count(*) FROM pageviews WHERE website_id = :w"),
            {"w": mine["website_id"]},
        ).scalar()
    assert still_mine == 1, "the row left its own website"
