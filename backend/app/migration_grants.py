"""Granting to the application role, on databases that have one.

Production runs the application as `argus_app`, an unprivileged role that owns
nothing, which is what makes the row-level security policies apply to it at
all: policies never apply to a table's owner. Development and CI have no such
role. They connect as the owner, so the policies are inert there and a grant
would have nothing to grant to.

A migration that says

    op.execute("GRANT SELECT ON job_runs TO argus_app")

therefore succeeds in production and fails everywhere else with

    ProgrammingError: role "argus_app" does not exist

which is exactly what happened: CI went red for eleven commits and nobody
noticed, because the development database happened to have the role left over
from an earlier experiment. The environment the migration was verified in was
not the environment that runs it.

So grants go through here, where the role's absence is a no-op rather than a
failure. test_schema_hygiene checks that no migration writes a bare one.
"""
from alembic import op

#: The role the application connects as in production. Created by init-db.sh
#: when APP_DB_PASSWORD is set, which the production compose requires and the
#: development compose deliberately leaves unset.
APP_ROLE = "argus_app"


def grant(privileges: str, target: str, role: str = APP_ROLE) -> None:
    """GRANT, but only where the role exists.

    Deliberately silent when it does not. A development database has no
    unprivileged role by design, and a migration is not the place to create a
    login role: that needs a password, which is a deployment's decision and
    not a schema change.

    The quoting is by identifier rather than string literal, so a target like
    "ALL TABLES IN SCHEMA public" still works.
    """
    op.execute(
        f"""
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE 'GRANT {privileges} ON {target} TO {role}';
            END IF;
        END
        $grant$;
        """
    )
