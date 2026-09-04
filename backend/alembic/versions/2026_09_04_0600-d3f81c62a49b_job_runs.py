"""Record when each scheduled job last ran and whether it worked

Nobody waits for a scheduled job, so it can do nothing for months and the only
symptom is something that should have happened and did not.

That already happened here. The traffic-spike job ran hourly for weeks,
walked every website, found no alert settings because nothing in the interface
could create any, and did nothing at all. It raised no error, because from its
own point of view nothing was wrong.

One row per job. /health reads it, so an uptime check pointed at that endpoint
notices a job that stopped without anyone reading logs.

Revision ID: d3f81c62a49b
Revises: c9e5b1a73d28
Create Date: 2026-09-04 06:00:00.000000

"""
from alembic import op

from app.migration_grants import grant
import sqlalchemy as sa


revision = 'd3f81c62a49b'
down_revision = 'c9e5b1a73d28'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job_name", sa.String(length=64), primary_key=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        # The one that matters. A job failing every night still has a recent
        # last_started_at, which is why both are here.
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    # The jobs write this from the scheduler, which runs as the job context.
    # No row-level security: there is nothing tenant-specific in it, and
    # /health has to read it without a context at all.
    grant("SELECT, INSERT, UPDATE", "job_runs")


def downgrade() -> None:
    op.drop_table("job_runs")
