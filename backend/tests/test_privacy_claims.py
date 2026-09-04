"""The privacy properties the policy promises, tested as promises.

privacy.html tells visitors, in writing, that the visitor hash rotates daily,
that IP addresses are truncated before hashing, and that a hash on one site
cannot be matched to the same person on another. Those are not internal
implementation details. They are the argument for why this is analytics that
does not identify people, and a customer relies on them when they decide the
product is lawful to install.

A change that quietly broke any of them would make a published legal document
false, and nothing would fail. So each one is checked here, against the
sentence it corresponds to.
"""
import datetime as datetime_module
from unittest.mock import patch

from app.utils.security import generate_visitor_hash

UA = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"


class _FrozenDatetime(datetime_module.datetime):
    """A clock the hash function will read, since it calls datetime.now()."""

    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


def _hash_on(year, month, day, ip="192.168.1.10", domain="example.com"):
    _FrozenDatetime._now = datetime_module.datetime(
        year, month, day, 12, 0, tzinfo=datetime_module.timezone.utc
    )
    with patch("datetime.datetime", _FrozenDatetime):
        return generate_visitor_hash(ip, UA, domain)


class TestDailyRotation:
    """"a hash that changes daily and is not linked to a person" """

    def test_the_same_visitor_hashes_differently_the_next_day(self):
        assert _hash_on(2026, 1, 1) != _hash_on(2026, 1, 2), (
            "the visitor hash does not rotate, so a visitor is trackable "
            "across days and the privacy policy says otherwise"
        )

    def test_it_is_stable_within_a_day(self):
        """Without this, a returning visitor counts as a new one every hit."""
        assert _hash_on(2026, 1, 1) == _hash_on(2026, 1, 1)


class TestIpTruncation:
    """"IP truncation (/24): impossible to identify individual in shared network" """

    def test_addresses_in_one_subnet_share_a_hash(self):
        assert _hash_on(2026, 1, 1, ip="192.168.1.10") == _hash_on(
            2026, 1, 1, ip="192.168.1.250"
        ), "the last octet still reaches the hash, so the address is not truncated"

    def test_different_subnets_do_not(self):
        assert _hash_on(2026, 1, 1, ip="192.168.1.10") != _hash_on(
            2026, 1, 1, ip="192.168.2.10"
        )

    def test_ipv6_is_truncated_too(self):
        """A /48 prefix, which is the IPv6 equivalent and easy to forget."""
        assert _hash_on(
            2026, 1, 1, ip="2001:db8:1234:5678:9abc:def0:1234:5678"
        ) == _hash_on(2026, 1, 1, ip="2001:db8:1234:ffff:ffff:ffff:ffff:ffff")


class TestSiteScoping:
    """"Domain scoping: hashes are site-specific, no cross-site correlation" """

    def test_the_same_visitor_is_a_different_hash_on_another_site(self):
        assert _hash_on(2026, 1, 1, domain="example.com") != _hash_on(
            2026, 1, 1, domain="other.com"
        ), (
            "one visitor produces the same hash on two customers' sites, so "
            "the two customers could correlate a person between them"
        )


class TestNoRawAddress:
    def test_the_hash_does_not_contain_the_address_or_the_agent(self):
        """Obvious, and worth asserting because the failure is silent."""
        digest = _hash_on(2026, 1, 1, ip="192.168.1.10")

        assert "192.168" not in digest
        assert "Mozilla" not in digest
        assert len(digest) >= 32, f"a {len(digest)} character digest is too short"
