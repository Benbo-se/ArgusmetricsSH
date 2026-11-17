"""The table of hosting-provider address ranges, and the lookup into it (#103).

Three things here can be wrong without anything appearing to break:

The refresh replaces the whole table. A download that is an error page parses
to nothing, and installing nothing is a refresh that succeeds: every crawler is
a visitor again and the dashboard shows a good week. So it refuses, and most
of the tests are about the refusal.

The lookup takes the one range starting at or before an address and asks
whether it reaches. An off-by-one at either end labels a neighbour, and the
neighbour of a hosting block is as likely as not somebody's broadband.

The list decides who is left out. A consumer network on it hides real people,
which is why Cloudflare, Akamai, Fastly, Google's main network and Apple are
written down as never to be added, and a test holds the two lists apart.

Nothing here touches the network. The file is tests/fixtures/ip2asn-sample.tsv,
fifteen ranges in the format iptoasn.com publishes and one line of rubbish.
"""
import gzip
import inspect
import pathlib

import pytest
from sqlalchemy import text

from app import hosting_asns
from app.services import hosting_networks_service as hn

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ip2asn-sample.tsv"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing in this file may fetch. A test that reaches for the real file
    by mistake fails here, at once, and does not wait on iptoasn.com."""
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a URL")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def fixture_lines():
    return FIXTURE.read_text().splitlines()


def fetch_fixture(source, timeout=None):
    return fixture_lines()


def ranges_in(db):
    return [
        (r.start_ip, r.end_ip)
        for r in db.execute(
            text(
                "SELECT host(r.start_ip) AS start_ip, host(r.end_ip) AS end_ip "
                "FROM hosting_network_ranges r ORDER BY r.start_ip"
            )
        )
    ]


@pytest.fixture
def small_file_allowed(monkeypatch):
    """Let a sixteen-line file through, for the tests that are not about the
    floor. The floor has tests of its own, with these at their real values."""
    monkeypatch.setattr(hn, "MINIMUM_FILE_ROWS", 10)
    monkeypatch.setattr(hn, "MINIMUM_RANGES", 5)
    monkeypatch.setattr(hn, "MINIMUM_SHARE_OF_LIST", 0.05)


@pytest.fixture
def loaded(db, small_file_allowed):
    """The table as the fixture file makes it. Whatever was there is replaced,
    inside the test's transaction."""
    hn.refresh(db, fetch=fetch_fixture)
    return db


class TestTheList:
    def test_nothing_is_both_listed_and_ruled_out(self):
        both = set(hosting_asns.HOSTING_ASNS) & set(hosting_asns.NEVER_LISTED)
        assert not both, (
            f"{sorted(both)} are on the list and on the list of networks never "
            "to add. Real people browse from behind those: read the reasons "
            "at the top of app/hosting_asns.py before changing either."
        )

    @pytest.mark.parametrize("asn", [13335, 20940, 36183, 54113, 15169])
    def test_the_networks_real_people_sit_behind_are_not_listed(self, asn):
        assert asn not in hosting_asns.HOSTING_ASNS

    def test_every_entry_is_a_number_with_a_name(self):
        for asn, name in hosting_asns.HOSTING_ASNS.items():
            assert isinstance(asn, int) and asn > 0
            assert isinstance(name, str) and name.strip()


class TestParsingTheFile:
    def test_a_row_becomes_a_family_two_integers_and_a_number(self):
        rows = list(hn.parse_ip2asn(["3.0.0.0\t3.0.255.255\t16509\tUS\tAMAZON-02"]))
        assert rows == [(4, 0x03000000, 0x0300FFFF, 16509)]

    def test_ipv6_is_in_the_same_file(self):
        rows = list(hn.parse_ip2asn(["2a01:4f8::\t2a01:4f8:ffff:ffff:ffff:ffff:ffff:ffff\t24940\tDE\tHETZNER"]))
        assert rows[0][0] == 6 and rows[0][3] == 24940

    @pytest.mark.parametrize("skipped,why", [
        ("", "blank lines"),
        ("<html><body>503 Service Unavailable</body></html>", "an error page"),
        ("3.0.0.0 3.0.255.255 16509 US AMAZON-02", "spaces where the tabs should be"),
        ("3.0.0.0\t3.0.255.255", "a row cut short"),
        ("not-an-address\t3.0.255.255\t16509\tUS\tX", "an unparseable start"),
        ("3.0.0.0\t3.0.255.255\tAS16509\tUS\tX", "an AS number that is not a number"),
        ("3.0.255.255\t3.0.0.0\t16509\tUS\tX", "a range that ends before it starts"),
        ("3.0.0.0\t2a01:4f8::\t16509\tUS\tX", "a range across two address families"),
    ])
    def test_what_it_leaves_out(self, skipped, why):
        assert list(hn.parse_ip2asn([skipped])) == [], f"{why} should not become a range"

    def test_the_fixture_has_fifteen_ranges_and_one_line_of_rubbish(self):
        assert len(fixture_lines()) == 16
        assert len(list(hn.parse_ip2asn(fixture_lines()))) == 15


