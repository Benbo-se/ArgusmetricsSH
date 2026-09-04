"""Every operator-facing setting must be documented and forwarded.

A setting that exists only in config.py is invisible to whoever is running
this. ENABLE_REGISTRATION is the case that matters: an instance exposed to the
internet with open signup, whose owner never knew the setting existed, is a
real problem rather than a documentation gap.

Worse than undocumented is documented but not forwarded. A variable that
docker-compose.prod.yml does not pass through reaches nothing, so setting it
in .env has no effect at all, and it looks like it worked.

The classification lives in config.py as two sets that must together cover
every field exactly. A setting added later belongs to neither, and the first
test here fails until somebody decides which it is. That decision is the whole
point: leaving it undecided is how this gap opened.
"""
import pathlib
import re

import pytest

from app.config import INTERNAL_SETTINGS, OPERATOR_SETTINGS, Settings

REPO = pathlib.Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / "docker" / ".env.example"
COMPOSE = REPO / "docker" / "docker-compose.prod.yml"


def test_every_setting_is_classified():
    """The guard against this drifting again. Needs no files, so never skips."""
    fields = set(Settings.model_fields)

    unclassified = fields - OPERATOR_SETTINGS - INTERNAL_SETTINGS
    assert not unclassified, (
        f"new settings belong to neither set: {sorted(unclassified)}. "
        "Decide whether someone running their own instance needs to know each "
        "one exists. If yes, add it to OPERATOR_SETTINGS, document it in "
        "docker/.env.example and forward it in docker-compose.prod.yml. If no, "
        "add it to INTERNAL_SETTINGS with a comment saying why not."
    )

    stale = (OPERATOR_SETTINGS | INTERNAL_SETTINGS) - fields
    assert not stale, (
        f"classified settings that no longer exist: {sorted(stale)}. "
        "Remove them, or the lists slowly become fiction."
    )

    both = OPERATOR_SETTINGS & INTERNAL_SETTINGS
    assert not both, f"settings in both sets: {sorted(both)}"


# The development container mounts only the backend directory. Say so rather
# than skipping quietly, because a check that silently skips is decoration.
needs_checkout = pytest.mark.skipif(
    not ENV_EXAMPLE.exists() or not COMPOSE.exists(),
    reason=(
        f"needs the full checkout: {ENV_EXAMPLE} and {COMPOSE} are not both "
        "here. This runs in CI. If it is skipping there, it is testing nothing."
    ),
)


def _mentioned(text: str, name: str) -> bool:
    """Whether a settings name appears as a variable, set or commented out."""
    return re.search(rf"^\s*#?\s*{re.escape(name)}\s*[:=]", text, re.M) is not None


@needs_checkout
def test_operator_settings_are_in_the_example_env():
    text = ENV_EXAMPLE.read_text()
    missing = sorted(n for n in OPERATOR_SETTINGS if not _mentioned(text, n))

    assert not missing, (
        f"not in docker/.env.example: {missing}. Somebody self-hosting this "
        "will never find them. Commented out with an explanation counts; "
        "unmentioned does not."
    )


@needs_checkout
def test_operator_settings_are_forwarded_by_the_compose_file():
    text = COMPOSE.read_text()

    # Postgres credentials are consumed by the compose file itself to build
    # the connection string, so they are not forwarded to the backend under
    # their own names.
    consumed_by_compose = {"DATABASE_URL"}

    missing = sorted(
        n
        for n in OPERATOR_SETTINGS - consumed_by_compose
        if not _mentioned(text, n)
    )

    assert not missing, (
        f"not forwarded by docker-compose.prod.yml: {missing}. Setting these "
        "in .env would have no effect, which is worse than them being "
        "undocumented, because it looks like it worked."
    )


@needs_checkout
def test_internal_settings_are_not_offered_to_operators():
    """The lists have to mean something in both directions.

    A setting called internal that is nonetheless advertised in .env.example is
    an invitation to set it, and the classification stops describing reality.
    """
    text = ENV_EXAMPLE.read_text()
    offered = sorted(n for n in INTERNAL_SETTINGS if _mentioned(text, n))

    assert not offered, (
        f"listed in .env.example but classified internal: {offered}. Either it "
        "is operator-facing, in which case move it, or the line should go."
    )
