"""A record of when each scheduled job last ran, and whether it worked.

A scheduled job fails differently from a request. Nobody is waiting for a
response, so it can do nothing at all for months and the only symptom is
something that should have happened and did not: data that should have been
deleted, a report that never arrived, an alert that never fired.

That is not hypothetical here. The traffic-spike job ran hourly for weeks,
walked every website, found no alert settings because nothing in the interface
could create any, and did nothing. It reported no error because nothing was
wrong with it.

One row per job, updated in place. /health reads it, so an uptime check
pointed at that endpoint can notice a job that stopped without anyone having
to watch logs.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class JobRun(Base):
    """The last thing each scheduled job did.

    Attributes:
        job_name: The scheduler's id for the job, one row per job
        last_started_at: When it last began, whatever happened next
        last_success_at: When it last finished without raising. This is the
            one that matters: a job failing every night still has a recent
            last_started_at
        last_error: The message from the most recent failure, kept after a
            later success so a flapping job is visible
        consecutive_failures: Reset to zero on success
        last_duration_ms: A job that suddenly takes ten times longer is worth
            seeing before it starts overlapping its own schedule
    """

    __tablename__ = "job_runs"

    job_name = Column(String(64), primary_key=True)
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, server_default="0", default=0)
    last_duration_ms = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<JobRun(job_name='{self.job_name}', "
            f"last_success_at={self.last_success_at}, "
            f"consecutive_failures={self.consecutive_failures})>"
        )
