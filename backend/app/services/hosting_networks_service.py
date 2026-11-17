"""Build the table of hosting-provider address ranges (#103).

A crawler that runs JavaScript behind an ordinary Chrome user agent cannot be
told from a visitor by anything it sends. It can be told by where it sends it
from, and the access logs record no address on purpose, so that has to be
decided when the pageview arrives or never.

IPtoASN publishes which network announces every routed address range, daily,
without an account, as one file:

    range_start <tab> range_end <tab> AS_number <tab> country <tab> AS_description
    3.0.0.0         3.0.255.255       16509       US    AMAZON-02 - Amazon.com, Inc.

The data is public domain. iptoasn.com says "Licensed under Public Domain
(PDDL v1.0)" on its front page and names
https://opendatacommons.org/licenses/pddl/1.0/ as the licence of the dataset
(read 2026-11-17), so there is nothing to attribute and nothing to agree to.

We keep only the ranges whose AS number is on the list in app/hosting_asns.py,
about twenty-six thousand of the seven hundred thousand, and of those only
where they start and end.

What it costs, stated plainly because the number on the dashboard will not say
it: this is which network *announces* a range, not who is using it. A person
on a VPN, a corporate proxy or a remote desktop hosted at one of the listed
providers is labelled exactly as a crawler is. And a crawler on a residential
proxy, or at a provider that is not listed, is not labelled at all. It removes
the bulk, not the whole.

The refresh fetches one public file. That is the server reading a published
dataset on a schedule; no visitor address is involved and nothing about your
traffic leaves the machine, which is the reason the lookup itself never
touches the network.
"""
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hosting_asns import HOSTING_ASNS

logger = logging.getLogger(__name__)

#: IPv4 and IPv6 in one file, gzipped, about 11 MB.
SOURCE_URL = "https://iptoasn.com/data/ip2asn-combined.tsv.gz"

#: The only value the label takes today. A string and not a boolean so that a
#: later class does not need a second column on the largest table we have.
DATACENTER = "datacenter"

#: Below these the file is not the file, it is an error page or half a
#: download. The real one has about 720,000 rows, of which about 26,000 belong
#: to the listed networks, and every listed network appears in it. A refresh
#: that falls short would otherwise install itself silently and start counting
#: crawlers again, with nothing anywhere saying so.
MINIMUM_FILE_ROWS = 300_000
MINIMUM_RANGES = 10_000
#: Three quarters of the list. A provider renumbering or leaving the table is
#: ordinary; most of them missing means the file is not what it was.
MINIMUM_SHARE_OF_LIST = 0.75

#: The largest download we will hold. Six times the real file.
MAXIMUM_BYTES = 64 * 1024 * 1024
#: And the most rows we will read out of it, so that a small file which
#: unpacks to something enormous is refused instead of read to the end.
MAXIMUM_FILE_ROWS = 5_000_000

Range = Tuple[int, int, int]  # family (4 or 6), first address, last address


def parse_ip2asn(lines: Iterable[str]) -> Iterator[Tuple[int, int, int, int]]:
    """Turn the file into (family, first, last, AS number), one per good row.

    Every well-formed row is yielded, listed or not: how many there were is
    how refresh() tells the file from an error page. Addresses come out as
    integers because the next step is to sort and merge them.

    A row that cannot be read is skipped, not raised on. One bad line in seven
    hundred thousand should not cost the refresh, and a file of nothing but
    bad lines is caught by the count.
    """
    for raw in lines:
        parts = raw.rstrip("\r\n").split("\t")
        if len(parts) < 3:
            continue
        try:
            first = ipaddress.ip_address(parts[0].strip())
            last = ipaddress.ip_address(parts[1].strip())
            asn = int(parts[2])
        except ValueError:
            continue
        if first.version != last.version or int(last) < int(first) or asn < 0:
            continue
        yield first.version, int(first), int(last), asn


def merge(ranges: Iterable[Range]) -> List[Range]:
    """Sort, and join ranges that touch or overlap.

    The lookup takes the last range starting at or before an address and asks
    whether it reaches that far. That is only right when no range sits inside
    another, which the published file promises and this makes true whatever
    the file does. It also makes the table smaller: neighbouring blocks of one
    provider become one row.
    """
    merged: List[Range] = []
    for family, first, last in sorted(ranges):
        if merged:
            previous_family, previous_first, previous_last = merged[-1]
            if previous_family == family and first <= previous_last + 1:
                if last > previous_last:
                    merged[-1] = (family, previous_first, last)
                continue
        merged.append((family, first, last))
    return merged


def _as_text(family: int, value: int) -> str:
    if family == 4:
        return str(ipaddress.IPv4Address(value))
    return str(ipaddress.IPv6Address(value))