class TestFetching:
    """The download itself, against a stand-in for the socket."""

    @staticmethod
    def _serving(monkeypatch, body, asked=None):
        import io
        import urllib.request

        def urlopen(request, timeout=None):
            if asked is not None:
                asked.append((request.full_url, timeout))
            return io.BytesIO(body)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    def test_it_unpacks_what_is_published(self, monkeypatch):
        asked = []
        self._serving(monkeypatch, gzip.compress(FIXTURE.read_bytes()), asked)

        lines = list(hn.fetch_ip2asn())

        assert len(lines) == 16
        assert lines[0].startswith("1.0.0.0\t1.0.0.255\t13335")
        assert asked == [(hn.SOURCE_URL, 120)], "one request, with a timeout"

    def test_a_body_that_was_never_gzipped_is_read_as_it_is(self, monkeypatch):
        """An error page arrives as plain text. It must reach the parser and
        be refused there for what it is, not die here as a broken archive."""
        self._serving(monkeypatch, b"<html><body>503</body></html>\n")

        assert list(hn.fetch_ip2asn()) == ["<html><body>503</body></html>\n"]

    def test_a_download_that_is_far_too_large_is_refused(self, monkeypatch):
        monkeypatch.setattr(hn, "MAXIMUM_BYTES", 100)
        self._serving(monkeypatch, gzip.compress(FIXTURE.read_bytes()))

        with pytest.raises(RuntimeError, match="larger than 100 bytes"):
            hn.fetch_ip2asn()


class TestMerging:
    def test_neighbours_become_one_range(self):
        assert hn.merge([(4, 10, 19), (4, 20, 29)]) == [(4, 10, 29)]

    def test_a_gap_of_one_address_keeps_them_apart(self):
        assert hn.merge([(4, 10, 19), (4, 21, 29)]) == [(4, 10, 19), (4, 21, 29)]

    def test_a_range_inside_another_disappears_into_it(self):
        """The lookup is only right when no range sits inside another."""
        assert hn.merge([(4, 10, 99), (4, 20, 29)]) == [(4, 10, 99)]

    def test_the_two_families_never_merge(self):
        assert hn.merge([(6, 0, 9), (4, 0, 9)]) == [(4, 0, 9), (6, 0, 9)]


class TestARefreshKeepsOnlyTheListedNetworks:
    def test_it_installs_the_listed_ranges_and_nothing_else(self, loaded):
        """Amazon (two neighbours and a third network, merged into one),
        Hetzner, Google Cloud, and their IPv6. Not Telia, not Cloudflare, not
        Apple, not the unrouted block."""
        assert ranges_in(loaded) == [
            ("3.0.0.0", "3.2.0.255"),
            ("5.9.0.0", "5.9.255.255"),
            ("34.64.0.0", "34.64.255.255"),
            ("2600:1f00::", "2600:1fff:ffff:ffff:ffff:ffff:ffff:ffff"),
            ("2a01:4f8::", "2a01:4f9:ffff:ffff:ffff:ffff:ffff:ffff"),
        ]

    def test_it_reports_what_it_did(self, db, small_file_allowed):
        result = hn.refresh(db, fetch=fetch_fixture)

        assert result["file_rows"] == 15
        assert result["listed_rows"] == 8
        assert result["ranges"] == 5
        assert result["networks"] == 4  # 16509, 14618, 24940, 396982
        assert 14061 in result["missing"], "a listed network absent from the file is named"

    def test_it_replaces_the_table_and_does_not_add_to_it(self, loaded):
        hn.refresh(loaded, fetch=fetch_fixture)
        assert len(ranges_in(loaded)) == 5

    def test_asking_for_the_real_file_by_default(self):
        assert hn.SOURCE_URL == "https://iptoasn.com/data/ip2asn-combined.tsv.gz"
        assert inspect.signature(hn.refresh).parameters["fetch"].default is hn.fetch_ip2asn


