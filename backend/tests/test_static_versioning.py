"""Assets carry a hash of their contents, so they can be cached forever.

The dashboard's stylesheets and scripts sit at fixed URLs. That left two bad
options, and we had picked the worse one: served immutable for thirty days
while being rebuilt on almost every commit, so a returning user could get
today's markup against last month's stylesheet and there was no way to reach
them. The alternative, revalidating forever, is merely wasteful.

A fingerprint removes the choice. The URL changes exactly when the file does.

Which makes the reference itself load-bearing. A template that spells out
/static/css/whatever.css gets no fingerprint, and nginx gives an unversioned
asset an hour rather than a year, so the failure is slow pages rather than
stale ones. That is the right direction to fail in, and still worth catching,
because a reference nobody notices is one nobody fixes.

The tracking script is the deliberate exception, in both directions: it must
never be versioned here, and nginx refuses to give it the long cache even if
a version appears. Customers pasted that URL into their own pages.
"""
import pathlib
import re

import pytest

from app.static_files import STATIC_ROOT, fingerprint, static_url

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"

#: href="/static/..." or src="/static/..." pointing at a stylesheet or script.
LITERAL_ASSET = re.compile(r'(?:href|src)="(/static/[^"]+\.(?:css|js))"')


def _templates():
    return sorted(TEMPLATES.rglob("*.html"))


class TestTheHelper:
    def test_a_url_carries_a_fingerprint(self):
        url = static_url("css/tailwind.min.css")
        assert re.fullmatch(r"/static/css/tailwind\.min\.css\?v=[0-9a-f]{8}", url), url

    def test_the_fingerprint_follows_the_contents(self, tmp_path, monkeypatch):
        """The whole point. A hash that does not move with the file is a
        constant, and a constant is the same as no version at all."""
        import app.static_files as sf

        asset = tmp_path / "thing.css"
        asset.write_text("a{}")
        monkeypatch.setattr(sf, "STATIC_ROOT", tmp_path)
        monkeypatch.setattr(sf, "_fingerprints", {})

        first = sf.fingerprint("thing.css")
        asset.write_text("a{color:red}")
        monkeypatch.setattr(sf, "_fingerprints", {})
        second = sf.fingerprint("thing.css")

        assert first and second and first != second

    def test_identical_contents_give_an_identical_url(self, tmp_path, monkeypatch):
        """A deploy that changes nothing must not cost every visitor a
        download, which is what a build number or a timestamp would do."""
        import app.static_files as sf

        monkeypatch.setattr(sf, "STATIC_ROOT", tmp_path)
        (tmp_path / "a.css").write_text("same")
        (tmp_path / "b.css").write_text("same")
        monkeypatch.setattr(sf, "_fingerprints", {})

        assert sf.fingerprint("a.css") == sf.fingerprint("b.css")

    def test_a_missing_file_still_produces_a_usable_url(self, monkeypatch):
        """Without a version, so nginx gives it the short cache.

        Better a revalidation than a 404 cached for a year.
        """
        import app.static_files as sf

        monkeypatch.setattr(sf, "_fingerprints", {})
        assert sf.static_url("css/does-not-exist.css") == "/static/css/does-not-exist.css"

    def test_it_is_cached_per_process(self):
        """These files do not change under a running container, and hashing
        them on every render would read every asset on every page load."""
        assert fingerprint("css/theme.css") == fingerprint("css/theme.css")


class TestEveryTemplateReferenceIsVersioned:
    def test_no_template_spells_out_a_stylesheet_or_script_path(self):
        offenders = []
        for path in _templates():
            for match in LITERAL_ASSET.finditer(path.read_text()):
                url = match.group(1)
                if url == "/static/tracker.min.js":
                    continue
                offenders.append(f"{path.relative_to(TEMPLATES)}: {url}")

        assert not offenders, (
            "these assets are referenced without a content fingerprint, so "
            "they fall back to the short cache and are revalidated forever:\n  "
            + "\n  ".join(offenders)
            + "\n\nUse {{ static_url('css/thing.css') }} instead."
        )

    def test_the_scan_would_notice_if_one_came_back(self):
        """Guards against the regex quietly matching nothing."""
        sample = '<link rel="stylesheet" href="/static/css/thing.css">'
        assert LITERAL_ASSET.findall(sample) == ["/static/css/thing.css"]

    def test_the_helper_is_actually_used(self):
        """The test above also passes on templates that reference no assets
        at all, which is not the same as versioning them."""
        used = sum(
            path.read_text().count("static_url(") for path in _templates()
        )
        assert used >= 8, (
            f"only {used} static_url() calls across the templates; the "
            "references were probably removed rather than versioned"
        )

    def test_every_versioned_path_resolves_to_a_real_file(self):
        """A typo produces no fingerprint and a silent 404 for a stylesheet,
        which is a page that renders unstyled rather than an error."""
        missing = []
        for path in _templates():
            for rel in re.findall(r"static_url\(\s*'([^']+)'\s*\)", path.read_text()):
                if not (STATIC_ROOT / rel).exists():
                    missing.append(f"{path.relative_to(TEMPLATES)}: {rel}")

        assert not missing, "\n  ".join(["these assets do not exist:"] + missing)


class TestTheTrackingScriptIsNeverVersioned:
    """Its URL is in other people's page source. It cannot move."""

    def test_no_template_adds_a_version_to_it(self):
        offenders = [
            str(path.relative_to(TEMPLATES))
            for path in _templates()
            if "tracker.min.js?v=" in path.read_text()
        ]
        assert not offenders, (
            "the tracking script was given a version in " + ", ".join(offenders)
            + ". Customers pasted the unversioned URL into their own sites."
        )

    def test_the_snippet_shown_to_customers_has_no_version(self):
        """What the settings page tells them to copy is what has to work."""
        settings = TEMPLATES / "dashboard" / "settings.html"
        text = settings.read_text()
        assert "tracker.min.js" in text
        assert "tracker.min.js?v=" not in text