def fetch_ip2asn(url: str = SOURCE_URL, timeout: int = 120) -> Iterator[str]:
    """Read the published file. Kept separate so tests never touch the network."""
    import io
    import urllib.request

    logger.info(f"Fetching {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "argusmetrics-hosting-networks-refresh"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAXIMUM_BYTES + 1)
    if len(body) > MAXIMUM_BYTES:
        raise RuntimeError(
            f"{url} is larger than {MAXIMUM_BYTES} bytes, which the real file "
            "is nowhere near"
        )
    return read_ip2asn(io.BytesIO(body))


def read_ip2asn(stream) -> Iterator[str]:
    """Lines of the file from an open binary stream, gzipped or not.

    The published file is gzipped; one carried in by hand may have been
    unpacked on the way. Told apart by the two bytes every gzip file starts
    with, not by the name.
    """
    import gzip
    import io

    head = stream.read(2)
    stream.seek(0)
    if head == b"\x1f\x8b":
        stream = gzip.GzipFile(fileobj=stream)
    return iter(io.TextIOWrapper(stream, encoding="utf-8", errors="replace"))


def refresh(db: Session, fetch=fetch_ip2asn, source: Optional[str] = None) -> Dict:
    """Rebuild the table from the published file, or leave it exactly as it was.

    The whole thing is one transaction, so a reader either sees the old table
    or the new one and never an empty one mid-rebuild.

    It refuses to commit a result that is too small to be real. An empty or
    thin table does not fail anywhere: it classifies nothing, every crawler is
    a visitor again, and the dashboard shows a good week. The checks are the
    part of this function that matters most, which is why they are not
    optional.
    """
    source = source or SOURCE_URL
    file_rows = 0
    kept: List[Range] = []
    seen = set()

    for family, first, last, asn in parse_ip2asn(fetch(source)):
        file_rows += 1
        if file_rows > MAXIMUM_FILE_ROWS:
            raise RuntimeError(
                f"Refusing to read past {MAXIMUM_FILE_ROWS} rows of {source}. "
                "The existing table is untouched."
            )
        if asn in HOSTING_ASNS:
            kept.append((family, first, last))
            seen.add(asn)

    missing = sorted(set(HOSTING_ASNS) - seen)
    needed = int(len(HOSTING_ASNS) * MINIMUM_SHARE_OF_LIST)

    if (
        file_rows < MINIMUM_FILE_ROWS
        or len(kept) < MINIMUM_RANGES
        or len(seen) < needed
    ):
        raise RuntimeError(
            f"Refusing to install {len(kept)} ranges from {len(seen)} of "
            f"{len(HOSTING_ASNS)} listed networks, out of {file_rows} rows "
            f"read; expected at least {MINIMUM_RANGES} ranges, {needed} "
            f"networks and {MINIMUM_FILE_ROWS} rows. The existing table is "
            "untouched."
        )

    ranges = merge(kept)

    db.execute(text("DELETE FROM hosting_network_ranges"))
    db.execute(
        text(
            "INSERT INTO hosting_network_ranges (start_ip, end_ip) "
            "VALUES (:start, :end)"
        ),
        [
            {"start": _as_text(family, first), "end": _as_text(family, last)}
            for family, first, last in ranges
        ],
    )
    db.commit()

    if missing:
        # Worth a line, not a failure: the list is ours and the file is
        # theirs, and a number that stops appearing is how the list goes
        # stale.
        logger.warning(
            "Listed networks with no ranges in the file: "
            + ", ".join(f"AS{asn} ({HOSTING_ASNS[asn]})" for asn in missing)
        )

    logger.info(
        f"Installed {len(ranges)} ranges ({len(kept)} before merging) from "
        f"{len(seen)} networks, out of {file_rows} rows"
    )
    return {
        "ranges": len(ranges),
        "listed_rows": len(kept),
        "file_rows": file_rows,
        "networks": len(seen),
        "missing": missing,
        "refreshed_at": datetime.now(timezone.utc),
    }


def lookup(db: Session, ip_address: str) -> Optional[str]:
    """The class of one address: 'datacenter', or None for everything else.

    Goes through the SECURITY DEFINER function, not the table, because the
    caller is the tracking context and it has no SELECT policy on anything.
    The function answers with the class and nothing else, so what the tracking
    context can learn through it is one bit about an address it was given.

    Never touches the network. An empty table answers None for every address,
    which is an instance behaving exactly as it did before this existed.

    The address is parsed here first. Postgres raises on text that is not an
    address, and a raised statement aborts the transaction the pageview is
    about to be written in.
    """
    try:
        address = ipaddress.ip_address(str(ip_address).strip())
    except ValueError:
        return None
    # ::ffff:203.0.113.7 is the IPv4 address 203.0.113.7 and is listed as one.
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped

    try:
        return db.execute(
            text("SELECT argus_traffic_class_for_ip(CAST(:ip AS inet))"),
            {"ip": str(address)},
        ).scalar()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Network lookup failed: {e}")
        return None
