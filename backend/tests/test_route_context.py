"""Every route either declares a security context or is listed here as not needing one.

This started as a one-off audit and became a test, because the audit found
three bugs and nothing would have caught the fourth.

The question it asks is the one that matters, and the one I did not ask before
shipping the row-level security policies: not where set_rls_context appears,
but where it is missing. A route that reaches a policied table without
declaring who it is acting as reads nothing and writes nothing, silently, and
returns 200 the whole time. It is invisible in development, where the app
connects as the table owner and policies never apply.

Adding a route now forces a decision. Either it declares a context, or it goes
in EXEMPT with a reason. There is no third option that passes.
"""
import inspect

import pytest

from app.main import app
from app.routers import analytics, auth

# Dependencies that declare a context for everything beneath them.
DECLARING_DEPENDENCIES = {
    auth.get_current_user,
    analytics.get_current_user_or_token,
    analytics.use_tracking_context,
}

# Routes that legitimately declare nothing, each with the reason. A route
# belongs here only if it touches no policied table, or reaches one through a
# SECURITY DEFINER function because its caller has no identity to declare.
#
# Keyed by method and path, not by path alone. /logout has both a GET that
# clears a cookie and a POST that authenticates first, and a path-only
# exemption would have covered the POST too, which is exactly how a future
# route slips through a guard like this one.
EXEMPT = {
    # Static pages and generated files: no database at all.
    "GET /": "marketing page",
    "GET /login": "page",
    "GET /signup": "page",
    "GET /reset": "page",
    "GET /verify": "page",
    "GET /logout": "clears the cookie and redirects",
    "POST /logout": "deletes the session row and clears the cookie; sessions is not policied",
    "GET /robots.txt": "generated file",
    "GET /sitemap.xml": "generated file",
    "GET /favicon.ico": "static file",
    "GET /health": "pings the connection; touches no policied table",
    # Authentication itself, which runs before anyone has an identity. These
    # touch users and sessions, neither of which is policied.
    "POST /api/v1/auth/login": "establishes the identity a context would need",
    "POST /api/v1/auth/signup": "creates the user",
    "GET /api/v1/auth/verify": "verifies by token, not by session",
    "POST /api/v1/auth/verify-code": "verifies by code",
    "POST /api/v1/auth/resend-verification": "by email address",
    "POST /api/v1/auth/request-reset": "by email address",
    "POST /api/v1/auth/set-password": "by reset token",
    "GET /api/v1/auth/password-rules": "static rules, no database",
    # A token in the URL is the credential, and its holder is not logged in.
    # Each of these resolves through a SECURITY DEFINER function instead.
    "GET /accept-invite": "invitation page, resolves via argus_resolve_invite_token",
    # Counts rows and reads job_runs, none of it tenant-specific, and it has
    # no user to declare a context for. Gated on a token instead, and answers
    # 404 without one.
    "GET /metrics": "aggregate counts only, no tenant data, token-gated",
    # Declares one, but from inside the service rather than as a dependency,
    # because the context it declares is the account this call is creating:
    # there is no identity to declare on the way in. It resolves the token
    # through argus_resolve_invite_token, creates the user, and only then sets
    # a user context for that address before touching website_members.
    "POST /api/v1/auth/accept-invite": (
        "resolves via argus_resolve_invite_token, then declares a user context "
        "for the address it just created"
    ),
    "GET /api/v1/websites/invites/{token}": "same, as JSON",
    "GET /api/v1/dashboard-password/check/{share_token}": (
        "public share link, resolves via argus_resolve_share_token"
    ),
    "POST /api/v1/dashboard-password/verify/{share_token}": "same",
    "POST /public/{share_token}": "same; the GET declares a public context inline",
}


def _declares_via_dependency(route):
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    if dependant.call in DECLARING_DEPENDENCIES:
        return True

    stack, seen = list(dependant.dependencies), set()
    while stack:
        dep = stack.pop()
        if dep.call in DECLARING_DEPENDENCIES:
            return True
        if id(dep) in seen:
            continue
        seen.add(id(dep))
        stack.extend(dep.dependencies)
    return False


def _declares_inline(route):
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    try:
        return "set_rls_context" in inspect.getsource(endpoint)
    except (OSError, TypeError):
        return False


def _keys(route, path):
    """Every "METHOD /path" this route answers."""
    methods = getattr(route, "methods", None) or {"WS"}
    return [f"{m} {path}" for m in sorted(methods) if m != "HEAD"]


def _routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path or path.startswith("/static"):
            continue
        # Framework surface, not application surface: FastAPI registers the
        # docs and schema routes itself, and only outside production, so
        # matching on their module is steadier than matching on their paths.
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__module__", "").startswith(("fastapi", "starlette")):
            continue
        yield route, path


def test_every_route_declares_a_context_or_is_exempt():
    undeclared = sorted(
        {
            key
            for route, path in _routes()
            if not _declares_via_dependency(route)
            and not _declares_inline(route)
            for key in _keys(route, path)
            if key not in EXEMPT
        }
    )

    assert not undeclared, (
        "These routes reach a handler without declaring a row-level security "
        "context:\n  " + "\n  ".join(undeclared) + "\n\n"
        "A route with no context reads nothing from any policied table and "
        "returns 200 while doing it. Either declare one (see "
        "use_tracking_context or get_current_user), resolve through a "
        "SECURITY DEFINER function if the caller has no identity, or add the "
        "route to EXEMPT in this file with the reason."
    )


def test_the_exempt_list_has_no_stale_entries():
    """An exemption that no longer applies is worse than none.

    It silently covers whatever route later takes that path.
    """
    live = {key for route, path in _routes() for key in _keys(route, path)}
    stale = sorted(set(EXEMPT) - live)

    assert not stale, (
        "EXEMPT lists routes that no longer exist:\n  " + "\n  ".join(stale)
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/analytics/track",
        "/api/v1/analytics/track-event",
        "/api/v1/analytics/track-ecommerce",
        "/api/v1/revenue/track",
    ],
)
def test_the_tracking_endpoints_declare_the_tracking_context(path):
    """Named explicitly, because /revenue/track was the one that did not.

    Its inserts were refused by policy while every other tracking endpoint
    worked, and nothing said so.
    """
    matching = [route for route, p in _routes() if p == path]
    assert matching, f"{path} is not registered"

    for route in matching:
        assert _declares_via_dependency(route), (
            f"{path} does not declare the tracking context"
        )
