"""The four tabbed cards on the analytics page, and the names in them.

The page was fifteen cards; the lists are now tabs in four. Grouping moves
markup around, and what can go wrong is quiet: a tab with no panel behind it
shows an empty card, a list left out of every card is simply gone, and a
country shown by name but filtered by name filters nothing, because the
stored value is the code.

The cases are tables walked inside a test, as elsewhere in this suite: the
README states a test count, and twenty rows of one table are one thing
checked.
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.routers.dashboard import country_flag, referrer_name
from app.services import visitor_dimensions as vd
from app.services.country_names import COUNTRY_NAMES, country_name

CARDS = {
    "sources": ["referrer", "channels", "campaigns"],
    "pages": ["page", "entry", "exit", "hostname"],
    "locations": ["country", "language"],
    "devices": ["device", "browser", "browser_version", "os", "os_version", "screen"],
}


def _pageview(db, website_id, **values):
    names = "".join(f", {name}" for name in values)
    binds = "".join(f", :{name}" for name in values)
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp"'
            f"{names}) VALUES (:w, '/', 'v', :t{binds})"
        ),
        {"w": website_id, "t": datetime.now(timezone.utc) - timedelta(hours=1), **values},
    )
    db.commit()


def test_a_country_code_reads_as_its_name():
    cases = [
        ("SE", "Sweden"), ("se", "Sweden"), ("US", "United States"),
        ("GB", "United Kingdom"), ("KR", "South Korea"),
        # A code the table does not know is shown as it was stored.
        ("ZZ", "ZZ"),
        # And nothing is ever the word None.
        (None, "Unknown"), ("", "Unknown"),
    ]
    for code, name in cases:
        assert country_name(code) == name, code

    for code, name in COUNTRY_NAMES.items():
        assert re.fullmatch(r"[A-Z]{2}", code), code
        assert name and name == name.strip(), code
        assert len(country_flag(code)) == 2, f"{code} has no flag"


def test_a_referrer_reads_as_host_and_path():
    cases = [
        ("https://www.google.com/", "google.com"),
        ("http://www.reddit.com/r/coffee/", "reddit.com/r/coffee"),
        ("https://news.ycombinator.com/item?id=1", "news.ycombinator.com/item"),
        ("https://Example.COM:8443/a#b", "example.com/a"),
        # www is only dropped from the front.
        ("https://awww.example.com", "awww.example.com"),
        # Not a web address: shown as stored.
        ("android-app://com.slack", "android-app://com.slack"),
        ("(Direct)", "(Direct)"),
        (None, ""),
    ]
    for stored, shown in cases:
        assert referrer_name(stored) == shown, stored


class TestThePage:
    def test_every_list_is_a_tab_with_a_panel_behind_it(self, owner_client, db, website):
        _pageview(db, website["id"], country="SE", referrer="https://www.google.com/",
                  browser="Chrome", device_type="desktop")

        response = owner_client.get(f"/dashboard/website/{website['id']}")

        assert response.status_code == 200, response.text[:500]
        body = response.text
        for card, tabs in CARDS.items():
            for tab in tabs:
                marker = f'data-card="{card}" data-tab="{tab}"'
                assert body.count(marker) == 2, (
                    f"{card}/{tab}: expected one tab and one panel, "
                    f"found {body.count(marker)} elements"
                )
            # One tab per card is the one shown before any script has run.
            chosen = re.findall(
                rf'data-card="{card}" data-tab="[a-z_]+"\s+aria-selected="true"', body
            )
            assert len(chosen) == 1, (card, chosen)

        # Every visitor dimension has a home in one of the cards.
        homed = {tab for tabs in CARDS.values() for tab in tabs}
        assert set(vd.DIMENSION_NAMES) <= homed

    def test_a_country_is_named_and_filtered_by_its_code(self, owner_client, db, website):
        _pageview(db, website["id"], country="SE")
        page = f"/dashboard/website/{website['id']}"

        body = owner_client.get(page).text

        row = re.search(
            r'data-filter="country" data-value="SE".*?</div>', body, re.S
        ).group(0)
        assert "Sweden" in row
        assert 'title="SE"' in row, "the code is no longer anywhere a person can find it"

        filtered = owner_client.get(page + "?country=SE").text
        chip = re.search(r'data-dimension-chip="country".*?</button>', filtered, re.S).group(0)
        assert "Sweden" in chip
        assert 'data-filter="country"' in chip, "the chip cannot remove its filter"
        # The tab holding the filtered list says so, for when another is in front.
        assert re.search(
            r'data-card="locations" data-tab="country"[^>]*class="has-filter"', filtered
        )
        assert not re.search(
            r'data-card="locations" data-tab="language"[^>]*class="has-filter"', filtered
        )

    def test_channels_and_campaigns_are_rows_without_emoji(self, owner_client, db, website):
        _pageview(db, website["id"], referrer="https://www.google.com/")
        _pageview(db, website["id"], referrer="https://www.facebook.com/")
        _pageview(db, website["id"], utm_source="newsletter", utm_medium="email")
        _pageview(db, website["id"])

        body = owner_client.get(f"/dashboard/website/{website['id']}").text

        panel = re.search(
            r'role="tabpanel"[^>]*data-card="sources" data-tab="channels".*?'
            r'(?=<div role="tabpanel")', body, re.S
        ).group(0)
        for channel in ("Organic Search", "Social", "Direct", "Email"):
            assert channel in panel, channel
        assert panel.count('class="rank-row') == 4
        assert panel.count("<svg") == 4, "a channel row without its icon"
        for emoji in "🔍📱➡📧💰🤖🔗🌐":
            assert emoji not in body, f"{emoji} is back on the page"

        campaigns = re.search(
            r'role="tabpanel"[^>]*data-card="sources" data-tab="campaigns".*?</section>',
            body, re.S,
        ).group(0)
        assert "newsletter" in campaigns and "email" in campaigns
        assert "<table" not in campaigns
