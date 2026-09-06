"""The IP-to-country table we build from the registries' own published data.

Country lookup used to need a file from a vendor. The registries publish the
allocations underneath those files themselves, daily and without an account,
so a self-hosted instance can have country statistics without signing up to
anything.

Two things in here can be wrong without anything appearing to break, and both
have most of the tests:

The IPv4 `value` column is a count of addresses, not a prefix length. Read it
as a prefix length and every range becomes a handful of addresses, almost
every lookup falls through to whatever range came before it, and the dashboard
fills with confident, wrong countries. Nothing raises.

The refresh replaces the whole table. A fetch that returns an error page
parses to nothing, and installing nothing is a successful refresh that turns
the whole world Unknown until somebody happens to wonder why. So it refuses,
and the tests for the refusal outnumber the tests for the parsing.
"""
import ipaddress

import pytest
from sqlalchemy import text

from app.services import ip_country_service as ic
from app.services.analytics_recording_service import _is_routable


def line(country="SE", kind="ipv4", start="2.0.0.0", value="131072",
         status="allocated", registry="ripencc"):
    return f"{registry}|{country}|{kind}|{start}|{value}|20100712|{status}|opaque-id"


class TestParsingTheDelegatedFormat:
    def test_the_ipv4_value_is_a_count_not_a_prefix_length(self):
        """The single most expensive thing to get wrong here.

        131072 addresses starting at 2.0.0.0 ends at 2.1.255.255. Read as a
        prefix length it would be nonsense, and nothing would raise: the table
        would just be full of tiny ranges and every lookup between them would
        return whichever range happened to start before the address.
        """
        ranges = list(ic.parse_delegated([line()], "ripencc"))

        assert ranges == [("2.0.0.0", "2.1.255.255", "SE")]

    def test_a_count_that_is_not_a_power_of_two(self):
        """Which is why these are ranges and not networks.

        A record like this cannot be expressed as one CIDR block, so a parser
        that produced networks would have to split it or drop it.
        """
        ranges = list(ic.parse_delegated(
            [line(start="10.0.0.0", value="1536")], "arin"
        ))

        start, end, _country = ranges[0]
        assert start == "10.0.0.0"
        assert end == "10.0.5.255"
        assert int(ipaddress.IPv4Address(end)) - int(ipaddress.IPv4Address(start)) + 1 == 1536

    def test_a_single_address(self):
        ranges = list(ic.parse_delegated([line(start="9.9.9.9", value="1")], "arin"))
        assert ranges == [("9.9.9.9", "9.9.9.9", "SE")]

    def test_on_an_ipv6_line_the_same_column_is_a_prefix_length(self):
        """Same position in the record, different meaning entirely."""
        ranges = list(ic.parse_delegated(
            [line(kind="ipv6", start="2a00:1450::", value="32")], "ripencc"
        ))

        assert ranges == [
            ("2a00:1450::", "2a00:1450:ffff:ffff:ffff:ffff:ffff:ffff", "SE")
        ]

    @pytest.mark.parametrize("skipped,why", [
        ("# comment", "comments"),
        ("", "blank lines"),
        ("2|ripencc|1788645599|260446|19700101|20260905|+0200", "the version header"),
        ("ripencc|*|ipv4|*|100672|summary", "summary lines"),
        (line(kind="asn", start="1234", value="1"), "AS number records"),
        (line(status="reserved"), "reserved space"),
        (line(status="available"), "unallocated space"),
        (line(country="ZZ"), "the registries' own unknown marker"),
        (line(country="X"), "codes that are not two letters"),
        (line(country="12"), "codes that are not letters"),
        (line(value="0"), "empty ranges"),
        (line(start="not-an-address"), "unparseable addresses"),
    ])
    def test_what_it_leaves_out(self, skipped, why):
        assert list(ic.parse_delegated([skipped], "ripencc")) == [], (
            f"{why} should not become a range"
        )

    def test_assigned_counts_as_held_as_well_as_allocated(self):
        """Both mean an organisation in that country has it.

        Dropping "assigned" would silently lose a fifth of the records, which
        would look like patchy coverage rather than a bug.
        """
        ranges = list(ic.parse_delegated([line(status="assigned")], "ripencc"))
        assert len(ranges) == 1

    def test_the_country_is_upper_cased(self):
        ranges = list(ic.parse_delegated([line(country="se")], "ripencc"))
        assert ranges[0][2] == "SE"

    def test_a_real_shaped_file(self):
        """A handful of records in the shape the registries actually publish."""
        sample = [
            "2|ripencc|1788645599|260446|19700101|20260905|+0200",
            "ripencc|*|ipv4|*|100672|summary",
            "ripencc|SE|ipv4|2.0.0.0|131072|20100712|allocated|8845474d",
            "ripencc|FR|ipv4|2.3.0.0|65536|20100712|allocated|3fb1a207",
            "ripencc|EU|ipv4|2.16.0.0|524288|20100910|allocated|1faabfb2",
            "ripencc|ZZ|ipv4|5.0.0.0|1024|20100910|reserved|",
            "ripencc|SE|ipv6|2a02:100::|32|20100712|assigned|8845474d",
        ]

        ranges = list(ic.parse_delegated(sample, "ripencc"))

        assert [r[2] for r in ranges] == ["SE", "FR", "EU", "SE"]


