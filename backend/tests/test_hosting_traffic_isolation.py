"""Hosting-provider classification, as the role production runs as (#103).

Classifying an address happens in the tracking context, which is the context
of anybody at all: a tracking code is public in every customer's page source.
It may insert events and read nothing, and this feature must not become the
first exception. So the lookup is a SECURITY DEFINER function that answers
with one word, and these check both directions as an unprivileged role: that
the function works there, and that it is the whole of what was handed out.

The other half is the reports. Whether a labelled row is counted is decided
by a subquery on the website's own row, and that row is only readable where a
policy says so. Development connects as the table owner, where every policy
is inert, so the ordinary suite would pass with the setting unreadable and
every website silently stuck on the default. This is where that is caught.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.config import pin_psycopg2
from app.models.pageview import Pageview
from app.services.filters import counted, left_out

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
def engine():
    eng = create_engine(pin_psycopg2(DB_URL), future=True)
    with eng.connect() as conn:
        role, is_super, bypasses = conn.execute(
            text(
                "SELECT current_user,"
                "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),"
                "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
            )
        ).one()
        assert not is_super, f"{role} is a superuser; policies would not apply."
        assert not bypasses, f"{role} has BYPASSRLS; policies would not apply."
        for table in ("hosting_network_ranges", "pageviews", "websites"):
            owner = conn.execute(
                text("SELECT tableowner FROM pg_tables WHERE tablename = :t"), {"t": table}
            ).scalar()
            assert owner != role, f"{role} owns {table}; policies never apply to an owner."
            enabled = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
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
def world(engine):
    """Two ranges, and two customers with one reader and one labelled crawler
    each. Made in the job context and rolled back afterwards."""
    conn = engine.connect()
    trans = conn.begin()
    _context(conn, "job")

    conn.execute(text("DELETE FROM hosting_network_ranges"))
    conn.execute(
        text(
            "INSERT INTO hosting_network_ranges (start_ip, end_ip) VALUES "
            "('5.9.0.0', '5.9.255.255'),"
            "('2a01:4f8::', '2a01:4f8:ffff:ffff:ffff:ffff:ffff:ffff')"
        )
    )

    suffix = uuid.uuid4().hex[:8]
    made = {}
    for name in ("alice", "bob"):
        email = f"{name}-{suffix}@example.invalid"
        conn.execute(
            text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
            {"e": email},
        )
        website_id = conn.execute(
            text(
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
        for visitor, label in (("reader", None), ("crawler", "datacenter")):
            conn.execute(
                text(
                    "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp, traffic_class) "
                    "VALUES (:w, '/', :h, now(), :label)"
                ),
                {"w": website_id, "h": f"{visitor}-{suffix}", "label": label},
            )
        made[name] = {"email": email, "website_id": website_id, "tracking_code": f"{name[:2]}{suffix}"}

    yield conn, made

    trans.rollback()
    conn.close()


def _counted(conn, website_id):
    return conn.execute(
        select(func.count()).select_from(Pageview).where(
            Pageview.website_id == website_id, counted(website_id)
        )
    ).scalar()


def _left_out(conn, website_id):
    return conn.execute(
        select(func.count()).select_from(Pageview).where(
            Pageview.website_id == website_id, left_out(website_id)
        )
    ).scalar()


def _switch_off(conn, website_id):
    _context(conn, "job")
    conn.execute(
        text("UPDATE websites SET exclude_datacenter = false WHERE id = :w"), {"w": website_id}
    )


class TestTheTrackingContext:
    def test_it_can_classify_an_address(self, world):
        conn, _made = world
        _context(conn, "tracking")

        def classify(address):
            return conn.execute(
                text("SELECT argus_traffic_class_for_ip(CAST(:ip AS inet))"), {"ip": address}
            ).scalar()

        assert classify("5.9.1.1") == "datacenter"
        assert classify("2a01:4f8::1") == "datacenter"
        assert classify("81.224.1.1") is None
        assert classify("5.10.0.0") is None

    def test_it_cannot_read_the_table(self, world):
        conn, _made = world
        _context(conn, "tracking")

        assert conn.execute(text("SELECT count(*) FROM hosting_network_ranges")).scalar() == 0

    def test_it_cannot_change_the_table(self, world):
        """A crawler that could delete the ranges would count itself back in."""
        conn, _made = world
        _context(conn, "tracking")

        assert conn.execute(text("DELETE FROM hosting_network_ranges")).rowcount == 0
        assert conn.execute(
            text("UPDATE hosting_network_ranges SET end_ip = start_ip")
        ).rowcount == 0
        with pytest.raises(DBAPIError, match="row-level security"):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO hosting_network_ranges (start_ip, end_ip) "
                        "VALUES ('81.224.0.0', '81.224.255.255')"
                    )
                )

        _context(conn, "job")
        assert conn.execute(text("SELECT count(*) FROM hosting_network_ranges")).scalar() == 2

    def test_the_function_answers_one_word_and_nothing_else(self, world):
        """What the context can learn through it is one bit about an address
        it was handed. Not a range, not a row, not a second column."""
        conn, _made = world
        _context(conn, "tracking")

        signature = conn.execute(
            text(
                "SELECT pg_get_function_result(p.oid), p.proretset, p.prosecdef, p.proconfig "
                "FROM pg_proc p WHERE p.proname = 'argus_traffic_class_for_ip'"
            )
        ).all()
        assert len(signature) == 1, "exactly one function by that name"
        result_type, returns_set, security_definer, config = signature[0]
        assert result_type == "character varying"
        assert returns_set is False
        assert security_definer is True
        assert any(item.startswith("search_path=") for item in config), (
            "a SECURITY DEFINER function without a pinned search_path runs "
            "whatever the caller put first on it"
        )

        answers = {
            conn.execute(
                text("SELECT argus_traffic_class_for_ip(CAST(:ip AS inet))"), {"ip": address}
            ).scalar()
            for address in ("0.0.0.0", "5.9.0.0", "5.9.255.255", "255.255.255.255", "::", "2a01:4f8::")
        }
        assert answers == {None, "datacenter"}

    def test_the_resolver_hands_it_the_switch_and_still_no_website(self, world):
        conn, made = world
        _switch_off(conn, made["bob"]["website_id"])
        _context(conn, "tracking")

        def resolved(name):
            return conn.execute(
                text("SELECT exclude_datacenter FROM argus_resolve_tracking_code(:c)"),
                {"c": made[name]["tracking_code"]},
            ).scalar()

        assert resolved("alice") is True
        assert resolved("bob") is False
        assert conn.execute(text("SELECT count(*) FROM websites")).scalar() == 0

    def test_it_may_write_a_labelled_pageview(self, world):
        """The label is one more column on a row the context could already
        insert, and it still cannot read the row back."""
        conn, made = world
        alice = made["alice"]
        _context(conn, "tracking", website_id=alice["website_id"])

        conn.execute(
            text(
                "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp, traffic_class) "
                "VALUES (:w, '/new', 'v', now(), 'datacenter')"
            ),
            {"w": alice["website_id"]},
        )

        assert conn.execute(text("SELECT count(*) FROM pageviews")).scalar() == 0


def test_a_labelled_pageview_is_not_charged_to_the_account(world):
    """The trigger's WHEN clause, as a role that does not own the table."""
    conn, made = world
    alice = made["alice"]
    _context(conn, "job")

    def usage():
        return conn.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "AND period_start = date_trunc('month', now())::date"
            ),
            {"e": alice["email"]},
        ).scalar() or 0

    def write(label):
        conn.execute(
            text(
                "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp, traffic_class) "
                "VALUES (:w, '/new', 'v', now(), :label)"
            ),
            {"w": alice["website_id"], "label": label},
        )

    before = usage()
    write("datacenter")
    assert usage() == before
    write(None)
    assert usage() == before + 1, "the control: an ordinary pageview is charged"


