"""is_production decides several security switches, so it gets its own test."""
import pytest

from app.config import Settings


def _settings(**overrides):
    # ENVIRONMENT is explicit in every case, because pydantic would otherwise
    # read it from the process environment and the test would be measuring
    # whatever the container happens to be set to.
    base = dict(
        DATABASE_URL="postgresql://u:p@localhost:5432/d",
        SECRET_KEY="x" * 40,
        ENVIRONMENT=None,
    )
    base.update(overrides)
    return Settings(**base)


class TestIsProduction:
    """It gates TrustedHostMiddleware, Secure cookies, the API docs, and
    whether signup may ever return a verification link."""

    @pytest.mark.parametrize("declared", ["production", "PRODUCTION", " prod "])
    def test_declaring_production_wins(self, declared):
        s = _settings(ENVIRONMENT=declared, DEBUG=True, BASE_URL="http://localhost:8020")
        assert s.is_production is True, (
            "a deployment that says it is production is treated as development"
        )

    @pytest.mark.parametrize("declared", ["development", "test", "ci", "staging"])
    def test_declaring_non_production_wins(self, declared):
        s = _settings(ENVIRONMENT=declared, DEBUG=False, BASE_URL="https://argusmetrics.io")
        assert s.is_production is False

    def test_the_old_inference_still_applies_when_nothing_is_declared(self):
        """Existing deployments set neither, and must not change behaviour."""
        assert _settings(DEBUG=False, BASE_URL="https://argusmetrics.io").is_production is True
        assert _settings(DEBUG=True, BASE_URL="https://argusmetrics.io").is_production is False
        assert _settings(DEBUG=False, BASE_URL="http://localhost:8020").is_production is False

    def test_an_unrecognised_value_falls_back_rather_than_guessing(self):
        """A typo must not silently turn production off."""
        s = _settings(ENVIRONMENT="prodction", DEBUG=False, BASE_URL="https://argusmetrics.io")
        assert s.is_production is True


def test_a_bare_postgres_url_names_the_psycopg2_driver():
    """SQLAlchemy 2.1 reads a bare postgresql:// as psycopg 3, which is not
    installed. Every URL in the compose files, CI and the server's .env is
    bare, so the driver is named where the URL is read (#119)."""
    from app.config import pin_psycopg2

    assert pin_psycopg2("postgresql://u:p@h:5432/d") == "postgresql+psycopg2://u:p@h:5432/d"
    assert pin_psycopg2("postgres://u:p@h/d") == "postgresql+psycopg2://u:p@h/d"
    # A driver someone chose is theirs.
    assert pin_psycopg2("postgresql+psycopg://u:p@h/d") == "postgresql+psycopg://u:p@h/d"