class TestTheRefreshRefusesRatherThanInstallingNonsense:
    """With the floor at its real values, which is what production runs."""

    @pytest.fixture
    def seeded(self, db):
        """One range already in the table, to prove a refusal leaves it."""
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.execute(
            text(
                "INSERT INTO hosting_network_ranges (start_ip, end_ip) "
                "VALUES ('5.9.0.0', '5.9.255.255')"
            )
        )
        db.commit()
        return db

    def test_a_file_that_is_too_small_is_refused(self, seeded):
        with pytest.raises(RuntimeError, match="Refusing to install"):
            hn.refresh(seeded, fetch=fetch_fixture)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")], (
            "a refused refresh changed the table anyway"
        )

    def test_an_error_page_is_refused(self, seeded):
        """The realistic failure: a 200 that is not the file."""
        html = ["<!DOCTYPE html>", "<html><body>503 Service Unavailable</body></html>"]

        with pytest.raises(RuntimeError, match="Refusing to install 0 ranges"):
            hn.refresh(seeded, fetch=lambda source, timeout=None: html)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")]

    def test_a_fetch_that_fails_leaves_the_table_alone(self, seeded):
        def fetch(source, timeout=None):
            raise OSError("connection refused")

        with pytest.raises(OSError):
            hn.refresh(seeded, fetch=fetch)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")]

    def test_enough_rows_but_too_few_listed_ranges_is_refused(self, seeded, monkeypatch):
        """A whole file with the wrong things in it. Half a download does
        this: the file is sorted by address, so its first half has plenty of
        rows and is missing most of every provider."""
        monkeypatch.setattr(hn, "MINIMUM_FILE_ROWS", 10)

        with pytest.raises(RuntimeError, match="expected at least 10000 ranges"):
            hn.refresh(seeded, fetch=fetch_fixture)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")]

    def test_enough_ranges_from_too_few_networks_is_refused(self, seeded, monkeypatch):
        """Rows alone do not mean the list was matched. One provider's ranges
        can clear the count while fifty providers are missing, which is a
        file whose AS numbers no longer mean what the list thinks."""
        monkeypatch.setattr(hn, "MINIMUM_FILE_ROWS", 10)
        monkeypatch.setattr(hn, "MINIMUM_RANGES", 5)

        with pytest.raises(RuntimeError, match="from 4 of"):
            hn.refresh(seeded, fetch=fetch_fixture)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")]

    def test_a_file_that_never_ends_is_refused(self, seeded, monkeypatch):
        monkeypatch.setattr(hn, "MAXIMUM_FILE_ROWS", 10)

        with pytest.raises(RuntimeError, match="Refusing to read past"):
            hn.refresh(seeded, fetch=fetch_fixture)

        assert ranges_in(seeded) == [("5.9.0.0", "5.9.255.255")]

    def test_the_floor_is_where_the_real_file_clears_it_and_a_stub_does_not(self):
        """Measured against the real file on 2026-11-17: 719,149 rows, 26,114
        of them on the list, all 54 listed networks present."""
        assert 100_000 <= hn.MINIMUM_FILE_ROWS <= 600_000
        assert 5_000 <= hn.MINIMUM_RANGES <= 20_000
        assert 0.5 <= hn.MINIMUM_SHARE_OF_LIST <= 0.9


