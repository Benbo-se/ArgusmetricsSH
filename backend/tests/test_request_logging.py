"""Every log line carries the request it came from.

There are over five hundred logging calls in this application. When a customer
says "it broke around two o'clock", a log without request ids is a flat stream
of lines from every request that happened around two o'clock, interleaved, and
the useful ones cannot be separated from the rest.

The id rides on a context variable so those five hundred call sites did not
have to change, which also means nothing reminds anyone it is there. These
tests are that reminder.
"""
import json
import logging

import pytest

from app.logging_setup import (
    JsonFormatter,
    RequestIdFilter,
    request_id_var,
    set_request_id,
)


class TestTheResponseCarriesTheId:
    def test_a_request_gets_an_id_back(self, client):
        """So a customer can quote it from the page they were looking at."""
        response = client.get("/health")

        assert response.headers.get("X-Request-Id"), "no request id on the response"

    def test_two_requests_get_different_ids(self, client):
        first = client.get("/health").headers["X-Request-Id"]
        second = client.get("/health").headers["X-Request-Id"]

        assert first != second

    def test_an_incoming_id_is_adopted(self, client):
        """A proxy usually sets one, and keeping it is what makes a trace
        continuous across hops rather than restarting at our door."""
        response = client.get("/health", headers={"X-Request-Id": "upstream-abc-123"})

        assert response.headers["X-Request-Id"] == "upstream-abc-123"

    def test_a_hostile_incoming_id_is_cleaned(self, client):
        """It arrives from outside and ends up in a log line and a header.

        A newline would let a caller forge log entries; a header injection
        would be worse.
        """
        response = client.get(
            "/health", headers={"X-Request-Id": "abc\r\nX-Evil: yes"}
        )

        returned = response.headers["X-Request-Id"]
        assert "\n" not in returned and "\r" not in returned
        assert "X-Evil" not in response.headers

    def test_a_very_long_id_is_capped(self, client):
        response = client.get("/health", headers={"X-Request-Id": "a" * 500})

        assert len(response.headers["X-Request-Id"]) <= 64


class TestTheLogLineCarriesIt:
    def test_the_filter_puts_the_id_on_a_record(self):
        set_request_id("known-id")
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "something happened", None, None
        )

        RequestIdFilter().filter(record)

        assert record.request_id == "known-id"

    def test_outside_a_request_it_is_a_dash_rather_than_an_error(self):
        """Scheduled jobs and the startup sequence log too, and neither has a
        request. A missing id must not raise inside the logging system."""
        request_id_var.set("-")
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "nightly cleanup", None, None
        )

        RequestIdFilter().filter(record)

        assert record.request_id == "-"


class TestJsonFormat:
    def _format(self, record):
        RequestIdFilter().filter(record)
        return json.loads(JsonFormatter().format(record))

    def test_it_produces_one_json_object_per_line(self):
        set_request_id("json-test")
        record = logging.LogRecord(
            "app.test", logging.WARNING, __file__, 1, "disk is filling", None, None
        )

        out = self._format(record)

        assert out["level"] == "WARNING"
        assert out["logger"] == "app.test"
        assert out["request_id"] == "json-test"
        assert out["message"] == "disk is filling"

    def test_extra_fields_survive(self):
        """The reason for JSON at all: a searchable field beats a sentence."""
        set_request_id("json-test")
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "recorded", None, None
        )
        record.website_id = 42

        assert self._format(record)["website_id"] == 42

    def test_a_traceback_is_one_field_not_thirty_lines(self):
        """grep on a wrapped multi-line traceback is not a search."""
        try:
            raise ValueError("database went away")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
            )

        out = self._format(record)

        assert "database went away" in out["exception"]
        assert "\n" in out["exception"], "the traceback lost its structure"

    def test_an_unserialisable_value_does_not_break_logging(self):
        """A crash inside the logging system is a miserable way to lose a log."""
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "odd", None, None
        )
        record.thing = object()

        out = self._format(record)

        assert "thing" in out
