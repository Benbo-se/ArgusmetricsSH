"""The numbers the marketing site states about this repository.

The site's own argument is that you do not have to take any of it on trust,
because the code is public and so are the tests. A claim on that page which
has quietly gone stale undermines exactly the thing the page is selling: it
said 311 automated tests while the suite had grown to 445, which is the
harmless direction and would have been just as wrong in the other.

So the claim is pinned to the thing it describes. This test fails when the
suite grows or shrinks past a tolerance, and the fix is to update the page.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = ROOT / "site" / "index.html"
README = ROOT / "README.md"
TESTS = pathlib.Path(__file__).resolve().parent

# Some drift is fine; the number is an order-of-magnitude honesty claim, not an
# invoice. Ten per cent is close enough to stay true and loose enough that
# adding one test does not turn the build red.
TOLERANCE = 0.10


def _claimed_test_count() -> int:
    """The number printed next to "automated tests" on the home page."""
    html = SITE.read_text()
    match = re.search(
        r'>(\d+)</div>\s*<p[^>]*>\s*automated tests', html, re.S
    )
    assert match, (
        "the home page no longer states a test count in the shape this test "
        "looks for. If the claim was removed, remove this test with it."
    )
    return int(match.group(1))


def _actual_test_count() -> int:
    """Collected tests, parametrised cases included.

    Counted by asking pytest rather than by counting `def test_`, because a
    parametrised test is several tests and the site's claim is about how much
    is checked, not how many functions exist.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(TESTS)],
        capture_output=True, text=True, cwd=str(TESTS.parent),
    )
    match = re.search(r"(\d+) tests collected", result.stdout)
    assert match, f"could not read a collected count from pytest:\n{result.stdout[-800:]}"
    return int(match.group(1))


# The development container mounts only backend/, so the site is genuinely
# absent there and skipping is correct. CI checks out the whole repository, so
# a skip in CI means the path is wrong and this test is checking nothing. The
# guard below is what tells the two apart.
@pytest.mark.skipif(
    not SITE.exists(),
    reason=(
        f"marketing site not in this checkout ({SITE}). Expected in CI, where "
        "the whole repository is present. If this skips in CI, the path is "
        "wrong and nothing is being checked."
    ),
)
def test_the_stated_test_count_is_close_to_the_real_one():
    claimed = _claimed_test_count()
    actual = _actual_test_count()

    assert abs(claimed - actual) <= actual * TOLERANCE, (
        f"the home page says {claimed} automated tests and there are {actual}. "
        f"Update it in site-src/index.html and rebuild: the page under site/ is "
        f"generated. It is on the section that tells "
        f"people they do not have to take the claims on trust."
    )


def test_ci_actually_has_the_site():
    """Fails in CI if the file the test above needs is not where it looks.

    Without this, a wrong path turns the check into a permanent skip, which
    reads as green. Locally there is no CI variable and this does nothing.
    """
    import os

    if not os.environ.get("CI"):
        pytest.skip("only meaningful where the whole repository is checked out")

    assert SITE.exists(), (
        f"{SITE} does not exist in CI, so the claim check silently skips. "
        "Fix the path rather than the assertion."
    )


def _claimed_in_readme() -> int:
    """The backend test count the README states."""
    match = re.search(r'(\d+) backend tests', README.read_text())
    assert match, (
        "the README no longer states a backend test count in the shape this "
        "test looks for. If the claim was removed, remove this test with it."
    )
    return int(match.group(1))


@pytest.mark.skipif(not README.exists(), reason="README not in this checkout")
def test_the_readme_count_is_close_to_the_real_one():
    """The same rot, in the other document that states a number.

    The home page said 311 while the suite had grown to 445. The README said
    270. Both are the kind of claim that is true the day it is written and
    quietly wrong a month later, on pages whose argument is that you do not
    have to take any of this on trust.
    """
    claimed = _claimed_in_readme()
    actual = _actual_test_count()

    assert abs(claimed - actual) <= actual * TOLERANCE, (
        f"the README says {claimed} backend tests and there are {actual}. "
        f"Update it."
    )
