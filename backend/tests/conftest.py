"""Shared test fixtures.

Two decisions worth stating, because both were learned the hard way.

**Tests run against real PostgreSQL, never SQLite.** This codebase uses JSONB,
GIN indexes, triggers and row-level security, none of which SQLite has. More to
the point, twice in this project a test passed while the thing it tested was
broken, both times because the environment running the test was not the
environment running the code. An in-memory stand-in would guarantee that
happens again.

**Each test runs inside a transaction that is rolled back.** The application
commits mid-request, so the session joins an outer transaction with
create_savepoint: a commit inside the app releases a savepoint, and the
rollback here still undoes the whole thing. Tests can therefore run against a
database with real data in it without leaving anything behind.

Run:
    docker exec argusmetrics-backend python -m pytest tests/ -v
"""
import os
import uuid
from urllib.parse import urlparse
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", os.environ.get("DATABASE_URL")
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="no database configured"
)


@pytest.fixture(scope="session")
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("no database configured")
    eng = create_engine(TEST_DATABASE_URL, future=True)
    with eng.connect() as conn:
        # Fail loudly rather than erroring one assertion at a time if the
        # schema was never migrated.
        missing = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'pageviews'"
            )
        ).scalar()
        assert missing, (
            "pageviews does not exist. Run 'alembic upgrade head' against "
            f"{TEST_DATABASE_URL.rsplit('@', 1)[-1]} first."
        )
    return eng


@pytest.fixture
def db(engine):
    """A session whose writes are always undone, app commits included."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    """A TestClient whose requests share the test's rolled-back session.

    Deliberately not used as a context manager, which would run the lifespan
    handlers on every test. Those start the background scheduler and, on the
    way out, dispose the engine the whole session is using. The scheduler is
    a singleton that cannot be restarted once stopped, so the second test in
    a run would fail on teardown with SchedulerNotRunningError.

    Nothing in lifespan is needed here anyway: it logs, checks the connection
    and starts jobs that have no business running during a test.

    base_url matters. In production mode the app adds TrustedHostMiddleware
    with the one host from BASE_URL, and TestClient's default host of
    "testserver" is not it, so every request is rejected with 400 before it
    reaches a route. That failure is quiet in the worst way: a test expecting
    a 400 passes on the middleware's 400 while never exercising the endpoint
    at all. Three of these did exactly that in CI. Use the host the app
    actually accepts, and assert on why a request failed, never just on 400.
    """
    app.dependency_overrides[get_db] = lambda: db
    test_client = TestClient(app, base_url=settings.BASE_URL.rstrip("/"))

    # Prove requests reach a route before any test draws a conclusion from a
    # status code. Without this, a middleware rejecting every request looks
    # like a handful of endpoint failures plus some suspiciously green
    # negative tests.
    probe = test_client.get("/health")
    assert probe.status_code == 200, (
        f"requests are not reaching the app: /health returned "
        f"{probe.status_code} for host {settings.BASE_URL}. No test below "
        "is testing what it claims to."
    )

    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def website(db):
    """A verified, active website owned by a throwaway user.

    Verified because the tracking endpoints refuse to record for a domain that
    is not, so an unverified fixture would make every tracking test fail for a
    reason that has nothing to do with what it is testing.
    """
    suffix = uuid.uuid4().hex[:8]
    email = f"test-{suffix}@example.com"  # example.invalid is rejected by the email validator

    db.execute(
        text(
            "INSERT INTO users (email, is_verified, created_at) "
            "VALUES (:e, true, now()) ON CONFLICT (email) DO NOTHING"
        ),
        {"e": email},
    )
    website_id = db.execute(
        text(
            "INSERT INTO websites (name, domain, user_email, tracking_code,"
            "                      verification_token, is_verified, is_active,"
            "                      email_reports_enabled, is_public,"
            "                      public_password_enabled, created_at) "
            "VALUES (:n, :d, :e, :tc, :vt, true, true, false, false, false, now()) "
            "RETURNING id"
        ),
        {
            "n": f"Test site {suffix}",
            "d": f"https://{suffix}.example.com",
            "e": email,
            "tc": suffix,
            "vt": f"tok-{suffix}",
        },
    ).scalar()
    db.commit()

    return {
        "id": website_id,
        "email": email,
        "tracking_code": suffix,
        "domain": f"https://{suffix}.example.com",
    }


@pytest.fixture
def owner_client(client, db, website):
    """A client authenticated as the fixture website's owner.

    Both authentication dependencies are overridden, because routes use one or
    the other, and the row-level security context is declared here the way the
    real dependencies declare it. Authentication itself is covered by
    test_auth_context; this exists so feature tests can get past the door.
    """
    from app.database import set_rls_context
    from app.models.user import User
    from app.routers.analytics import get_current_user_or_token
    from app.routers.auth import get_current_user

    user = db.query(User).filter(User.email == website["email"]).first()

    def _as_owner():
        set_rls_context(db, context="user", user_email=user.email)
        return user

    app.dependency_overrides[get_current_user] = _as_owner
    app.dependency_overrides[get_current_user_or_token] = _as_owner
    yield client
    for dep in (get_current_user, get_current_user_or_token):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def shared_website(db, website):
    """The fixture website, published behind a share token."""
    token = uuid.uuid4().hex[:32]
    db.execute(
        text(
            "UPDATE websites SET is_public = true, public_share_token = :t "
            "WHERE id = :w"
        ),
        {"t": token, "w": website["id"]},
    )
    db.commit()
    return {**website, "share_token": token}


@pytest.fixture
def goal(db, website):
    """A goal on the fixture website, keyed on the event name the app matches."""
    event_name = f"signup_{uuid.uuid4().hex[:6]}"
    goal_id = db.execute(
        text(
            "INSERT INTO goals (website_id, name, event_name, created_at) "
            "VALUES (:w, :n, :e, now()) RETURNING id"
        ),
        {"w": website["id"], "n": "Test goal", "e": event_name},
    ).scalar()
    db.commit()
    return {"id": goal_id, "event_name": event_name}


def ws_headers():
    """Headers a websocket handshake needs to get past TrustedHostMiddleware.

    TestClient honours base_url for HTTP but sends Host: testserver on every
    websocket handshake regardless, so in production mode the middleware
    answers "Invalid host header" and the connection never reaches the
    endpoint. That looks exactly like an auth failure, so set the host
    explicitly rather than reading anything into a refused connection.
    """
    return {"host": urlparse(settings.BASE_URL).netloc}


def reason(response):
    """The app's explanation for a failed request, lowercased.

    Asserting on a bare status code is how three tests here passed against a
    middleware that was rejecting every request. A negative test should say
    which failure it expects.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.lower()
    return str(body.get("message") or body.get("detail") or body).lower()


def count(db, table, **where):
    """Row count, for asserting that a write path actually wrote something.

    A 200 response is not evidence a row landed. Several features in this
    codebase rendered and returned 200 while writing nothing at all.
    """
    clause = " AND ".join(f"{col} = :{col}" for col in where) or "true"
    return db.execute(
        text(f"SELECT count(*) FROM {table} WHERE {clause}"), where
    ).scalar()
