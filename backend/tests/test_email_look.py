"""What every mail has in common, checked on all of them.

A mail that fetches a picture or a typeface tells the server holding it that
the mail was opened, and when. This product's whole claim is that it does not
follow people, so its own mail fetches nothing.
"""
import re

import pytest

from app.services import email_layout
from app.services.email_reports_service import EmailReportsService
from app.services.email_service import email_service


@pytest.fixture
def sent(monkeypatch):
    mails = []
    monkeypatch.setattr(email_service, "configured", True)
    monkeypatch.setattr(email_service, "_deliver",
                        lambda to, subject, text, html: mails.append(html) or True)
    monkeypatch.setattr(email_service, "_log_email", lambda *a, **k: None)
    return mails


def _every_mail(sent):
    email_service.send_verification_email("a@example.com", "https://app.example/verify?token=t", "123456")
    email_service.send_welcome_email("a@example.com")
    email_service.send_password_reset_email("a@example.com", "https://app.example/reset?token=t")
    email_service.send_account_invitation("a@example.com", "b@example.com", "https://app.example/join/t", 7)
    email_service.send_team_invitation("a@example.com", "Shop", "https://shop.example", "admin",
                                       "b@example.com", "https://app.example/accept-invite?token=t")
    site = type("Site", (), {"id": 1, "name": "Shop", "domain": "https://shop.example"})
    sent.append(EmailReportsService(None).generate_report_html(site, {
        "period": "Last 7 Days", "start_date": "2026-01-01", "end_date": "2026-01-08",
        "total_pageviews": 9, "unique_visitors": 4, "previous_pageviews": 6, "previous_visitors": 4,
        "daily": [{"date": f"2026-01-0{d}", "views": d} for d in range(2, 9)],
        "top_pages": [{"path": "/", "views": 9}],
        "top_referrers": [{"referrer": "https://www.example.org/", "views": 2}],
        "top_countries": [{"country": "SE", "views": 9}],
    }))
    assert len(sent) == 6
    return sent


def test_no_mail_fetches_anything_when_it_is_opened(sent):
    for page in _every_mail(sent):
        assert not re.search(r"<img|<link|<script|@font-face|@import|url\(|background=", page, re.I), (
            "a mail carries something a mail client would fetch from a server"
        )
        assert set(re.findall(r'(?:src|href)="([^"]+)"', page)) <= set(re.findall(r'<a href="([^"]+)"', page))


def test_every_mail_is_in_the_same_frame(sent):
    for page in _every_mail(sent):
        assert email_layout.NIGHT in page and email_layout.PEACOCK_DEEP in page
        assert "667eea" not in page, "the purple of the old template is back"


def test_the_report_says_which_way_the_week_went(sent):
    report = _every_mail(sent)[-1]
    assert "up 50% on the week before" in report
    assert "same as the week before" in report
    assert "example.org" in report and "https://www.example.org/" not in report


def test_a_code_and_a_name_are_escaped_by_the_pieces():
    assert "<b>" not in email_layout.code("<b>1</b>")
    assert "<b>" not in email_layout.ranking("Pages", [("<b>/x</b>", 1)])
    assert "<b>" not in email_layout.aside("<b>Shop</b>")