class TestLookup:
    @pytest.mark.parametrize("address", [
        "3.0.0.0",          # the first address of a range
        "3.0.0.1",
        "3.1.44.7",         # in the second of two merged neighbours
        "3.2.0.255",        # the last address of a range
        "5.9.255.255",
        "34.64.12.1",
        "2600:1f00::",                              # IPv6, first address
        "2600:1f18:4a2::17",
        "2a01:4f9:ffff:ffff:ffff:ffff:ffff:ffff",   # IPv6, last address
    ])
    def test_an_address_in_a_listed_range_is_datacenter(self, loaded, address):
        assert hn.lookup(loaded, address) == "datacenter"

    @pytest.mark.parametrize("address", [
        "2.255.255.255",    # one before a range begins, and Telia's
        "3.2.1.0",          # one after a range ends
        "5.8.255.255",
        "5.10.0.0",         # Telia again, right after Hetzner
        "1.0.0.1",          # Cloudflare, deliberately not listed
        "17.5.6.7",         # Apple, deliberately not listed
        "104.16.0.1",       # Cloudflare
        "81.224.1.1",       # nothing near it in the table
        "0.0.0.1",          # below every range
        "255.255.255.254",  # above every IPv4 range, below every IPv6 one
        "2600:1eff:ffff:ffff:ffff:ffff:ffff:ffff",  # one before
        "2600:2000::",                              # one after
        "2a00:801::1",                              # Telia's IPv6
        "2a01:4fa::",                               # one after Hetzner's
        "::1",
    ])
    def test_an_address_outside_is_not(self, loaded, address):
        assert hn.lookup(loaded, address) is None

    def test_an_ipv4_address_written_as_ipv6_is_the_ipv4_address(self, loaded):
        assert hn.lookup(loaded, "::ffff:5.9.1.1") == "datacenter"
        assert hn.lookup(loaded, "::ffff:5.10.0.0") is None

    def test_nonsense_is_none_and_does_not_break_the_transaction(self, loaded):
        """It is reached from the tracking endpoint, where a bad
        X-Forwarded-For must not cost the pageview written right after it."""
        assert hn.lookup(loaded, "not-an-address") is None
        assert hn.lookup(loaded, "") is None
        assert hn.lookup(loaded, "5.9.1.1/24") is None
        assert loaded.execute(text("SELECT 1")).scalar() == 1

    def test_an_empty_table_classifies_nothing(self, db):
        """An instance that never loaded the file behaves as it always did."""
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.commit()

        assert hn.lookup(db, "5.9.1.1") is None
        assert hn.lookup(db, "2a01:4f8::1") is None

    def test_it_goes_through_the_security_definer_function(self):
        """Not a direct read of the table. The caller is the tracking
        context, which has no SELECT policy on anything on purpose."""
        source = inspect.getsource(hn.lookup)
        assert "argus_traffic_class_for_ip" in source
        assert "FROM hosting_network_ranges" not in source

    def test_a_miss_costs_one_step_in_the_index_not_a_walk_through_it(self, loaded):
        """Nearly every lookup is a miss: an ordinary visitor. The obvious
        query, filtering on the end while walking backwards, reads every
        range below the address before giving up."""
        definition = loaded.execute(
            text("SELECT pg_get_functiondef('argus_traffic_class_for_ip(inet)'::regprocedure)")
        ).scalar()
        inner = definition.split("FROM hosting_network_ranges", 1)[1].split("LIMIT 1", 1)[0]
        assert "end_ip" not in inner, (
            "the range is chosen by its start alone and compared with its end "
            "afterwards; filtering on end_ip inside the scan makes a miss "
            "read the whole table"
        )


class TestTheCommandLine:
    @pytest.fixture
    def cli(self, db, monkeypatch, small_file_allowed):
        """The module's main(), on the test's session so nothing is left."""
        from app import hosting_networks

        class Borrowed:
            def __getattr__(self, name):
                return getattr(db, name)

            def close(self):
                pass

        monkeypatch.setattr(hosting_networks, "_session", lambda: Borrowed())
        return hosting_networks.main

    def test_refresh_from_a_file(self, cli, db):
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.commit()

        assert cli(["refresh", "--from-file", str(FIXTURE)]) == 0
        assert len(ranges_in(db)) == 5

    def test_refresh_from_a_gzipped_file_as_it_is_published(self, cli, db, tmp_path):
        packed = tmp_path / "ip2asn-combined.tsv.gz"
        packed.write_bytes(gzip.compress(FIXTURE.read_bytes()))
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.commit()

        assert cli(["refresh", "--from-file", str(packed)]) == 0
        assert len(ranges_in(db)) == 5

    def test_a_file_that_is_not_there_fails_and_changes_nothing(self, cli, db, tmp_path):
        cli(["refresh", "--from-file", str(FIXTURE)])

        assert cli(["refresh", "--from-file", str(tmp_path / "missing.tsv")]) == 1
        assert len(ranges_in(db)) == 5

    def test_a_refused_file_exits_non_zero_and_changes_nothing(self, cli, db, tmp_path, monkeypatch):
        cli(["refresh", "--from-file", str(FIXTURE)])
        stub = tmp_path / "stub.tsv"
        stub.write_text("3.0.0.0\t3.0.255.255\t16509\tUS\tAMAZON-02\n")
        monkeypatch.setattr(hn, "MINIMUM_FILE_ROWS", 300_000)

        assert cli(["refresh", "--from-file", str(stub)]) == 1
        assert len(ranges_in(db)) == 5

    def test_refresh_without_a_file_fetches_the_published_one(self, cli, db, monkeypatch):
        asked = []

        def fetch(source, timeout=None):
            asked.append(source)
            return fixture_lines()

        monkeypatch.setattr(hn, "fetch_ip2asn", fetch)

        assert cli(["refresh"]) == 0
        assert asked == [hn.SOURCE_URL]

    def test_status_says_what_is_loaded(self, cli, db, caplog):
        cli(["refresh", "--from-file", str(FIXTURE)])

        with caplog.at_level("INFO", logger="hosting_networks"):
            assert cli(["status"]) == 0
        assert "5 ranges (3 IPv4, 2 IPv6)" in caplog.text

    def test_status_on_an_empty_table_says_how_to_fill_it(self, cli, db, caplog):
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.commit()

        with caplog.at_level("INFO", logger="hosting_networks"):
            assert cli(["status"]) == 1
        assert "python -m app.hosting_networks refresh" in caplog.text

    def test_lookup(self, cli, db, caplog):
        cli(["refresh", "--from-file", str(FIXTURE)])

        with caplog.at_level("INFO", logger="hosting_networks"):
            assert cli(["lookup", "5.9.1.1"]) == 0
            assert cli(["lookup", "81.224.1.1"]) == 1
        assert "5.9.1.1: datacenter" in caplog.text
        assert "81.224.1.1: not in a listed hosting network" in caplog.text


