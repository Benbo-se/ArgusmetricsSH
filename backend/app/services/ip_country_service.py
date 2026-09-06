"""Build the IP-to-country table from the registries' own published data.

Every commercial geolocation database starts here. The five Regional Internet
Registries publish, daily and without an account, exactly which address ranges
they have handed to organisations in which country:

    ripencc|SE|ipv4|81.224.0.0|262144|20010823|allocated|<opaque org id>

So a self-hosted instance can have country statistics without signing up to
anything or agreeing to a redistribution licence. That is the point of doing
it this way rather than shipping instructions to go and fetch a vendor file.

What it costs, stated plainly because the number on the dashboard will not say
it: this is where a block was *allocated*, not where it is used. A Telia or
Bahnhof range is Swedish and its customers are in Sweden. A range allocated to
a US company and announced from a Stockholm data centre reads US. Commercial
databases close that gap with BGP announcements, which we do not have. For
ordinary consumer traffic the two agree; for cloud, VPN and CDN traffic they
do not, and an operator who needs that accuracy should point GEOIP_DB_PATH at
an mmdb, which still takes precedence over this table.

The refresh fetches five public files. That is the server reading a published
dataset on a schedule; no visitor address is involved and nothing about your
traffic leaves the machine. It is the same promise as before, and the reason
the lookup itself never touches the network.
"""
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: The published allocation files, one per registry. Plain text over https,
#: no credentials. Each registry covers its own region and the five together
#: cover every allocated address.
RIR_SOURCES: Dict[str, str] = {
    "afrinic": "https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-extended-latest",
    "apnic": "https://ftp.apnic.net/pub/stats/apnic/delegated-apnic-extended-latest",
    "arin": "https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest",
    "lacnic": "https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest",
    "ripencc": "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest",
}

#: Only these two statuses mean an organisation in a named country holds the
#: range. "reserved" and "available" carry the registry's own placeholder.
HELD = ("allocated", "assigned")

#: Not a country. The registries use it where they do not know.
UNKNOWN_CODE = "ZZ"

#: Below this the file is not a file, it is an error page or half a download.
#: RIPE alone publishes about a hundred thousand IPv4 ranges, so a refresh
#: that produces a few thousand rows has gone wrong in a way that would
#: otherwise install itself silently and turn most countries to Unknown.
MINIMUM_ROWS = 50_000
MINIMUM_COUNTRIES = 100


def parse_delegated(lines: Iterable[str], registry: str) -> Iterator[Tuple[str, str, str]]:
    """Turn one delegated-extended file into (start, end, country) ranges.

    Two shapes hide in this format and getting either wrong is silent:

    The value on an ipv4 line is a *count of addresses*, not a prefix length.
    262144 is a /14. Reading it as a prefix length would put every Swedish
    range in a block the size of nothing and resolve almost every address to
    whatever came before it in the table.

    That count is also not guaranteed to be a power of two, so a record does
    not always correspond to one CIDR block, which is why this yields address
    ranges rather than networks.

    On an ipv6 line the same column *is* a prefix length. Same position,
    different meaning.
    """
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("|")
        if len(parts) < 7:
            continue

        _registry, country, kind, start, value, _date, status = parts[:7]

        if status not in HELD:
            continue
        if kind not in ("ipv4", "ipv6"):
            # asn lines, and the summary lines that use "*" for the country.
            continue
        if len(country) != 2 or not country.isalpha() or country.upper() == UNKNOWN_CODE:
            continue

        try:
            if kind == "ipv4":
                count = int(value)
                if count < 1:
                    continue
                first = ipaddress.IPv4Address(start)
                last = ipaddress.IPv4Address(int(first) + count - 1)
            else:
                network = ipaddress.IPv6Network(f"{start}/{value}", strict=False)
                first, last = network.network_address, network.broadcast_address
        except (ipaddress.AddressValueError, ValueError) as e:
            logger.debug(f"Skipping unparseable {registry} line {line!r}: {e}")
            continue

        yield str(first), str(last), country.upper()


def fetch_delegated(url: str, timeout: int = 120) -> List[str]:
    """Read one registry's file. Kept separate so tests never touch the network."""
    import urllib.request

    logger.info(f"Fetching {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "argusmetrics-ip-country-refresh"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace").splitlines()


def refresh(db: Session, fetch=fetch_delegated, sources: Optional[Dict[str, str]] = None) -> Dict:
    """Rebuild the table from the registries, or leave it exactly as it was.

    The whole thing is one transaction, so a reader either sees the old table
    or the new one and never an empty one mid-rebuild.

    It refuses to commit a result that is too small to be real. A refresh that
    quietly installs four thousand rows because one registry served an error
    page does not fail: it succeeds, and then most of the world resolves to
    Unknown for a month until somebody wonders why. The sanity check is the
    part of this function that matters most, which is why it is not optional
    and why the tests for it outnumber the tests for the parser.
    """
    sources = sources or RIR_SOURCES
    ranges: List[Tuple[str, str, str, str]] = []
    failures: Dict[str, str] = {}

    for registry, url in sources.items():
        try:
            lines = fetch(url)
        except Exception as e:  # noqa: BLE001
            # One registry being unreachable must not wipe the other four, and
            # must not silently ship a table missing a continent either. It is
            # counted here and judged against the thresholds below.
            logger.warning(f"Could not fetch {registry}: {e}")
            failures[registry] = str(e)
            continue

        before = len(ranges)
        for start, end, country in parse_delegated(lines, registry):
            ranges.append((start, end, country, registry))
        logger.info(f"{registry}: {len(ranges) - before} ranges")

    countries = {country for _s, _e, country, _r in ranges}

    if len(ranges) < MINIMUM_ROWS or len(countries) < MINIMUM_COUNTRIES:
        raise RuntimeError(
            f"Refusing to install {len(ranges)} ranges across {len(countries)} "
            f"countries; expected at least {MINIMUM_ROWS} and "
            f"{MINIMUM_COUNTRIES}. The existing table is untouched. "
            f"Failures: {failures or 'none'}"
        )

    db.execute(text("DELETE FROM ip_country_ranges"))
    db.execute(
        text(
            "INSERT INTO ip_country_ranges (start_ip, end_ip, country, registry) "
            "VALUES (:start, :end, :country, :registry)"
        ),
        [
            {"start": s, "end": e, "country": c, "registry": r}
            for s, e, c, r in ranges
        ],
    )
    db.commit()

    logger.info(
        f"Installed {len(ranges)} ranges across {len(countries)} countries"
    )
    return {
        "ranges": len(ranges),
        "countries": len(countries),
        "failures": failures,
        "refreshed_at": datetime.now(timezone.utc),
    }


def lookup(db: Session, ip_address: str) -> Optional[str]:
    """The country for one address, or None.

    Goes through the SECURITY DEFINER function rather than reading the table,
    because the caller is the tracking context and it has no SELECT policy on
    anything. Giving it one so it could read a reference table would be giving
    it the first read it has ever had, and the next person adding a table would
    find a precedent for doing the same.
    """
    try:
        return db.execute(
            text("SELECT argus_country_for_ip(CAST(:ip AS inet))"),
            {"ip": ip_address},
        ).scalar()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Country lookup failed for {ip_address}: {e}")
        return None


def is_populated(db: Session) -> bool:
    """Whether the table can answer anything at all.

    Used by the dashboard so an empty countries panel can say which of the two
    reasons it is empty: nobody has visited, or nothing has been loaded.
    """
    try:
        return bool(db.execute(text("SELECT argus_country_data_loaded()")).scalar())
    except Exception:  # noqa: BLE001
        return False
