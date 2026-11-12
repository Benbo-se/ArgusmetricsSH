"""Traffic channels: which bucket a visit lands in.

The old classifier searched for domain names inside the referrer string, so
't.co' (Twitter's shortener) matched 'chatgpt.com' and every ChatGPT visit was
counted as Social. These tests use the real failure cases, and lookalike hosts
that must not be mistaken for the real thing.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.analytics_query_service import AnalyticsQueryService
from app.services.traffic_sources import classify_channel

OWN = "https://shop.example.com"


class TestClassification:
    @pytest.mark.parametrize("referrer, expected", [
        ("https://chatgpt.com/", "AI Assistants"),
        ("https://claude.ai/chat/abc", "AI Assistants"),
        ("https://www.perplexity.ai/search", "AI Assistants"),
        ("https://gemini.google.com/app", "AI Assistants"),
        ("https://copilot.microsoft.com/", "AI Assistants"),
        ("https://www.google.se/", "Organic Search"),
        ("https://google.co.uk/search?q=x", "Organic Search"),
        ("https://www.google.com", "Organic Search"),
        ("https://ecosia.org/", "Organic Search"),
        ("https://search.brave.com/search?q=x", "Organic Search"),
        ("https://www.startpage.com/", "Organic Search"),
        ("https://t.co/abc", "Social"),
        ("https://l.facebook.com/l.php", "Social"),
        ("https://news.ycombinator.com/", "Referral"),
        ("https://example.org:8443/post", "Referral"),
        ("", "Direct"),
        (None, "Direct"),
        ("about://newtab", "Direct"),
        ("android-app://com.google.android.gm", "Direct"),
        # Own domain, with and without www, a subdomain, and a port.
        ("https://shop.example.com/cart", "Direct"),
        ("https://www.shop.example.com:443/", "Direct"),
        ("https://blog.shop.example.com/", "Direct"),
    ])
    def test_referrer_host(self, referrer, expected):
        assert classify_channel(referrer, own_domain=OWN) == expected

    @pytest.mark.parametrize("referrer", [
        "https://notgoogle.com.evil.test/",
        "https://google.com.evil.test/",
        "https://evilt.co/",
        "https://shop.example.com.evil.test/",
        "https://notchatgpt.com/",
    ])
    def test_lookalikes_are_not_the_real_thing(self, referrer):
        assert classify_channel(referrer, own_domain=OWN) == "Referral"

    def test_ai_source_without_referrer(self):
        assert classify_channel(None, utm_source="chatgpt.com") == "AI Assistants"
        assert classify_channel("", utm_source="ChatGPT") == "AI Assistants"
        assert classify_channel(None, utm_source="newsletter-june") == "Direct"

    def test_utm_medium_is_honoured(self):
        assert classify_channel("https://google.com/", utm_medium="email") == "Email"
        assert classify_channel("https://google.com/", utm_medium="CPC") == "Paid"
        assert classify_channel(None, utm_medium="social") == "Social"

    def test_the_old_substring_bug_is_gone(self):
        # 't.co' is inside 'chatgpt.com'. It must not be Social.
        assert classify_channel("https://chatgpt.com/") != "Social"


class TestDashboard:
    @pytest.fixture
    def add(self, db, website):
        counter = iter(range(10_000))

        def _add(referrer=None, source=None, n=1):
            for _ in range(n):
                db.execute(text(
                    "INSERT INTO pageviews (website_id, path, visitor_hash, referrer, "
                    "utm_source, \"timestamp\") "
                    "VALUES (:w, '/', :h, :r, :s, now())"
                ), {"w": website["id"], "h": f"v{next(counter)}",
                    "r": referrer, "s": source})
            db.commit()
        return _add

    def test_channels_and_top_referrers(self, db, website, add):
        own = website["domain"]
        add("https://chatgpt.com/", n=3)
        add("https://www.google.se/", n=2)
        add("https://google.com/", n=1)
        add(own + "/pricing", n=4)
        add("about://newtab", n=1)
        add("https://" + own.split("//")[1] + ".evil.test/x", n=1)
        add("https://blog.example.org/post", n=1)
        add(None, source="claude.ai", n=2)

        now = datetime.now(timezone.utc)
        stats = AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"],
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=1),
        )
        channels = {c["channel"]: c["views"] for c in stats["traffic_channels"]}
        assert channels == {
            "AI Assistants": 5, "Organic Search": 3, "Direct": 5, "Referral": 2,
        }
        referrers = [r["referrer"] for r in stats["top_referrers"]]
        assert not any(r.startswith(own + "/") for r in referrers), "own domain listed"
        assert referrers.count("https://chatgpt.com/") == 1
        assert any(".evil.test" in r for r in referrers), "lookalike must stay listed"
