"""Schema properties that are easy to break and invisible when broken.

An index nobody wants does not fail anything. It is written on every insert,
it competes for cache, and the only symptom is that writes are slower than
they should be, which nobody measures.

Sixteen of them accumulated here before anyone looked, because
`primary_key=True, index=True` reads like care rather than duplication.
"""
import pytest
from sqlalchemy import text

DUPLICATES = """
SELECT i1.tablename, i1.indexname, i2.indexname
FROM pg_indexes i1
JOIN pg_indexes i2
  ON i1.tablename = i2.tablename
 AND i1.indexname <> i2.indexname
 AND regexp_replace(i1.indexdef, '^.*USING ', '')
   = regexp_replace(i2.indexdef, '^.*USING ', '')
WHERE i1.schemaname = 'public' AND i1.indexname > i2.indexname
ORDER BY 1, 2
"""


def test_no_two_indexes_cover_the_same_columns(engine):
    with engine.connect() as conn:
        duplicates = conn.execute(text(DUPLICATES)).all()

    assert not duplicates, "duplicate indexes:\n  " + "\n  ".join(
        f"{t}: {a} duplicates {b}" for t, a, b in duplicates
    )


def test_no_primary_key_declares_index_true():
    """The source of every one of the sixteen.

    A primary key already has a unique index. Adding index=True makes a second
    one, and the model reads as though it is being careful.
    """
    import pathlib

    offenders = [
        f"{path.name}:{n}"
        for path in pathlib.Path("app/models").glob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if "primary_key=True" in line and "index=True" in line
    ]

    assert not offenders, (
        "index=True on a primary key column creates a duplicate index:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "table,column",
    [
        ("pageviews", "website_id"),
        ("custom_events", "website_id"),
        ("api_tokens", "token"),
        ("users", "email"),
        ("sessions", "token"),
    ],
)
def test_the_columns_that_are_looked_up_are_indexed(engine, table, column):
    """The other half: dropping duplicates must not drop what is used.

    Each of these is a lookup on the hot path. Postgres will seq scan a small
    table whatever indexes exist, so this asks the catalogue rather than the
    planner.
    """
    with engine.connect() as conn:
        covered = conn.execute(
            text(
                "SELECT count(*) FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :t "
                "AND indexdef LIKE '%(' || :c || '%'"
            ),
            {"t": table, "c": column},
        ).scalar()

    assert covered, f"{table}.{column} has no index and is looked up by value"
