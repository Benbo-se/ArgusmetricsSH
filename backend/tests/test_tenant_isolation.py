"""Cross-tenant isolation: prove one customer cannot read another's rows.

This is the test that makes the row-level security rollout safe. Each table
that gains policies gets added to TENANT_TABLES below, and this catches a
policy that is missing, too permissive, or accidentally dropped.

The single most important thing about this file: **it must connect as a role
that is not the table owner**. Postgres never applies policies to a table's
owner, so the same assertions run as the owner would pass while proving
nothing at all. setup_module asserts that the role in use is neither the owner
nor a superuser nor BYPASSRLS, so this test fails loudly rather than
silently going green if that ever changes.

Run locally:
    RLS_TEST_DATABASE_URL=postgresql://argus_app:devapppassword@127.0.0.1:5432/argusmetrics \\
        pytest backend/tests/test_tenant_isolation.py -v
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

# Tables carrying tenant data, added here as each one gains policies.
TENANT_TABLES = [
    "pageviews",
    "custom_events",
    "ecommerce_events",
    "goal_conversions",
    "funnel_events",
]

DB_URL = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="RLS_TEST_DATABASE_URL not set; must point at an unprivileged role",
)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DB_URL, future=True)
    with eng.connect() as conn:
        role, is_super, bypasses = conn.execute(
            text(
                "SELECT current_user,"
                "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),"
                "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
            )
        ).one()

        # Without these, every assertion below would pass vacuously.
        assert not is_super, (
            f"{role} is a superuser, which bypasses row-level security. "
            "This test would pass without testing anything."
        )
        assert not bypasses, f"{role} has BYPASSRLS, so policies do not apply to it."
        for table in TENANT_TABLES:
            owner = conn.execute(
                text("SELECT tableowner FROM pg_tables WHERE tablename = :t"),
                {"t": table},
            ).scalar()
            assert owner != role, (
                f"{role} owns {table}; policies never apply to a table's owner, "
                "so this test would prove nothing."
            )
            enabled = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            ).scalar()
            assert enabled, f"row-level security is not enabled on {table}"
    return eng


def _context(conn, context, user_email="", website_id=""):
    conn.execute(
        text(
            "SELECT set_config('app.context', :c, true),"
            "       set_config('app.user_email', :u, true),"
            "       set_config('app.website_id', :w, true)"
        ),
        {"c": context, "u": user_email, "w": str(website_id)},
    )


@pytest.fixture
def tenants(engine):
    """Two customers, each with their own website and one pageview.

    Created in the job context, which is the one allowed to write across
    tenants, then rolled back so the test leaves nothing behind.
    """
    conn = engine.connect()
    trans = conn.begin()
    _context(conn, "job")

    suffix = uuid.uuid4().hex[:8]
    made = {}
    for name in ("alice", "bob"):
        email = f"{name}-{suffix}@example.invalid"
        conn.execute(
            text("INSERT INTO users (email, is_verified, created_at) "
                 "VALUES (:e, true, now()) ON CONFLICT (email) DO NOTHING"),
            {"e": email},
        )
        website_id = conn.execute(
            text(
                # Every NOT NULL column without a default has to be listed, or
                # the fixture fails before it can test anything.
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES (:n, :d, :e, :tc, :vt, true, true, false, false, false, now()) "
                "RETURNING id"
            ),
            {
                "n": f"{name} site", "d": f"https://{name}-{suffix}.example.invalid",
                "e": email, "tc": f"{name[:2]}{suffix}", "vt": f"tok-{name}-{suffix}",
            },
        ).scalar()
        conn.execute(
            text("INSERT INTO pageviews (website_id, path, visitor_hash, timestamp) "
                 "VALUES (:w, :p, :h, now())"),
            {"w": website_id, "p": f"/{name}-secret", "h": f"hash-{name}-{suffix}"},
        )
        made[name] = {"email": email, "website_id": website_id, "path": f"/{name}-secret"}

    yield conn, made
    trans.rollback()
    conn.close()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_context_sees_nothing(tenants, table):
    """A request that declares no context must read nothing: fail closed."""
    conn, _ = tenants
    _context(conn, "")
    assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_owner_sees_only_their_own_rows(tenants):
    conn, made = tenants
    _context(conn, "user", user_email=made["alice"]["email"])
    paths = {r[0] for r in conn.execute(text("SELECT path FROM pageviews"))}
    assert made["alice"]["path"] in paths
    assert made["bob"]["path"] not in paths, "Alice can read Bob's pageviews"


def test_neither_tenant_can_read_the_other(tenants):
    conn, made = tenants
    for reader, other in (("alice", "bob"), ("bob", "alice")):
        _context(conn, "user", user_email=made[reader]["email"])
        rows = conn.execute(
            text("SELECT count(*) FROM pageviews WHERE website_id = :w"),
            {"w": made[other]["website_id"]},
        ).scalar()
        assert rows == 0, f"{reader} can read {other}'s rows"


def test_public_context_is_pinned_to_one_website(tenants):
    """A share link must expose its own website and no other."""
    conn, made = tenants
    _context(conn, "public", website_id=made["alice"]["website_id"])
    paths = {r[0] for r in conn.execute(text("SELECT path FROM pageviews"))}
    assert made["alice"]["path"] in paths
    assert made["bob"]["path"] not in paths, "a public link exposed another website"


def test_tracking_context_can_write_but_not_read(tenants):
    """The tracking endpoints take input from any visitor's browser."""
    conn, made = tenants
    _context(conn, "tracking")
    assert conn.execute(text("SELECT count(*) FROM pageviews")).scalar() == 0, \
        "the tracking context can read pageviews"
    conn.execute(
        text("INSERT INTO pageviews (website_id, path, visitor_hash, timestamp) "
             "VALUES (:w, '/tracked', 'h', now())"),
        {"w": made["alice"]["website_id"]},
    )


