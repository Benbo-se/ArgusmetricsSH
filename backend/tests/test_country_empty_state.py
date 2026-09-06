"""What the dashboard says when there is no country data.

Two bugs, one cause. Country resolution reads a MaxMind database file on this
machine and nothing else, which is what keeps a visitor's address from ever
leaving the server. Without that file every country is NULL, permanently, and
the dashboard handled it twice and got it wrong both times:

  - the countries panel said "No country data yet", which reads as waiting for
    traffic. It was not waiting. It would have said that forever.
  - the live visitor list rendered the country straight into the page, and
    Jinja renders None as the word "None", so every visitor was from None.

The empty state is the part of an interface nobody looks at while building it,
which is exactly why it gets to be wrong for a long time.
"""
import pathlib

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"


@pytest.fixture
def env():
    """A Jinja environment matching the app's, minus the request plumbing.

    Rendering the partials directly rather than driving the whole dashboard:
    the bug is in the templates, and a test that needs a login, a website and
    a pageview to reach two lines of markup is a test that gets deleted.
    """
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    from app.routers.dashboard import templates as app_templates

    environment.filters.update(app_templates.env.filters)
    environment.globals.update(app_templates.env.globals)
    return environment


class TestTheLiveVisitorList:
    def test_an_unresolved_country_is_not_the_word_none(self, env):
        html = env.get_template("dashboard/_live_list.html").render(
            visitors=[{"country": None, "path": "/docs", "time_ago": "6m ago"}]
        )

        assert "None" not in html, (
            "an unresolved country renders as Python's None. Every visitor in "
            "the live list read 'None' on an instance without a GeoIP database."
        )
        assert "Unknown" in html
        assert "/docs" in html

    def test_a_resolved_country_still_shows(self, env):
        html = env.get_template("dashboard/_live_list.html").render(
            visitors=[{"country": "SE", "path": "/", "time_ago": "now"}]
        )
        assert "SE" in html
        assert "Unknown" not in html


class TestGeoipAvailable:
    """The property the empty state branches on."""

    def test_false_when_no_path_is_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", None)
        assert settings.geoip_available is False

    def test_false_when_the_path_points_at_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", "/no/such/GeoLite2-Country.mmdb")
        assert settings.geoip_available is False, (
            "a configured path that does not exist is the same as no country "
            "data, and the dashboard must not claim otherwise"
        )

    def test_true_when_the_file_is_there(self, monkeypatch, tmp_path):
        db = tmp_path / "GeoLite2-Country.mmdb"
        db.write_bytes(b"not really a database, but it exists")
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(db))
        assert settings.geoip_available is True

    def test_it_is_read_per_request_not_once_at_import(self, env, monkeypatch, tmp_path):
        """The global is a callable for a reason.

        An operator adds the file and reloads the page. If the template global
        had captured a value at import, the dashboard would keep telling them
        country data is off until someone restarted the process.

        Only the file is asserted here. The global answers for two sources now,
        an mmdb or the table built from the registries, and the table's half is
        covered in test_ip_country.py against a database it controls; asserting
        False here would fail on any machine that has actually loaded it.
        """
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", None)
        before = env.globals["geoip_available"]()

        db = tmp_path / "GeoLite2-Country.mmdb"
        db.write_bytes(b"x")
        monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(db))

        assert env.globals["geoip_available"]() is True
        assert settings.geoip_available is True, (
            "the file half of the answer no longer responds to the setting"
        )
        assert isinstance(before, bool)


class TestTheCountriesPanelTellsTheTruth:
    """Both dashboards branch, and both must keep branching.

    Scanning the markup rather than rendering the page: these panels sit deep
    inside a template that wants a website, stats and a session, and the thing
    under test is one conditional.
    """

    PAGES = ["dashboard/website.html", "dashboard/public.html",
             "dashboard/cross_domain.html"]

    @pytest.mark.parametrize("page", PAGES)
    def test_the_panel_asks_whether_geoip_is_configured(self, page):
        source = (TEMPLATES / page).read_text()
        assert "geoip_available()" in source, (
            f"{page} no longer distinguishes 'no data yet' from 'this will "
            "never produce data', so its empty state is misleading again"
        )

    # A public share is read by the owner's client, not by whoever holds the
    # .env file, so it gets the same truth without the configuration.
    @pytest.mark.parametrize("page", ["dashboard/website.html",
                                      "dashboard/cross_domain.html"])
    def test_the_unconfigured_branch_names_the_setting(self, page):
        source = (TEMPLATES / page).read_text()
        assert "GEOIP_DB_PATH" in source, (
            f"{page} says country data is off without saying what turns it on"
        )

    def test_the_public_share_says_nothing_about_configuration(self):
        source = (TEMPLATES / "dashboard/public.html").read_text()
        assert "GEOIP_DB_PATH" not in source, (
            "the public dashboard is shown to the owner's visitors, who cannot "
            "act on a setting and did not ask how the server is configured"
        )

    @pytest.mark.parametrize("page", PAGES)
    def test_it_does_not_promise_data_is_coming(self, page):
        """The 'yet' has to sit inside the configured branch.

        A page that says "No country data yet" unconditionally is back to the
        original bug with extra markup around it.
        """
        source = (TEMPLATES / page).read_text()

        # Every occurrence, not the first: these pages carry an empty state per
        # panel, and only the countries one is a promise the server cannot keep.
        for index, part in enumerate(source.split("No country data yet")[:-1]):
            assert "geoip_available()" in part.rsplit("</div>", 3)[-1], (
                f"{page} occurrence {index + 1} says 'yet' before it has "
                "checked whether country data is possible at all"
            )