class TestTheRefreshRefusesRatherThanInstallingNonsense:
    """The check that matters more than the parser.

    Every failure mode here ends with a table full of the wrong thing and no
    error anywhere, which is the shape of bug this codebase keeps producing.
    """

    @pytest.fixture
    def seeded(self, db):
        """One range already in the table, to prove a refusal leaves it."""
        db.execute(
            text(
                "INSERT INTO ip_country_ranges (start_ip, end_ip, country, registry) "
                "VALUES ('2.0.0.0', '2.1.255.255', 'SE', 'ripencc')"
            )
        )
        db.commit()
        return db

    @staticmethod
    def _fetch_returning(lines):
        return lambda url, timeout=None: lines

    def test_it_refuses_a_result_that_is_too_small(self, seeded):
        with pytest.raises(RuntimeError, match="Refusing to install"):
            ic.refresh(
                seeded,
                fetch=self._fetch_returning([line()]),
                sources={"ripencc": "http://example.invalid/ripencc"},
            )

    def test_a_refusal_leaves_the_existing_table_alone(self, seeded):
        """The table has to survive a bad refresh, or a transient outage
        costs a week of country data rather than nothing.

        Counted before and after rather than against a fixed number: this runs
        against a database that may already have a real table loaded, and a
        test that only passes on an empty one would start failing for a reason
        that has nothing to do with the refresh.
        """
        before = seeded.execute(
            text("SELECT count(*) FROM ip_country_ranges")
        ).scalar()

        with pytest.raises(RuntimeError):
            ic.refresh(
                seeded,
                fetch=self._fetch_returning([line()]),
                sources={"ripencc": "http://example.invalid/ripencc"},
            )

        after = seeded.execute(
            text("SELECT count(*) FROM ip_country_ranges")
        ).scalar()
        assert after == before, "a refused refresh deleted rows anyway"
        assert before >= 1, "the fixture row is missing, so this proves nothing"

    def test_an_error_page_parses_to_nothing_and_is_refused(self, seeded):
        """The realistic failure: a 200 that is not the file."""
        html = ["<!DOCTYPE html>", "<html><body>503 Service Unavailable</body></html>"]

        with pytest.raises(RuntimeError, match="Refusing to install 0 ranges"):
            ic.refresh(
                seeded,
                fetch=self._fetch_returning(html),
                sources={"ripencc": "http://example.invalid/ripencc"},
            )

    def test_enough_rows_but_too_few_countries_is_also_refused(self, seeded, monkeypatch):
        """Rows alone do not mean the data is right.

        One registry answering and four failing can clear the row threshold
        while covering one continent. The country count is the check that
        notices.
        """
        monkeypatch.setattr(ic, "MINIMUM_ROWS", 10)
        many_swedish = [
            line(start=f"10.{n}.0.0", value="256") for n in range(20)
        ]

        with pytest.raises(RuntimeError, match="countries"):
            ic.refresh(
                seeded,
                fetch=self._fetch_returning(many_swedish),
                sources={"ripencc": "http://example.invalid/ripencc"},
            )

    def test_a_registry_that_cannot_be_reached_is_recorded_not_swallowed(
        self, db, monkeypatch
    ):
        """Four registries answering is not a success worth being quiet about."""
        monkeypatch.setattr(ic, "MINIMUM_ROWS", 2)
        monkeypatch.setattr(ic, "MINIMUM_COUNTRIES", 2)

        def fetch(url, timeout=None):
            if "broken" in url:
                raise OSError("connection refused")
            return [line(country="SE"), line(country="FR", start="3.0.0.0")]

        result = ic.refresh(
            db, fetch=fetch,
            sources={
                "ripencc": "http://example.invalid/ok",
                "arin": "http://example.invalid/broken",
            },
        )

        assert "arin" in result["failures"]
        assert "connection refused" in result["failures"]["arin"]
        assert result["ranges"] == 2

    def test_the_thresholds_are_high_enough_to_mean_something(self):
        """A guard set below what one registry publishes guards nothing.

        RIPE alone carries well over a hundred thousand ranges, so a threshold
        of, say, a thousand would pass on a table missing four continents.
        """
        assert ic.MINIMUM_ROWS >= 50_000
        assert ic.MINIMUM_COUNTRIES >= 100


