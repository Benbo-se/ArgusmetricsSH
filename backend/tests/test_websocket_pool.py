"""An open dashboard socket must not hold a pooled database connection.

/ws/live and /ws/debug authenticate, check access, and then wait for the
client for as long as the tab is open. They used to keep their session, and
with it one pooled connection, for that whole time, so as many open tabs as
the pool is large left /track and page loads waiting for a connection.

The pool here is deliberately tiny (one connection, no overflow, a short
timeout) and the sockets outnumber it. If a socket kept its connection, the
second one could not authenticate.
"""
import uuid
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import pin_psycopg2, settings
from app.database import get_db
from app.main import app
from app.services.token_service import TokenService
from tests.conftest import TEST_DATABASE_URL, ws_headers

POOL = 1
SOCKETS = 4


@pytest.fixture
def committed_site(engine):
    """A website and API token that other connections can see.

    The shared `db` fixture rolls back and is invisible to the separate
    sessions this test needs, so these rows are really committed and removed.
    """
    suffix = uuid.uuid4().hex[:8]
    email = f"pool-{suffix}@example.com"
    raw = f"t-{uuid.uuid4().hex}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
            {"e": email},
        )
        wid = conn.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                " verification_token, is_verified, is_active, email_reports_enabled,"
                " is_public, public_password_enabled, created_at)"
                " VALUES (:n, :d, :e, :tc, :vt, true, true, false, false, false, now())"
                " RETURNING id"
            ),
            {"n": f"Pool {suffix}", "d": f"https://{suffix}.example.com", "e": email,
             "tc": uuid.uuid4().hex[:8], "vt": f"tok-{suffix}"},
        ).scalar()
        conn.execute(
            text("INSERT INTO api_tokens (website_id, name, token, created_at)"
                 " VALUES (:w, 'pool test', :t, now())"),
            {"w": wid, "t": TokenService.hash_token(raw)},
        )
    yield {"id": wid, "token": raw}
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM api_tokens WHERE website_id = :w"), {"w": wid})
        conn.execute(text("DELETE FROM websites WHERE id = :w"), {"w": wid})
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


@pytest.mark.parametrize("path", ["live", "debug"])
def test_open_sockets_do_not_exhaust_the_pool(committed_site, path):
    small = create_engine(
        pin_psycopg2(TEST_DATABASE_URL),
        future=True,
        poolclass=QueuePool,
        pool_size=POOL,
        max_overflow=0,
        pool_timeout=2,
    )
    factory = sessionmaker(bind=small, autocommit=False, autoflush=False,
                           expire_on_commit=False)

    def small_pool_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = small_pool_db
    host = urlparse(settings.BASE_URL).netloc
    client = TestClient(app, base_url=f"https://{host}")
    url = f"/ws/{path}/{committed_site['id']}?api_token={committed_site['token']}"
    sockets = []
    try:
        for _ in range(SOCKETS):
            ws = client.websocket_connect(url, headers=ws_headers())
            ws.__enter__()
            sockets.append(ws)
            first = ws.receive_json()
            assert first["type"] in ("connected", "debug_connected"), first
        assert small.pool.checkedout() == 0, (
            f"{small.pool.checkedout()} connections held by {len(sockets)} open sockets"
        )
    finally:
        for ws in sockets:
            ws.__exit__(None, None, None)
        app.dependency_overrides.clear()
        small.dispose()
