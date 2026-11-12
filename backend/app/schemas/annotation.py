"""Schemas for notes on the traffic graph."""
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.models.annotation import MAX_NOTE_LENGTH

#: Outside these a date is a typing mistake, not a day anyone has traffic for.
EARLIEST_DAY = date(2000, 1, 1)
LATEST_DAY = date(2100, 1, 1)


def clean_note(value: str) -> str:
    """One line of text: control characters out, runs of whitespace to one
    space, nothing at either end.

    A note is drawn on a canvas, in a list and in a CSV file. A line break or
    a tab in it does nothing useful in any of them.
    """
    printable = "".join(ch if ch.isprintable() else " " for ch in value)
    return " ".join(printable.split())


class AnnotationWrite(BaseModel):
    """What creating or changing a note takes."""

    day: date = Field(..., description="The day the note marks, in the website's time zone")
    # No max_length here: the limit is on the cleaned text, checked below, so
    # that trailing whitespace does not count against it.
    note: str = Field(..., description=f"The text, at most {MAX_NOTE_LENGTH} characters")

    @field_validator("day")
    @classmethod
    def _day_in_range(cls, value: date) -> date:
        if not (EARLIEST_DAY <= value <= LATEST_DAY):
            raise ValueError("The date is out of range")
        return value

    @field_validator("note")
    @classmethod
    def _note_is_one_line(cls, value: str) -> str:
        value = clean_note(value)
        if not value:
            raise ValueError("A note needs some text")
        if len(value) > MAX_NOTE_LENGTH:
            raise ValueError(f"A note can be at most {MAX_NOTE_LENGTH} characters")
        return value


class AnnotationResponse(BaseModel):
    id: int
    website_id: int
    day: date
    note: str

    class Config:
        from_attributes = True