class TestTheRefreshReplacesTheTable:
    @pytest.fixture
    def small(self, monkeypatch):
        monkeypatch.setattr(ic, "MINIMUM_ROWS", 2)
        monkeypatch.setattr(ic, "MINIMUM_COUNTRIES", 2)

    def _load(self, db, lines):
        return ic.refresh(
            db,
            fetch=lambda url, timeout=None: lines,
            sources={"ripencc": "http://example.invalid/ripencc"},
        )

    def test_it_installs_what_it_parsed(self, db, small):
        result = self._load(db, [
            line(country="SE", start="2.0.0.0"),
            line(country="FR", start="3.0.0.0"),
        ])

        assert result["ranges"] == 2
        assert result["countries"] == 2
        assert db.execute(
            text("SELECT count(*) FROM ip_country_ranges")
        ).scalar() == 2

    def test_running_it_twice_replaces_rather_than_appends(self, db, small):
        """Otherwise the table doubles every week and old allocations linger,
        overlapping the new ones with no way to tell which is current."""
        lines = [line(country="SE", start="2.0.0.0"),
                 line(country="FR", start="3.0.0.0")]

        self._load(db, lines)
        self._load(db, lines)

        assert db.execute(
            text("SELECT count(*) FROM ip_country_ranges")
        ).scalar() == 2

    def test_it_records_which_registry_each_range_came_from(self, db, small):
        self._load(db, [line(country="SE"), line(country="FR", start="3.0.0.0")])

        registries = db.execute(
            text("SELECT DISTINCT registry FROM ip_country_ranges")
        ).scalars().all()
        assert registries == ["ripencc"]


