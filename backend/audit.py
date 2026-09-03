"""Which routes declare a row-level security context, and which do not.

Asking where set_rls_context appears finds the paths that have it. This asks
the other question, which is the one that matters: which authenticated entry
points reach a policied table without declaring who they are.
"""
import inspect
from app.main import app
from app.routers import auth, analytics, dashboard

# Dependencies known to declare a context.
DECLARES = {
    auth.get_current_user,
    analytics.get_current_user_or_token,
    analytics.use_tracking_context,
}

PUBLIC_PREFIXES = ("/health", "/static", "/docs", "/openapi", "/redoc", "/favicon")


def declares(route):
    seen = set()
    stack = list(getattr(route, "dependant", None).dependencies) if getattr(route, "dependant", None) else []
    if getattr(route, "dependant", None) and route.dependant.call in DECLARES:
        return True
    while stack:
        dep = stack.pop()
        if dep.call in DECLARES:
            return True
        if id(dep) in seen:
            continue
        seen.add(id(dep))
        stack.extend(dep.dependencies)
    return False


missing = []
for route in app.routes:
    path = getattr(route, "path", "")
    if not path or path.startswith(PUBLIC_PREFIXES):
        continue
    if declares(route):
        continue
    src = ""
    fn = getattr(route, "endpoint", None)
    if fn is not None:
        try:
            src = inspect.getsource(fn)
        except Exception:
            src = ""
    # A route may declare the context in its own body instead of via a dependency.
    inline = "set_rls_context" in src
    missing.append((path, sorted(getattr(route, "methods", ["WS"])), inline))

print(f"{'route':<58} {'methods':<16} declares in body")
for path, methods, inline in sorted(missing):
    mark = "yes" if inline else "NO"
    print(f"  {path:<56} {','.join(methods):<16} {mark}")
print(f"\nroutes with no context from a dependency: {len(missing)}")
print(f"of those, none in the body either:        {sum(1 for _,_,i in missing if not i)}")
