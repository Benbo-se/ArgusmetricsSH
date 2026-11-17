"""Load or reload the table of hosting-provider address ranges.

    python -m app.hosting_networks refresh
    python -m app.hosting_networks refresh --from-file /path/to/ip2asn-combined.tsv.gz
    python -m app.hosting_networks status
    python -m app.hosting_networks lookup 3.0.0.1

The scheduler does this weekly on its own. This exists for the first load, for
a machine with no outbound access, and for finding out what the table actually
thinks before blaming it.

--from-file reads a copy of https://iptoasn.com/data/ip2asn-combined.tsv.gz
already on disk instead of fetching it, gzipped or unpacked. An operator on a
closed network can carry it in.

Until the first refresh the table is empty, nothing is classified, and every
pageview is counted as it always was.
"""
import argparse
import logging
import pathlib
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("hosting_networks")


def _session():
    from app.database import SessionLocal, set_rls_context

    session = SessionLocal()
    # The refresh writes, and the only policy on the table is the job context.
    set_rls_context(session, context="job")
    return session


def _refresh(args) -> int:
    from app.services import hosting_networks_service

    fetch = hosting_networks_service.fetch_ip2asn
    source = None
    opened = []

    if args.from_file:
        path = pathlib.Path(args.from_file)
        if not path.is_file():
            logger.error(f"Not a file: {path}")
            return 1
        logger.info(f"Reading {path}")
        source = str(path)

        def fetch(source, timeout=None):  # noqa: ARG001
            stream = open(source, "rb")
            opened.append(stream)
            return hosting_networks_service.read_ip2asn(stream)

    session = _session()
    try:
        result = hosting_networks_service.refresh(session, fetch=fetch, source=source)
    except Exception as e:  # noqa: BLE001
        # The refresh refuses rather than installing something implausible, so
        # this path means the table is unchanged, which is the point.
        logger.error(str(e))
        return 1
    finally:
        session.close()
        for stream in opened:
            stream.close()

    logger.info(
        f"Loaded {result['ranges']:,} ranges from {result['networks']} "
        f"networks ({result['file_rows']:,} rows read)"
    )
    return 0


def _status(args) -> int:
    from sqlalchemy import text

    from app.config import settings

    session = _session()
    try:
        row = session.execute(
            text(
                "SELECT count(*) AS ranges,"
                "       count(*) FILTER (WHERE family(start_ip) = 6) AS ipv6,"
                "       max(refreshed_at) AS refreshed"
                "  FROM hosting_network_ranges"
            )
        ).one()
    finally:
        session.close()

    if not settings.DATACENTER_FILTER:
        logger.info("DATACENTER_FILTER is off: nothing is classified, whatever is loaded.")

    if not row.ranges:
        logger.info("The table is empty. Run: python -m app.hosting_networks refresh")
        return 1

    logger.info(
        f"{row.ranges:,} ranges ({row.ranges - row.ipv6:,} IPv4, {row.ipv6:,} IPv6), "
        f"loaded {row.refreshed:%Y-%m-%d %H:%M}"
    )
    return 0


def _lookup(args) -> int:
    from app.services import hosting_networks_service

    session = _session()
    try:
        found = hosting_networks_service.lookup(session, args.address)
    finally:
        session.close()

    if found is None:
        logger.info(f"{args.address}: not in a listed hosting network")
        return 1
    logger.info(f"{args.address}: {found}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.hosting_networks", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="rebuild the table from the IPtoASN file")
    refresh.add_argument(
        "--from-file",
        help="read an already-downloaded ip2asn-combined.tsv(.gz) instead of "
             "fetching it",
    )
    refresh.set_defaults(func=_refresh)

    status = sub.add_parser("status", help="what is loaded")
    status.set_defaults(func=_status)

    lookup = sub.add_parser("lookup", help="classify one address")
    lookup.add_argument("address")
    lookup.set_defaults(func=_lookup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