class TestLookingUpAnAddress:
    @pytest.fixture
    def loaded(self, db, monkeypatch):
        monkeypatch.setattr(ic, "MINIMUM_ROWS", 2)
        monkeypatch.setattr(ic, "MINIMUM_COUNTRIES", 2)
        ic.refresh(
            db,
            fetch=lambda url, timeout=None: [
                "ripencc|SE|ipv4|2.0.0.0|131072|20100712|allocated|x",
                "ripencc|FR|ipv4|3.0.0.0|65536|20100712|allocated|x",
                "ripencc|SE|ipv6|2a02:100::|32|20100712|allocated|x",
            ],
            sources={"ripencc": "http://example.invalid/ripencc"},
        )
        return db

    @pytest.mark.parametrize("address,expected", [
        ("2.0.0.0", "SE"),          # the first address of the range
        ("2.0.55.9", "SE"),
        ("2.1.255.255", "SE"),      # the last address of the range
        ("3.0.0.0", "FR"),
        ("3.0.255.255", "FR"),
    ])
    def test_addresses_inside_a_range(self, loaded, address, expected):
        assert ic.lookup(loaded, address) == expected

    @pytest.mark.parametrize("address", ["1.255.255.255", "2.2.0.0", "3.1.0.0"])
    def test_addresses_outside_every_range(self, loaded, address):
        """The boundary in the direction that matters.

        2.2.0.0 is one past the end of the Swedish range. A lookup that only
        checked start_ip would return SE for it, and for every unallocated
        address after it, all the way to the next range.
        """
        assert ic.lookup(loaded, address) is None

    def test_ipv6(self, loaded):
        assert ic.lookup(loaded, "2a02:100::1") == "SE"

    def test_an_ipv6_address_does_not_match_an_ipv4_range(self, loaded):
        assert ic.lookup(loaded, "2a03:100::1") is None

    def test_nonsense_is_none_rather_than_an_exception(self, loaded):
        """It is reached from the tracking endpoint, where a bad X-Forwarded-For
        must not become a 500 on somebody's website."""
        assert ic.lookup(loaded, "not-an-address") is None
        assert ic.lookup(loaded, "") is None

    def test_it_goes_through_the_security_definer_function(self):
        """Not a direct read of the table.

        The caller is the tracking context, which has no SELECT policy on
        anything on purpose: a tracking code is public in every customer's
        page source. Giving it a read so it could resolve a country would be
        the first read it has ever had, and the precedent for the next one.
        """
        import inspect

        source = inspect.getsource(ic.lookup)
        assert "argus_country_for_ip" in source
        assert "FROM ip_country_ranges" not in source


class TestIsPopulated:
    def test_false_when_the_table_is_empty(self, db):
        db.execute(text("DELETE FROM ip_country_ranges"))
        db.commit()
        assert ic.is_populated(db) is False

    def test_true_once_there_is_anything(self, db):
        db.execute(
            text(
                "INSERT INTO ip_country_ranges (start_ip, end_ip, country, registry) "
                "VALUES ('2.0.0.0', '2.1.255.255', 'SE', 'ripencc')"
            )
        )
        db.commit()
        assert ic.is_populated(db) is True

    def test_it_also_goes_through_a_function(self):
        """Development connects as the table owner, where policies are inert.

        A plain SELECT here would answer truthfully in development and always
        answer "no" in production, and the difference would show up as an
        empty-state message that only ever appeared on the live site.
        """
        import inspect

        assert "argus_country_data_loaded" in inspect.getsource(ic.is_populated)


class TestWhichAddressesAreWorthLookingUp:
    """The private-address check, which used to be string prefixes."""

    @pytest.mark.parametrize("address", [
        "172.17.0.5",       # Docker's default bridge
        "172.16.0.5",
        "172.31.255.254",
        "10.0.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "::1",
        "169.254.1.1",      # link-local
        "fe80::1",
        "0.0.0.0",
        "224.0.0.1",        # multicast
        "not-an-address",
        "",
    ])
    def test_addresses_that_are_not_worth_a_lookup(self, address):
        assert _is_routable(address) is False

    def test_the_docker_bridge_specifically(self):
        """The one the old check missed.

        It tested the literal prefix '172.16.', which is one sixteenth of the
        private 172.16.0.0/12 block. Docker's default bridge is 172.17.0.0/16,
        so container addresses went off to be geolocated.
        """
        assert _is_routable("172.17.0.2") is False

    @pytest.mark.parametrize("address", [
        "8.8.8.8", "81.224.1.1", "2a00:1450:4001::1", "1.1.1.1",
    ])
    def test_public_addresses_are_looked_up(self, address):
        assert _is_routable(address) is True


class TestTheSourcesAreTheFiveRegistries:
    def test_all_five(self):
        assert set(ic.RIR_SOURCES) == {
            "afrinic", "apnic", "arin", "lacnic", "ripencc"
        }

    def test_every_source_is_https(self):
        """These are fetched by the server on a schedule. Plain http would let
        anyone on the path decide which country your visitors are in."""
        for registry, url in ic.RIR_SOURCES.items():
            assert url.startswith("https://"), f"{registry} is not over https"


