"""The Content-Security-Policy, and the thing that used to make it pointless.

script-src carried 'unsafe-eval' because stock Alpine compiles every x-*
attribute with new AsyncFunction. One directive re-permitted the whole class of
attack the policy exists to stop, so the policy was decoration.

Two tests matter here and they protect each other:

  - the header must not name any unsafe source
  - no template may contain an expression the CSP build cannot evaluate

Without the second, the first passes while the dashboard is quietly broken:
Alpine's CSP build does not throw on an expression it cannot read, it warns to
the console and renders nothing. A page would load, look almost right, and have
a dead dropdown.
"""
import pathlib
import re

import pytest

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"

# The CSP build's whole grammar: completeScope[expression]. One bare name,
# optionally negated. No dots, no operators, no calls, no literals.
BARE_NAME = re.compile(r"^!?[A-Za-z_$][\w$]*$")

# Attributes at the start of a line have whitespace before them, and \b does
# not match between a space and a colon. Getting this wrong hid 29 expressions
# the first time.
ALPINE_ATTR = re.compile(
    r'(?<![\w-])(x-[\w:.-]+|@[\w:.-]+|:[\w:.-]+)\s*=\s*"([^"]*)"'
)

# x-transition takes CSS classes, not expressions. The rest hold no expression
# at all.
NOT_EXPRESSIONS = {"x-cloak", "x-ref", "x-id"}


def _alpine_expressions():
    """Every Alpine expression in every template, with where it came from."""
    for path in sorted(TEMPLATES.rglob("*.html")):
        for match in ALPINE_ATTR.finditer(path.read_text()):
            attribute, expression = match.group(1), match.group(2).strip()
            if attribute.startswith("x-transition") or attribute in NOT_EXPRESSIONS:
                continue
            if attribute == "x-for":
                # "item in items": only the collection is evaluated.
                expression = re.split(r"\s+in\s+", expression)[-1].strip()
            yield path.relative_to(TEMPLATES), attribute, expression


class TestTheHeader:
    def test_no_unsafe_source_anywhere_in_the_policy(self, client):
        response = client.get("/login")
        policy = response.headers["Content-Security-Policy"]

        assert "unsafe-eval" not in policy, (
            "'unsafe-eval' is back. Stock Alpine needs it and the CSP build "
            "does not; check which build base.html loads."
        )
        assert "unsafe-inline" not in policy.split("style-src")[0], (
            "script-src has 'unsafe-inline' again, which lets an injected "
            "<script> run regardless of the nonce."
        )

    def test_scripts_are_limited_to_this_origin_and_the_nonce(self, client):
        policy = client.get("/login").headers["Content-Security-Policy"]

        script_src = [
            part.strip()
            for part in policy.split(";")
            if part.strip().startswith("script-src")
        ]
        assert script_src, "there is no script-src at all"

        sources = script_src[0].replace("script-src", "").split()
        assert "'self'" in sources
        assert any(s.startswith("'nonce-") for s in sources)
        assert not any("unsafe" in s for s in sources)

    def test_the_nonce_changes_between_requests(self, client):
        """A fixed nonce is the same as no nonce."""
        first = client.get("/login").headers["Content-Security-Policy"]
        second = client.get("/login").headers["Content-Security-Policy"]
        assert first != second


class TestTheTemplatesStayWithinTheGrammar:
    def test_every_alpine_expression_is_a_bare_name(self):
        """The check that keeps the header honest.

        A failure here is not style. Alpine's CSP build warns to the console
        and renders nothing for an expression it cannot read, so the page still
        loads and the control silently does not work.
        """
        offenders = [
            f"{path}: {attribute}=\"{expression}\""
            for path, attribute, expression in _alpine_expressions()
            if not BARE_NAME.match(expression)
        ]

        assert not offenders, (
            "these expressions cannot be evaluated by Alpine's CSP build:\n  "
            + "\n  ".join(offenders)
            + "\n\nMove the logic into a component in alpine-components.js and "
            "name a getter or method here. See that file's header for why."
        )

    def test_there_are_expressions_to_check(self):
        """Guards against the scan quietly matching nothing.

        A regex that stops matching turns the test above into a test that
        always passes, which is worse than not having it.
        """
        found = list(_alpine_expressions())
        assert len(found) > 200, (
            f"only {len(found)} Alpine expressions found; the scan is probably "
            "broken rather than the templates being empty."
        )

    def test_no_template_loads_the_standard_alpine_build(self):
        base = (TEMPLATES / "base.html").read_text()
        assert "alpine-csp.min.js" in base
        assert "/static/js/alpine.min.js" not in base, (
            "base.html loads the standard Alpine build, which needs "
            "'unsafe-eval'. Load alpine-csp.min.js instead."
        )


class TestComponentsAreRegistered:
    """Every x-data name must exist in the JavaScript.

    x-data="typoName" is not an error either: Alpine warns and the whole
    subtree has no state.
    """

    @staticmethod
    def _registered_components():
        static = TEMPLATES.parent / "static" / "js"
        names = set()
        for path in static.glob("*.js"):
            names |= set(re.findall(r"Alpine\.data\(\s*'([^']+)'", path.read_text()))
        return names

    def test_every_x_data_names_a_registered_component(self):
        registered = self._registered_components()
        assert registered, "no Alpine.data registrations found at all"

        missing = []
        for path in sorted(TEMPLATES.rglob("*.html")):
            for match in re.finditer(r'x-data="([^"]*)"', path.read_text()):
                name = match.group(1).strip()
                if not BARE_NAME.match(name):
                    missing.append(f"{path.relative_to(TEMPLATES)}: x-data=\"{name}\" is not a bare name")
                elif name not in registered:
                    missing.append(f"{path.relative_to(TEMPLATES)}: x-data=\"{name}\" is not registered")

        assert not missing, "\n  ".join([""] + missing)
