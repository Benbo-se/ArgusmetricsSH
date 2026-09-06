"""Version stylesheets and scripts by their own contents.

The dashboard's assets sit at fixed URLs with no version in the name, which
leaves two bad options: cache them for a long time and be unable to ship a
fix, or cache them briefly and revalidate forever. The first was what we did,
and the stylesheet was served immutable for thirty days while being rebuilt on
almost every commit.

A fingerprint derived from the file's contents removes the choice. The URL
changes exactly when the file does, so the browser can be told to keep it
forever and still never run a stale copy.

    <link href="{{ static_url('css/tailwind.min.css') }}">
    → /static/css/tailwind.min.css?v=3f9a1c02

A query string rather than a renamed file, because renaming means a build
step, a manifest, and a way to serve both names during a rollout. This needs
none of that: nginx serves the same file whatever the query says, and the
query is only there to make the cache key move.

The hash is of the contents, not of a timestamp or a release number. Two
deploys that change nothing produce the same URL and cost the visitor no
download, and a file that changes gets a new URL even if the version did not.
"""
import hashlib
import logging
import pathlib
from typing import Dict

logger = logging.getLogger(__name__)

STATIC_ROOT = pathlib.Path(__file__).resolve().parent / "static"

#: One hash per file per process. The files are baked into the image and do
#: not change under a running container, so reading each one once is enough.
_fingerprints: Dict[str, str] = {}


def fingerprint(relative_path: str) -> str:
    """Eight hex characters of the file's SHA-256, or '' if it is not there.

    Short because it only has to make the URL change, not resist an attack:
    four billion values is far more than the number of versions any of these
    files will ever have.
    """
    if relative_path in _fingerprints:
        return _fingerprints[relative_path]

    path = STATIC_ROOT / relative_path
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError as e:
        # A missing file is a broken page either way. Returning no fingerprint
        # keeps the URL working and lets the short cache apply, which is the
        # safe direction: better a revalidation than an immutable 404.
        logger.warning(f"No fingerprint for {relative_path}: {e}")
        digest = ""

    _fingerprints[relative_path] = digest
    return digest


def static_url(relative_path: str) -> str:
    """The URL for a static asset, carrying its content fingerprint.

    Used for stylesheets and scripts. Not for the tracking script: that one is
    embedded in other people's pages and its URL has to stay exactly what we
    told them to paste.
    """
    version = fingerprint(relative_path)
    url = f"/static/{relative_path}"
    return f"{url}?v={version}" if version else url
