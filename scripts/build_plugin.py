#!/usr/bin/env python3
"""Build the WordPress plugin's download archives from its source.

    python scripts/build_plugin.py            # write the archives
    python scripts/build_plugin.py --check    # fail if they are stale

The archives on the site were zipped by hand once, in February, from version
1.1.0. The source moved on to 1.2.0, which loads both the script and the
endpoint from the operator's own instance; the downloads kept pointing at a
hosted service that no longer exists. Nothing compared the two (#110).

Now they are built here, reproducibly: entries sorted, timestamps and owners
fixed, gzip without a timestamp. The same source gives the same bytes, so CI
can rebuild them and compare, the way build_site.py --check does for the
pages. The version in the file names comes from the plugin header, and the
version constant in the code has to agree with it.
"""
import argparse
import gzip
import io
import pathlib
import re
import sys
import tarfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "wordpress-plugin" / "argus-metrics"
OUT = ROOT / "site" / "static" / "downloads"
NAME = "argus-metrics"
# 1980-01-01, the earliest time a zip can hold: a fixed date, not the build's.
EPOCH = (1980, 1, 1, 0, 0, 0)


def plugin_version() -> str:
    """The version, checked to be the same in every place it is written."""
    php = (SRC / "argus-metrics.php").read_text()
    header = re.search(r"^\s*\*\s*Version:\s*(\S+)", php, re.M).group(1)
    constant = re.search(r"define\('ARGUS_METRICS_VERSION',\s*'([^']+)'\)", php).group(1)
    stable = re.search(r"^Stable tag:\s*(\S+)", (SRC / "readme.txt").read_text(), re.M).group(1)
    if not header == constant == stable:
        sys.exit(
            f"Plugin versions disagree: header {header}, ARGUS_METRICS_VERSION "
            f"{constant}, readme.txt Stable tag {stable}. Make them the same."
        )
    return header


def files() -> list:
    return sorted(p for p in SRC.rglob("*") if p.is_file() and p.name != ".DS_Store")


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files():
            info = zipfile.ZipInfo(f"{NAME}/{path.relative_to(SRC).as_posix()}", EPOCH)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return buf.getvalue()


def build_tar_gz() -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for path in files():
            data = path.read_bytes()
            info = tarfile.TarInfo(f"{NAME}/{path.relative_to(SRC).as_posix()}")
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            t.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as g:
        g.write(raw.getvalue())
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the archives are stale")
    args = parser.parse_args()

    version = plugin_version()
    wanted = {
        OUT / f"{NAME}-{version}.zip": build_zip(),
        OUT / f"{NAME}-{version}.tar.gz": build_tar_gz(),
    }
    # Archives of any other version are stale by definition: the docs link
    # to this one, and an old one left beside it is the bug this fixes.
    stray = [p for p in OUT.glob(f"{NAME}-*") if p not in wanted]

    if args.check:
        bad = [p for p, data in wanted.items() if not p.exists() or p.read_bytes() != data]
        bad += stray
        if bad:
            for p in bad:
                print(f"  stale: {p.relative_to(ROOT)}", file=sys.stderr)
            print("Run: python scripts/build_plugin.py", file=sys.stderr)
            return 1
        print(f"Plugin {version}: archives match the source.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for p in stray:
        p.unlink()
        print(f"  removed {p.relative_to(ROOT)}")
    for p, data in wanted.items():
        p.write_bytes(data)
        print(f"  wrote {p.relative_to(ROOT)} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
