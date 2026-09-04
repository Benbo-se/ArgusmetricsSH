"""Logging that can be searched, with a request id on every line.

There are over five hundred logging calls in this application and none of them
knows which request it belongs to. When a customer says "it broke around two
o'clock", the log is a flat stream of lines from every request that happened
around two o'clock, interleaved.

A request id fixes that, and it has to arrive without touching five hundred
call sites. A context variable carries it, a filter puts it on every record,
and the existing `logger.info(...)` calls are left exactly as they are.

Two formats. Text stays the default because it is what a person reads while
developing. JSON is for a deployment, where the log is read by a machine
first and a person second, and where `grep` on a wrapped multi-line traceback
is not a search.

The id also goes back in the X-Request-Id response header, so a customer can
quote the number from the page they were looking at and it can be found.
"""
import json
import logging
import sys
from contextvars import ContextVar
from typing import Optional

# Set per request by the middleware. Default rather than raising outside a
# request, because scheduled jobs and the startup sequence log too.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Puts the current request id on every record.

    A filter rather than an adapter, because an adapter would have to be
    threaded through every module that logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Deliberately flat: a log shipper that has to walk nested objects to find a
    level is a log shipper that will be configured wrong.
    """

    # Everything LogRecord sets by itself. Anything else was attached
    # deliberately by a caller and belongs in the output.
    _STANDARD = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self._STANDARD and not key.startswith("_"):
                payload[key] = value

        # default=str so a stray object never turns a log line into a crash
        # inside the logging system, which is a genuinely miserable failure.
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Install the handler. Called once, at import time in main."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(request_id)s] %(name)s - %(levelname)s - %(message)s"
            )
        )

    root = logging.getLogger()
    # Replace rather than add: basicConfig may already have run, and two
    # handlers means every line twice.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def set_request_id(value: Optional[str]) -> str:
    """Adopt an incoming id or mint one.

    A proxy or a load balancer often sets X-Request-Id already, and keeping it
    is what makes a trace continuous across hops. Length-capped and stripped of
    anything unexpected, because it arrives from outside and ends up in a log
    line and a response header.
    """
    import secrets

    if value:
        cleaned = "".join(c for c in value if c.isalnum() or c in "-_")[:64]
        if cleaned:
            request_id_var.set(cleaned)
            return cleaned

    generated = secrets.token_hex(8)
    request_id_var.set(generated)
    return generated
