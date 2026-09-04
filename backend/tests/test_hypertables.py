"""The traffic tables are hypertables, and everything they carried survived.

Converting a table is not a local change. These tables carry row-level
security policies, two triggers, and a nightly purge, and none of those
announce it when they stop working:

  - Policies that stopped applying would not raise. Queries would simply start
    returning other customers' rows.
  - The trigger that fills owner_email would not raise either. It would write
    rows whose owner is NULL, which the policies then hide from everyone, so
    the data would look lost rather than leaked.
  - The purge deleted by ctid, which is a location inside one physical table.
    A hypertable is many, so the same location exists in every chunk. That one
    is not theoretical: on this database, with exactly one row old enough to
    purge, the old statement deleted seven.

So these tests check behaviour on chunks, not the catalog. Asserting that
pg_policies still has four rows would have passed in every one of those cases.
"""
import pytest
from sqlalchemy import text

HYPERTABLES = [
    "pageviews",
    "custom_events",
    "goal_conversions",
    "funnel_events",
    "ecommerce_events",
]


def _is_hypertable(db, table):
    return bool(
        db.execute(
            text(
                "SELECT 1 FROM timescaledb_information.hypertables "
                " WHERE hypertable_name = :t"
            ),
            {"t": table},
        ).scalar()
    )


class TestTheConversionHappened:
    @pytest.mark.parametrize("table", HYPERTABLES)
    def test_the_table_is_partitioned(self, db, table):
        assert _is_hypertable(db, table), (
            f"{table} is not a hypertable. The extension was installed and "
            "unused for the whole life of this project; do not let it go back."
        )

    def test_ecommerce_events_was_converted_too(self, db):
        """It was the exception, and then it was not.

        Its unique index enforced one purchase per transaction_id, which a
        hypertable cannot carry without the partitioning column in it, and
        adding the timestamp would have let the same transaction count twice.
        The guarantee moved to ecommerce_transactions instead, and the table
        followed the other four. test_ecommerce_dedup covers the guarantee.
        """
        assert _is_hypertable(db, "ecommerce_events")

    def test_compression_is_off_everywhere(self, db):
        """TimescaleDB refuses compression on a table with row security.

        The isolation guarantee is worth more than the disk. If someone turns
        compression on later, they will have had to drop the policies to do
        it, and this fails.
        """
        compressed = db.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                " WHERE compression_enabled"
            )
        ).scalars().all()
        assert not compressed, (
            f"compression is enabled on {compressed}, which cannot coexist "
            "with row-level security. Check the policies are still there."
        )


class TestWhatTheTablesStillCarry:
    @pytest.mark.parametrize("table", HYPERTABLES)
    def test_row_security_is_still_on(self, db, table):
        enabled = db.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"),
            {"t": table},
        ).scalar()
        assert enabled is True

    @pytest.mark.parametrize("table", HYPERTABLES)
    def test_the_policies_are_still_there(self, db, table):
        count = db.execute(
            text("SELECT count(*) FROM pg_policies WHERE tablename = :t"),
            {"t": table},
        ).scalar()
        assert count == 4, f"{table} has {count} policies, expected 4"

    def test_owner_email_is_still_filled_in_on_a_chunk(self, client, website, db):
        """The policies read owner_email, so losing this trigger hides data.

        Goes through the tracking endpoint rather than inserting directly,
        because the point is that the trigger fires on the path that real
        traffic takes.
        """
        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/chunked"},
        )
        assert response.status_code == 200

        row = db.execute(
            text(
                "SELECT owner_email, tableoid::regclass::text AS rel "
                "  FROM pageviews WHERE path = '/chunked'"
            )
        ).first()

        assert row is not None
        assert row.owner_email == website["email"]
        assert "_hyper_" in row.rel, "the row did not land in a chunk"

    def test_the_usage_counter_still_fires_on_a_chunk(self, client, website, db):
        before = db.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "   AND period_start = date_trunc('month', now())::date"
            ),
            {"e": website["email"]},
        ).scalar() or 0

        client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/counted-chunk"},
        )

        after = db.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "   AND period_start = date_trunc('month', now())::date"
            ),
            {"e": website["email"]},
        ).scalar()
        assert after == before + 1


class TestRetentionDeletesOnlyWhatIsOld:
    """The bug that conversion introduced, and the reason for the rewrite.

    `DELETE ... WHERE ctid IN (SELECT ctid ...)` matched the same physical
    location in every chunk. This is the test that would have caught it.
    """

    def _insert(self, db, website, path, age_days):
        db.execute(
            text(
                "INSERT INTO pageviews (website_id, path, \"timestamp\", visitor_hash) "
                "VALUES (:w, :p, now() - make_interval(days => :d), :h)"
            ),
            {"w": website["id"], "p": path, "d": age_days, "h": f"hash-{path}"},
        )

    def test_one_old_row_does_not_take_current_rows_with_it(
        self, db, website, monkeypatch
    ):
        from app.config import settings
        from app.services.cleanup_service import CleanupService

        # One row old enough to purge, and several current ones. The current
        # rows are spread across days so they do not all share a chunk, which
        # is what made the ctid collision possible in the first place.
        self._insert(db, website, "/retention-old", 400)
        for day in (1, 8, 15, 22, 29):
            self._insert(db, website, f"/retention-keep-{day}", day)
        db.commit()

        before = db.execute(
            text("SELECT count(*) FROM pageviews WHERE path LIKE '/retention-%'")
        ).scalar()
        assert before == 6

        monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 365)
        CleanupService(db).purge_old_event_data()

        remaining = db.execute(
            text(
                "SELECT path FROM pageviews WHERE path LIKE '/retention-%' "
                " ORDER BY path"
            )
        ).scalars().all()

        assert "/retention-old" not in remaining, "the old row should have gone"
        assert len(remaining) == 5, (
            f"expected the 5 current rows to survive, got {remaining}. "
            "This is the ctid collision: a delete keyed on a physical location "
            "matches that location in every chunk."
        )

    def test_nothing_is_deleted_when_retention_is_off(self, db, website, monkeypatch):
        from app.config import settings
        from app.services.cleanup_service import CleanupService

        self._insert(db, website, "/retention-ancient", 5000)
        db.commit()

        monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 0)
        CleanupService(db).purge_old_event_data()

        still_there = db.execute(
            text("SELECT count(*) FROM pageviews WHERE path = '/retention-ancient'")
        ).scalar()
        assert still_there == 1, "retention is off; nothing should have been purged"
