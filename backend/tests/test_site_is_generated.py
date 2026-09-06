"""The marketing site is rendered from templates, not maintained by hand.

Twelve pages had drifted into seven different navigations, six of them with no
footer at all, a meta description contradicting the table three screens below
it, and a test count wrong by a hundred and thirty. That is what a hundred and
forty-eight lines of navigation written out eleven times does over a year.

One layout renders all of it now, and the output is committed so nginx can
keep serving plain files: the marketing site stays up when the backend does
not, and no Python runs for a page that never changes.

Committing generated files is only safe while something checks they still
match their source, which is the whole point here. `build_site.py --check`
does it in CI. These tests check the arrangement around it: that every page
has a template, that nobody has started hand-editing the output again, and
that the tracking script keeps the URL customers pasted.
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "site-src"
OUT = ROOT / "site"
BUILDER = ROOT / "scripts" / "build_site.py"

pytestmark = pytest.mark.skipif(
    not SRC.is_dir(),
    reason=(
        f"marketing site templates not in this checkout ({SRC}). The "
        "development container mounts only backend/. Expected to run in CI."
    ),
)


def _pages():
    return sorted(p for p in OUT.rglob("*.html"))


def _templates():
    return sorted(p for p in SRC.glob("*.html") if not p.name.startswith("_"))


class TestEveryPageComesFromATemplate:
    def test_the_counts_match(self):
        """A page with no template is one nobody can regenerate, and the next
        person to change the navigation will miss it."""
        pages = {p.relative_to(OUT).as_posix() for p in _pages()}
        rendered = {t.name.replace("__", "/") for t in _templates()}

        assert pages == rendered, (
            f"pages without a template: {sorted(pages - rendered)}\n"
            f"templates with no page: {sorted(rendered - pages)}"
        )

    def test_there_are_pages_to_check(self):
        """Guards against both sides being empty, which compares equal."""
        assert len(_pages()) >= 10


class TestTheOutputMatchesTheTemplates:
    def test_rendering_again_changes_nothing(self):
        """The check CI runs. A failure means someone edited site/ by hand,
        or changed a template and did not rebuild."""
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--check"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        assert result.returncode == 0, result.stderr or result.stdout

    def test_the_check_notices_a_hand_edit(self, tmp_path):
        """Otherwise it is a check that always passes.

        A page is edited in place, the check is expected to fail, and the page
        is put back whatever happens.
        """
        page = OUT / "compare" / "matomo.html"
        original = page.read_text()
        try:
            page.write_text(original.replace("</body>", "<p>hand edit</p></body>"))
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--check"],
                capture_output=True, text=True, cwd=str(ROOT),
            )
        finally:
            page.write_text(original)

        assert result.returncode != 0, (
            "a hand-edited page passed the check, so nothing is verifying that "
            "the committed HTML still comes from the templates"
        )
        assert "matomo" in (result.stderr + result.stdout)


class TestTheLayoutIsShared:
    # The site navigation, identified by the Alpine state only it uses. Not
    # any <nav> element: the docs page has a sidebar table of contents, which
    # is page content and belongs in its template.
    SITE_NAV_MARKER = "mobileMenuOpen"

    def test_no_template_carries_its_own_navigation(self):
        """The thing this replaced. A page that inlines the site nav has
        forked it, and the fork is what drifted into seven variants."""
        offenders = [
            t.name for t in _templates()
            if self.SITE_NAV_MARKER in t.read_text()
        ]
        assert not offenders, (
            "these templates define their own site navigation instead of "
            f"inheriting it: {offenders}"
        )

    def test_the_marker_identifies_the_shared_navigation(self):
        """Guards the test above against keying on something that moved."""
        layout = (SRC / "_layout.html").read_text()
        assert self.SITE_NAV_MARKER in layout, (
            "the layout no longer contains the marker the check looks for, so "
            "the check passes for every template regardless"
        )

    def test_no_template_carries_its_own_footer(self):
        offenders = [
            t.name for t in _templates() if "<footer" in t.read_text()
        ]
        assert not offenders, f"these templates define their own footer: {offenders}"

    def test_every_page_ends_up_with_both(self):
        """Six of the twelve had no footer at all, which is how a visitor on
        the privacy page ran out of ways to get anywhere else."""
        missing = [
            p.relative_to(OUT).as_posix()
            for p in _pages()
            if "<nav" not in p.read_text() or "<footer" not in p.read_text()
        ]
        assert not missing, f"pages rendered without a nav or footer: {missing}"

    def test_the_navigation_is_identical_everywhere(self):
        """Seven variants across twelve pages was the original complaint."""
        import re

        navs = set()
        for page in _pages():
            match = re.search(r"<nav.*?</nav>", page.read_text(), re.S)
            assert match, f"{page.name} has no navigation"
            navs.add(match.group(0))

        assert len(navs) == 1, f"{len(navs)} different navigations across the site"


class TestAssetsAreVersionedExceptTheOne:
    def test_stylesheets_carry_a_fingerprint(self):
        import re

        unversioned = []
        for page in _pages():
            for url in re.findall(r'href="(/static/[^"]+\.css)"', page.read_text()):
                unversioned.append(f"{page.name}: {url}")

        assert not unversioned, (
            "these stylesheets have no content fingerprint, so nginx gives "
            f"them an hour instead of a year: {unversioned}"
        )

    def test_the_tracking_script_never_does(self):
        """Its URL is in other people's page source and cannot move."""
        offenders = [
            p.relative_to(OUT).as_posix()
            for p in _pages()
            if "tracker.min.js?v=" in p.read_text()
        ]
        assert not offenders, (
            f"the tracking script was given a version in {offenders}. "
            "Customers pasted the unversioned URL into their own sites."
        )

    def test_the_snippet_customers_copy_is_still_there(self):
        """The docs page shows the script tag people paste. If versioning ever
        reached it, every customer's copy would be wrong."""
        docs = (OUT / "docs" / "index.html").read_text()
        assert "tracker.min.js" in docs
        assert "tracker.min.js?v=" not in docs
