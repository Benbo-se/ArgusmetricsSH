"""One purchase counts once, and the table is still partitioned by time.

The guarantee used to live in a unique index on ecommerce_events, which is why
that table could not become a hypertable: a hypertable requires the
partitioning column in every unique index, and putting the timestamp in this
one would have let the same transaction count again a second later. Duplicate
revenue is the worst kind of wrong number, because it is the one a customer
checks.

The guarantee now lives in ecommerce_transactions, one narrow row per
purchase, claimed before the event is written. These tests are about the
guarantee and not the mechanism, so they drive the tracking endpoint and count
what came out.
"""
import uuid

import pytest
from sqlalchemy import text

from app.config import settings


def _purchase(client, website, transaction_id, revenue=499.0):
    return client.post(
        "/api/v1/analytics/track-ecommerce",
        json={
            "tracking_code": website["tracking_code"],
            "event_type": "purchase",
            "transaction_id": transaction_id,
            "revenue": revenue,
            "currency": "SEK",
        },
    )


class TestAPurchaseCountsOnce:
    def test_the_same_transaction_twice_records_one_event(self, client, website, db):
        transaction = f"order-{uuid.uuid4().hex[:10]}"

        first = _purchase(client, website, transaction)
        second = _purchase(client, website, transaction)

        assert first.status_code == 200
        assert second.status_code == 200, (
            "a shop retrying a purchase should not get an error: "
            f"{second.text[:200]}"
        )
        assert "duplicate" in second.json()["message"].lower()

        assert db.execute(
            text("SELECT count(*) FROM ecommerce_events WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar() == 1

    def test_the_revenue_is_not_doubled(self, client, website, db):
        """The number a customer would notice."""
        transaction = f"order-{uuid.uuid4().hex[:10]}"

        for _ in range(5):
            _purchase(client, website, transaction, revenue=1000.0)

        total = db.execute(
            text("SELECT coalesce(sum(revenue), 0) FROM ecommerce_events "
                 " WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar()
        assert float(total) == 1000.0

    def test_different_transactions_both_record(self, client, website, db):
        """The guarantee must not become "only one purchase ever"."""
        a = f"order-{uuid.uuid4().hex[:10]}"
        b = f"order-{uuid.uuid4().hex[:10]}"

        assert _purchase(client, website, a).status_code == 200
        assert _purchase(client, website, b).status_code == 200

        assert db.execute(
            text("SELECT count(*) FROM ecommerce_events WHERE transaction_id IN (:a, :b)"),
            {"a": a, "b": b},
        ).scalar() == 2

    def test_the_same_id_on_another_website_is_a_different_purchase(
        self, client, website, second_website, db
    ):
        """Order numbers are only unique within a shop."""
        transaction = f"order-{uuid.uuid4().hex[:10]}"

        assert _purchase(client, website, transaction).status_code == 200
        assert _purchase(client, second_website, transaction).status_code == 200

        assert db.execute(
            text("SELECT count(*) FROM ecommerce_events WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar() == 2


class TestTheClaimAndTheEventStayTogether:
    def test_a_refused_duplicate_writes_nothing_at_all(self, client, website, db):
        transaction = f"order-{uuid.uuid4().hex[:10]}"
        _purchase(client, website, transaction)

        before = db.execute(
            text("SELECT count(*) FROM ecommerce_transactions WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar()

        _purchase(client, website, transaction)

        after = db.execute(
            text("SELECT count(*) FROM ecommerce_transactions WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar()
        assert before == after == 1

    def test_a_claim_exists_for_every_recorded_purchase(self, client, website, db):
        """A purchase with no claim is a purchase that can be counted twice."""
        transaction = f"order-{uuid.uuid4().hex[:10]}"
        _purchase(client, website, transaction)

        assert db.execute(
            text(
                "SELECT count(*) FROM ecommerce_transactions "
                " WHERE transaction_id = :t AND event_type = 'purchase'"
            ),
            {"t": transaction},
        ).scalar() == 1

    def test_an_event_without_a_transaction_id_claims_nothing(self, client, website, db):
        """Browsing events have no order number and need no claim."""
        before = db.execute(
            text("SELECT count(*) FROM ecommerce_transactions")
        ).scalar()

        response = client.post(
            "/api/v1/analytics/track-ecommerce",
            json={
                "tracking_code": website["tracking_code"],
                "event_type": "view_item",
                "product_id": "sku-1",
                "currency": "SEK",
            },
        )
        assert response.status_code == 200

        assert db.execute(
            text("SELECT count(*) FROM ecommerce_transactions")
        ).scalar() == before


class TestTheTableIsPartitioned:
    def test_ecommerce_events_is_a_hypertable_now(self, db):
        assert db.execute(
            text(
                "SELECT count(*) FROM timescaledb_information.hypertables "
                " WHERE hypertable_name = 'ecommerce_events'"
            )
        ).scalar() == 1

    def test_the_old_unique_index_is_gone(self, db):
        """It could not coexist with partitioning, which is the whole point."""
        assert db.execute(
            text(
                "SELECT count(*) FROM pg_indexes "
                " WHERE indexname = 'uq_ecommerce_purchase_txn'"
            )
        ).scalar() == 0

    def test_the_row_lands_in_a_chunk(self, client, website, db):
        transaction = f"order-{uuid.uuid4().hex[:10]}"
        _purchase(client, website, transaction)

        relation = db.execute(
            text(
                "SELECT tableoid::regclass::text FROM ecommerce_events "
                " WHERE transaction_id = :t"
            ),
            {"t": transaction},
        ).scalar()
        assert "_hyper_" in relation


class TestRetentionCleansTheClaims:
    def test_old_claims_are_purged_with_their_events(self, db, website, monkeypatch):
        """Otherwise this is the one table that grows forever."""
        from app.services.cleanup_service import CleanupService

        transaction = f"order-{uuid.uuid4().hex[:10]}"
        db.execute(
            text(
                "INSERT INTO ecommerce_transactions "
                "  (website_id, event_type, transaction_id, first_seen) "
                "VALUES (:w, 'purchase', :t, now() - INTERVAL '400 days')"
            ),
            {"w": website["id"], "t": transaction},
        )
        db.commit()

        monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 365)
        CleanupService(db).purge_old_event_data()

        assert db.execute(
            text("SELECT count(*) FROM ecommerce_transactions WHERE transaction_id = :t"),
            {"t": transaction},
        ).scalar() == 0