class TestTheWeeklyJob:
    def test_it_is_scheduled_with_a_lock_key_of_its_own(self):
        import re

        from app import scheduled_tasks

        source = inspect.getsource(scheduled_tasks)
        keys = re.findall(r"_single_runner\((\d[\d_]*),\s*\"(\w+)\"", source)
        assert ("918_271_005", "hosting_networks_refresh") in keys
        assert len({key for key, _name in keys}) == len(keys), (
            f"two jobs share an advisory-lock key, so one would skip whenever "
            f"the other was running: {keys}"
        )
        assert 'id="hosting_networks_refresh"' in source

    def test_switched_off_it_fetches_nothing(self, monkeypatch):
        from app import scheduled_tasks
        from app.config import settings

        def fail(*args, **kwargs):
            raise AssertionError("the job started although DATACENTER_FILTER is off")

        monkeypatch.setattr(settings, "DATACENTER_FILTER", False)
        monkeypatch.setattr(scheduled_tasks, "_single_runner", fail)
        monkeypatch.setattr(hn, "fetch_ip2asn", fail)

        scheduled_tasks.hosting_networks_refresh_task()

    def test_health_expects_it_only_where_it_runs(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "DATACENTER_FILTER", True)
        jobs = client.get("/health").json()["jobs"]
        assert jobs["hosting_networks_refresh"]["max_age_seconds"] == 16 * 24 * 3600
        assert set(jobs["hosting_networks_refresh"]) == set(jobs["daily_cleanup"])

        monkeypatch.setattr(settings, "DATACENTER_FILTER", False)
        assert "hosting_networks_refresh" not in client.get("/health").json()["jobs"]

    def test_a_refresh_that_stopped_succeeding_makes_the_instance_degraded(self, client, db, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "DATACENTER_FILTER", True)
        for job in ("daily_cleanup", "email_reports", "traffic_alerts"):
            db.execute(
                text(
                    "INSERT INTO job_runs (job_name, last_success_at) VALUES (:n, now()) "
                    "ON CONFLICT (job_name) DO UPDATE SET last_success_at = now()"
                ),
                {"n": job},
            )
        db.execute(
            text(
                "INSERT INTO job_runs (job_name, last_success_at, consecutive_failures, last_error) "
                "VALUES ('hosting_networks_refresh', now() - interval '20 days', 2, 'Refusing to install 0 ranges') "
                "ON CONFLICT (job_name) DO UPDATE SET last_success_at = EXCLUDED.last_success_at, "
                "  consecutive_failures = 2, last_error = EXCLUDED.last_error"
            )
        )
        db.commit()

        body = client.get("/health").json()

        assert body["stalled_jobs"] == ["hosting_networks_refresh"]
        assert body["status"] == "degraded"
        assert "Refusing to install" in body["jobs"]["hosting_networks_refresh"]["last_error"]
