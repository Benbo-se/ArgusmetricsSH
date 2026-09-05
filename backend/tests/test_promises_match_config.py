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


# ── What the site is allowed to claim ────────────────────────────────────
#
# The marketing pages once said "100% GDPR compliant", that the product
# "collects no personal data as defined by GDPR Article 4", that no consent
# mechanism was required, and that the reader "can rely on Legitimate Interest
# as your lawful basis". The last one is advice about someone else's legal
# obligations, given by a page that cannot know their configuration.
#
# It also contradicted this project's own data processing agreement, which
# takes the cautious position that the visitor hash may still be in scope and
# says so with a note asking for a lawyer's opinion. Both cannot be right, and
# the careful one is the one to keep.
#
# Meanwhile the documentation teaches custom properties with `userId: '12345'`
# as an example. A customer who follows that is sending an identifier through
# a product whose marketing told them they had nothing to erase.
#
# So: the site may describe what the software does, in as much detail as it
# likes. It may not decide the reader's legal position for them.

SITE = REPO / "site"

FORBIDDEN = {
    "100% gdpr": "an absolute compliance claim nobody can make for someone else's deployment",
    "gdpr compliant": "a verdict rather than a description of behaviour",
    "no personal data as defined": "a legal conclusion about Article 4",
    "falls outside the scope of consent": "a legal conclusion about the reader's obligations",
    "no consent mechanism required": "depends on the rest of the reader's site",
    "you can rely on legitimate interest": "advice about the reader's lawful basis",
    "nothing to erase": "untrue as soon as custom properties carry an identifier",
}


@pytest.mark.skipif(not SITE.is_dir(), reason=f"needs the full checkout: {SITE} is absent")
def test_the_site_describes_behaviour_and_does_not_give_legal_advice():
    offenders = []
    for path in sorted(SITE.rglob("*.html")):
        lowered = path.read_text().lower()
        for phrase, why in FORBIDDEN.items():
            if phrase in lowered:
                offenders.append(f"{path.relative_to(SITE)}: '{phrase}' is {why}")

    assert not offenders, (
        "the site is making claims it cannot support:\n  "
        + "\n  ".join(offenders)
        + "\n\nSay what the software does instead. 'The IP address is never "
        "stored' is checkable and stronger than 'GDPR compliant', which is a "
        "question about the reader's deployment and not about this software."
    )


@pytest.mark.skipif(not SITE.is_dir(), reason=f"needs the full checkout: {SITE} is absent")
def test_the_site_still_warns_about_custom_properties():
    """The one field where the customer can send personal data.

    Removing the overclaims is only half of it. The page has to say that
    custom properties are the exception, because the documentation shows a
    user id going into one.
    """
    data_page = (SITE / "data.html").read_text().lower()

    assert "custom propert" in data_page, "the caveat is gone from data.html"
    assert "under your control" in data_page or "yours to" in data_page, (
        "data.html no longer says that what goes into custom properties is the "
        "customer's own choice and responsibility"
    )