def test_a_stranger_sees_nothing(tenants):
    conn, _ = tenants
    _context(conn, "user", user_email="nobody@example.invalid")
    assert conn.execute(text("SELECT count(*) FROM pageviews")).scalar() == 0


def _add_member(conn, website_id, user_email, status):
    conn.execute(
        text(
            "INSERT INTO website_members "
            "  (website_id, user_email, role, invited_at, status) "
            "VALUES (:w, :e, 'viewer', now(), CAST(:s AS memberstatus))"
        ),
        {"w": website_id, "e": user_email, "s": status},
    )


class TestConfigurationTables:
    """websites and website_members, which are not traffic and behave differently.

    A traffic table is written by the tracking context and read by nobody
    else. These two are read in every context, which is why they came last.
    """

    def test_a_stranger_sees_no_websites(self, tenants):
        conn, made = tenants
        _context(conn, "user", user_email="nobody@example.invalid")
        assert conn.execute(text("SELECT count(*) FROM websites")).scalar() == 0

    def test_neither_tenant_sees_the_other_s_website(self, tenants):
        conn, made = tenants
        for reader, other in (("alice", "bob"), ("bob", "alice")):
            _context(conn, "user", user_email=made[reader]["email"])
            rows = conn.execute(
                text("SELECT count(*) FROM websites WHERE id = :w"),
                {"w": made[other]["website_id"]},
            ).scalar()
            assert rows == 0, f"{reader} can see {other}'s website"

    def test_an_owner_sees_their_own_website(self, tenants):
        conn, made = tenants
        _context(conn, "user", user_email=made["alice"]["email"])
        rows = conn.execute(
            text("SELECT count(*) FROM websites WHERE id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar()
        assert rows == 1

    def test_an_active_member_sees_the_shared_website(self, tenants):
        conn, made = tenants
        _add_member(conn, made["alice"]["website_id"], made["bob"]["email"], "active")
        _context(conn, "user", user_email=made["bob"]["email"])
        rows = conn.execute(
            text("SELECT count(*) FROM websites WHERE id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar()
        assert rows == 1, "an active member cannot see the website shared with them"

    @pytest.mark.parametrize("status", ["pending", "revoked"])
    def test_an_inactive_member_sees_no_website(self, tenants, status):
        conn, made = tenants
        _add_member(conn, made["alice"]["website_id"], made["bob"]["email"], status)
        _context(conn, "user", user_email=made["bob"]["email"])
        rows = conn.execute(
            text("SELECT count(*) FROM websites WHERE id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar()
        assert rows == 0, f"a {status} member can see the website"

    def test_the_tracking_context_cannot_read_websites(self, tenants):
        """The whole reason the resolver functions exist.

        Tracking is unauthenticated and takes a code from a visitor's browser.
        It resolves that code through a SECURITY DEFINER function, so it needs
        no read access here, and a websites row carries verification_token,
        public_share_token and public_password_hash.
        """
        conn, _ = tenants
        _context(conn, "tracking")
        assert conn.execute(text("SELECT count(*) FROM websites")).scalar() == 0

    def test_a_member_list_is_visible_to_the_owner_and_the_member_only(self, tenants):
        conn, made = tenants
        _add_member(conn, made["alice"]["website_id"], made["bob"]["email"], "active")

        _context(conn, "user", user_email=made["alice"]["email"])
        assert conn.execute(
            text("SELECT count(*) FROM website_members WHERE website_id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar() == 1, "the owner cannot see their own team"

        _context(conn, "user", user_email=made["bob"]["email"])
        assert conn.execute(
            text("SELECT count(*) FROM website_members WHERE website_id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar() == 1, "a member cannot see their own membership"

        _context(conn, "user", user_email="nobody@example.invalid")
        assert conn.execute(
            text("SELECT count(*) FROM website_members WHERE website_id = :w"),
            {"w": made["alice"]["website_id"]},
        ).scalar() == 0, "a stranger can read someone's team list"

    def test_no_context_reads_neither_table(self, tenants):
        """Fail closed: a request that declares nothing sees nothing."""
        conn, _ = tenants
        _context(conn, "")
        assert conn.execute(text("SELECT count(*) FROM websites")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM website_members")).scalar() == 0




@pytest.mark.parametrize("status", ["pending", "revoked"])
def test_a_member_who_is_not_active_reads_nothing(tenants, status):
    """Membership alone is not access. The status decides.

    The application requires status ACTIVE everywhere it checks a role, so a
    policy that accepts any membership row is more permissive than the code
    above it. That matters most for 'revoked', which is the case where someone
    has deliberately had their access taken away, and where the database
    refusing is the whole point of having policies at all.
    """
    conn, made = tenants
    _add_member(conn, made["alice"]["website_id"], made["bob"]["email"], status)

    _context(conn, "user", user_email=made["bob"]["email"])
    paths = {r[0] for r in conn.execute(text("SELECT path FROM pageviews"))}

    assert made["alice"]["path"] not in paths, (
        f"a {status} member can read the website's pageviews"
    )


def test_an_active_member_reads_the_shared_website(tenants):
    """The other half: sharing has to keep working."""
    conn, made = tenants
    _add_member(conn, made["alice"]["website_id"], made["bob"]["email"], "active")

    _context(conn, "user", user_email=made["bob"]["email"])
    paths = {r[0] for r in conn.execute(text("SELECT path FROM pageviews"))}

    assert made["alice"]["path"] in paths, "an active member lost access"