class TestTheRecordingPathActuallyUsesIt:
    """The wiring, which is the part that has been missing before.

    A table full of correct ranges and a lookup that nothing calls is the
    failure this project keeps producing: complete underneath, absent on the
    screen. So this goes through the method the tracking endpoint calls.
    """

    @pytest.fixture
    def service(self, db, monkeypatch):
        from app.config import settings
        from app.services.analytics_recording_service import AnalyticsRecordingService

        # No mmdb configured, so the table is the source under test.
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", None)
        # Only these two ranges exist for the length of the test. Without the
        # delete, a machine with the real table loaded resolves every address
        # to something, and "an address in no range" has no address to use.
        # The db fixture rolls the whole thing back afterwards.
        db.execute(text("DELETE FROM ip_country_ranges"))
        db.execute(
            text(
                "INSERT INTO ip_country_ranges (start_ip, end_ip, country, registry) "
                "VALUES ('81.224.0.0', '81.224.255.255', 'SE', 'ripencc'), "
                "       ('8.8.8.0', '8.8.8.255', 'US', 'arin')"
            )
        )
        db.commit()
        return AnalyticsRecordingService(db)

    def test_a_public_address_resolves_from_the_table(self, service):
        assert service._get_country_from_ip("81.224.1.1") == "SE"
        assert service._get_country_from_ip("8.8.8.8") == "US"

    def test_an_address_in_no_range_is_unknown(self, service):
        assert service._get_country_from_ip("9.9.9.9") is None

    def test_a_container_address_is_not_looked_up(self, service):
        assert service._get_country_from_ip("172.17.0.4") is None

    def test_a_configured_mmdb_takes_precedence(self, service, monkeypatch, tmp_path):
        """An operator who put a file there chose it deliberately.

        The file here is not a real database, so the reader fails to open it
        and the lookup falls through. What matters is that the table is not
        consulted first and silently preferred over the operator's choice.
        """
        from app.config import settings
        from app.services import analytics_recording_service as ars

        fake = tmp_path / "country.mmdb"
        fake.write_bytes(b"not a database")
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(fake))
        monkeypatch.setattr(ars, "_MMDB_CACHE", {})

        called = []
        monkeypatch.setattr(
            ic, "lookup", lambda db, ip: called.append(ip) or "XX"
        )

        service._get_country_from_ip("81.224.1.1")

        assert called == ["81.224.1.1"], (
            "an unopenable file should fall through to the table, not silently "
            "return no country at all"
        )


class TestWhatTheDashboardIsToldAboutAvailability:
    """The template global answers for both sources, so both have to reach it.

    This lives here rather than beside the other empty-state tests because it
    needs a database it can empty, and a test that asserts "no country data"
    while the real table is loaded would fail on a working machine.
    """

    @pytest.fixture
    def available(self, db, monkeypatch):
        from app.config import settings
        from app.routers.dashboard import _country_lookup_available

        monkeypatch.setattr(settings, "GEOIP_DB_PATH", None)
        return _country_lookup_available

    def test_false_when_there_is_no_file_and_no_table(self, db, available, monkeypatch):
        """The state a fresh instance is in, and the one the honest empty
        state exists for."""
        from app.services import ip_country_service

        monkeypatch.setattr(ip_country_service, "is_populated", lambda session: False)
        assert available() is False

    def test_true_once_the_table_has_been_loaded(self, db, available, monkeypatch):
        from app.services import ip_country_service

        monkeypatch.setattr(ip_country_service, "is_populated", lambda session: True)
        assert available() is True

    def test_a_configured_file_answers_without_touching_the_database(
        self, available, monkeypatch, tmp_path
    ):
        """An operator with an mmdb should not pay a query per dashboard render."""
        from app.config import settings
        from app.services import ip_country_service

        mmdb = tmp_path / "country.mmdb"
        mmdb.write_bytes(b"x")
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(mmdb))

        def refuse(session):
            raise AssertionError("the table was consulted despite a configured file")

        monkeypatch.setattr(ip_country_service, "is_populated", refuse)
        assert available() is True
