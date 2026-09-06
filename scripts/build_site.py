#!/usr/bin/env python3
"""Render the marketing site from templates into static HTML.

    python scripts/build_site.py
    python scripts/build_site.py --check      # fail if the output is stale

The twelve pages under site/ used to be twelve hand-maintained files, and they
had drifted the way copies do: seven different navigations, six pages missing
the footer entirely, a meta description contradicting the table three screens
below it, and a test count that had been wrong by a hundred and thirty for
weeks. One layout, twelve content files, and that class of problem stops.

Generated to disk rather than served through the application. nginx keeps
serving plain files, so the site stays up when the backend does not, no Python
runs for a page that never changes, and the public pages have no attack
surface. The cost is generated files in the repository, which is why --check
exists and runs in CI: output that has drifted from its source is exactly the
problem this was meant to solve.

Asset URLs get eight hex characters of the file's SHA-256, so nginx can hand
them a year of cache without a fix being unable to arrive. The tracking script
never gets one: its URL is in other people's page source.
"""
import argparse
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "site-src"
OUT = ROOT / "site"
STATIC = OUT / "static"

#: Never fingerprinted. Customers pasted this URL into their own pages, and
#: nginx refuses to give it the long cache for the same reason.
NEVER_VERSIONED = {"tracker.min.js"}

#: site-src/compare__matomo.html renders to site/compare/matomo.html. A flat
#: source directory rather than nested, so a template's name says where it
#: lands without anyone having to look.
NESTING = "__"


def fingerprint(relative_path: str) -> str:
    """Eight hex characters of the file's contents, or '' if it is not there."""
    path = STATIC / relative_path
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        print(f"  no fingerprint for {relative_path}: not built yet", file=sys.stderr)
        return ""


def static_url(relative_path: str) -> str:
    """The URL for a static asset, carrying its content fingerprint."""
    if relative_path in NEVER_VERSIONED:
        return f"/static/{relative_path}"
    version = fingerprint(relative_path)
    url = f"/static/{relative_path}"
    return f"{url}?v={version}" if version else url


def output_path(template_name: str) -> pathlib.Path:
    return OUT / template_name.replace(NESTING, "/")


def render_all() -> dict:
    """Every template rendered, keyed by the file it belongs in."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(SRC)),
        # Undefined is an error rather than an empty string: a page that
        # forgets its title should fail the build, not ship with <title></title>.
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.globals["static"] = static_url
    # Every page may leave these unset and inherit the layout's fallback.
    for optional in ("page_canon", "page_og_url", "page_og_title", "page_og_desc",
                     "page_tw_title", "page_tw_desc", "page_og_img"):
        env.globals[optional] = ""

    pages = {}
    for template in sorted(SRC.glob("*.html")):
        if template.name.startswith("_"):
            continue
        pages[output_path(template.name)] = env.get_template(template.name).render()
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check", action="store_true",
        help="write nothing; exit non-zero if any page on disk differs from "
             "what the templates produce",
    )
    args = parser.parse_args()

    if not SRC.is_dir():
        print(f"No templates at {SRC}", file=sys.stderr)
        return 2

    pages = render_all()
    if not pages:
        print(f"No templates found in {SRC}", file=sys.stderr)
        return 2

    stale = []
    for path, html in pages.items():
        existing = path.read_text() if path.exists() else None
        if existing == html:
            continue
        stale.append(path.relative_to(ROOT))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html)

    if args.check:
        if stale:
            print(
                f"{len(stale)} page(s) differ from their templates:\n  "
                + "\n  ".join(str(p) for p in stale)
                + "\n\nRun: python scripts/build_site.py",
                file=sys.stderr,
            )
            return 1
        print(f"{len(pages)} pages match their templates.")
        return 0

    print(f"Rendered {len(pages)} pages, {len(stale)} changed.")
    for path in stale:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