@pytest.mark.parametrize("context", ["", "user", "public"])
def test_no_other_context_reads_or_writes_the_table(world, context):
    conn, made = world
    _context(conn, context, user_email=made["alice"]["email"], website_id=made["alice"]["website_id"])

    assert conn.execute(text("SELECT count(*) FROM hosting_network_ranges")).scalar() == 0
    assert conn.execute(text("DELETE FROM hosting_network_ranges")).rowcount == 0


class TestTheSwitchIsReadableWhereReportsAreMade:
    def test_the_owner_sees_their_own_setting(self, world):
        conn, made = world
        alice = made["alice"]

        _context(conn, "user", user_email=alice["email"])
        assert _counted(conn, alice["website_id"]) == 1
        assert _left_out(conn, alice["website_id"]) == 1

        _switch_off(conn, alice["website_id"])
        _context(conn, "user", user_email=alice["email"])
        assert _counted(conn, alice["website_id"]) == 2, (
            "the owner turned the exclusion off and the report still leaves "
            "the rows out: the setting is not readable in the user context"
        )
        assert _left_out(conn, alice["website_id"]) == 0

    def test_a_public_dashboard_sees_its_websites_setting(self, world):
        conn, made = world
        alice = made["alice"]

        _context(conn, "public", website_id=alice["website_id"])
        assert _counted(conn, alice["website_id"]) == 1

        _switch_off(conn, alice["website_id"])
        _context(conn, "public", website_id=alice["website_id"])
        assert _counted(conn, alice["website_id"]) == 2

    def test_the_scheduled_jobs_see_every_websites_setting(self, world):
        """Email reports and the hourly alert run in the job context."""
        conn, made = world
        _switch_off(conn, made["bob"]["website_id"])

        _context(conn, "job")
        assert _counted(conn, made["alice"]["website_id"]) == 1
        assert _counted(conn, made["bob"]["website_id"]) == 2

    def test_one_tenants_setting_does_not_reach_anothers_rows(self, world):
        """Bob counts his crawlers. Alice, asking about Bob's website, still
        gets nothing, and her own are still left out."""
        conn, made = world
        _switch_off(conn, made["bob"]["website_id"])

        _context(conn, "user", user_email=made["alice"]["email"])
        assert _counted(conn, made["bob"]["website_id"]) == 0
        assert _counted(conn, made["alice"]["website_id"]) == 1

    def test_where_the_setting_cannot_be_read_labelled_rows_stay_out(self, world):
        """Failing closed, shown on the expression itself: with a website id
        that has no row, a labelled pageview is not counted and is reported
        as left out."""
        conn, made = world
        _context(conn, "job")
        wid = made["alice"]["website_id"]

        counted_anyway = conn.execute(
            select(func.count()).select_from(Pageview).where(
                Pageview.website_id == wid, counted(-1)
            )
        ).scalar()
        left = conn.execute(
            select(func.count()).select_from(Pageview).where(
                Pageview.website_id == wid, left_out(-1)
            )
        ).scalar()

        assert (counted_anyway, left) == (1, 1)
