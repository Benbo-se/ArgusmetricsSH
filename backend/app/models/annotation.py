"""A note on the traffic graph: a day and a line of text.

"New start page", "campaign started": something that explains a change in the
numbers to whoever looks at them later.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from app.database import Base

#: The longest note. It is drawn in a chart tooltip and in a list under the
#: graph, and neither has room for a paragraph.
MAX_NOTE_LENGTH = 200


class Annotation(Base):
    """
    Attributes:
        id: Primary key
        website_id: The website whose graph the note is on
        day: The calendar date the note marks, in the website's time zone.
            A date and not an instant on purpose: "the day we launched" is a
            day on the site's own calendar, it lines up with a point in the
            daily graph without any conversion, and it stays on that day if
            the website's time zone is changed afterwards.
        note: The text, one line, at most MAX_NOTE_LENGTH characters
        created_at: When the note was written
    """

    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    day = Column(Date, nullable=False)
    note = Column(String(MAX_NOTE_LENGTH), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # Always read as "this website's notes between two days".
        Index('idx_annotations_website_day', 'website_id', 'day'),
    )

    def __repr__(self) -> str:
        return f"<Annotation(id={self.id}, website_id={self.website_id}, day={self.day})>"
