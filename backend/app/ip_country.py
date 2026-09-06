"""Load or reload the IP-to-country table.

    python -m app.ip_country refresh
    python -m app.ip_country refresh --from-dir /path/to/delegated/files
    python -m app.ip_country status
    python -m app.ip_country lookup 81.224.1.1

The scheduler does this weekly on its own. This exists for the first load, for
a machine with no outbound access, and for finding out what the table actually
thinks before blaming it.

--from-dir reads files already on disk instead of fetching, named after the
registry they came from (ripencc, arin, apnic, lacnic, afrinic), with or
without an extension. An operator on a closed network can carry them in.
"""
import argparse
import logging
import pathlib
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ip_country")


def _session():
    from app.database import SessionLocal, set_rls_context

    session = SessionLocal()
    # The refresh writes, and the only policy on the table is the job context.
    set_rls_context(session, context="job")
    return session


def _refresh(args) -> int:
    from app.services import ip_country_service

    fetch = ip_country_service.fetch_delegated
    sources = None

    if args.from_dir:
        directory = pathlib.Path(args.from_dir)
        if not directory.is_dir():
            logger.error(f"Not a directory: {directory}")
            return 1

        found = {}
        for registry in ip_country_service.RIR_SOURCES:
            matches = sorted(directory.glob(f"*{registry}*"))
            if matches:
                found[registry] = str(matches[0])
        if not found:
            logger.error(
                f"No registry files in {directory}. Expected names containing "
                + ", ".join(ip_country_service.RIR_SOURCES)
            )
            return 1

        logger.info("Reading " + ", ".join(f"{k} <- {v}" for k, v in found.items()))
        sources = found

        def fetch(path, timeout=None):  # noqa: ARG001
            return pathlib.Path(path).read_text(errors="replace").splitlines()

    session = _session()
    try:
        result = ip_country_service.refresh(session, fetch=fetch, sources=sources)
    except Exception as e:  # noqa: BLE001
        # The refresh refuses rather than installing something implausible, so
        # this path means the table is unchanged, which is the point.
        logger.error(str(e))
        return 1
    finally:
        session.close()

    logger.info(
        f"Loaded {result['ranges']:,} ranges across {result['countries']} countries"
    )
    if result["failures"]:
        logger.warning(
            "Some registries did not answer and their regions are missing: "
            + ", ".join(result["failures"])
        )
    return 0


def _status(args) -> int:
    from sqlalchemy import text

    session = _session()
    try:
        rows = session.execute(
            text(
                "SELECT registry, count(*), max(refreshed_at) "
                "  FROM ip_country_ranges GROUP BY registry ORDER BY registry"
            )
        ).all()
    finally:
        session.close()

    if not rows:
        logger.info("The table is empty. Run: python -m app.ip_country refresh")
        return 1

    for registry, count, refreshed in rows:
        logger.info(f"{registry:<10} {count:>8,} ranges   loaded {refreshed:%Y-%m-%d %H:%M}")
    logger.info(f"{'total':<10} {sum(r[1] for r in rows):>8,}")
    return 0


def _lookup(args) -> int:
    from app.services import ip_country_service

    session = _session()
    try:
        country = ip_country_service.lookup(session, args.address)
    finally:
        session.close()

    if country is None:
        logger.info(f"{args.address}: no range covers this address")
        return 1
    logger.info(f"{args.address}: {country}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.ip_country", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="rebuild the table from the registries")
    refresh.add_argument(
        "--from-dir",
        help="read already-downloaded registry files from this directory "
             "instead of fetching them",
    )
    refresh.set_defaults(func=_refresh)

    status = sub.add_parser("status", help="what is loaded, per registry")
    status.set_defaults(func=_status)

    lookup = sub.add_parser("lookup", help="resolve one address")
    lookup.add_argument("address")
    lookup.set_defaults(func=_lookup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
