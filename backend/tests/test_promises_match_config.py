"""What the privacy policy promises has to match what the deployment does.

A retention period is a promise made in a published legal document and kept by
an environment variable in a compose file. Nothing connects the two, so they
can drift silently: the policy says twelve months, the server keeps everything
forever, and the first person to notice is a regulator or a customer.

These read both and compare them.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PRIVACY = REPO / "site" / "privacy.html"
COMPOSE = REPO / "docker" / "docker-compose.prod.yml"

# Skipping silently is how a check like this becomes decoration, so say so.
# The development container mounts only the backend directory; CI checks out
# the whole repository, which is where this needs to run.
pytestmark = pytest.mark.skipif(
    not PRIVACY.exists() or not COMPOSE.exists(),
    reason=(
        f"needs the full checkout: {PRIVACY} and {COMPOSE} are not both here. "
        "This runs in CI. If it is skipping there, it is testing nothing."
    ),
)


def _months_promised():
    text = PRIVACY.read_text()
    match = re.search(r"kept for <strong>(\d+) months</strong>", text)
    assert match, "the privacy policy no longer states a retention period in months"
    return int(match.group(1))


def _days_configured():
    text = COMPOSE.read_text()
    match = re.search(r"DATA_RETENTION_DAYS:\s*\$\{DATA_RETENTION_DAYS:-(\d+)\}", text)
    assert match, "docker-compose.prod.yml no longer sets DATA_RETENTION_DAYS"
    return int(match.group(1))


def test_the_deployment_actually_purges():
    """0 means keep forever, which contradicts any promise at all."""
    assert _days_configured() > 0, (
        "the privacy policy promises a retention period and the production "
        "compose file defaults to keeping everything forever"
    )


def test_the_promise_matches_the_configuration():
    months, days = _months_promised(), _days_configured()

    # Months are not a fixed number of days; anything inside a fortnight of
    # the stated period is the same promise.
    expected = months * 30.44
    assert abs(days - expected) <= 14, (
        f"the privacy policy promises {months} months and the deployment is "
        f"configured for {days} days"
    )


def test_the_email_log_period_matches_too():
    """The policy states 90 days for delivery logs, which hold addresses."""
    policy = PRIVACY.read_text()
    assert "90 days" in policy, "the policy no longer states the email log period"

    from app.config import Settings

    default = Settings.model_fields["EMAIL_LOG_RETENTION_DAYS"].default
    assert default == 90, (
        f"the policy says 90 days and the default is {default}"
    )
