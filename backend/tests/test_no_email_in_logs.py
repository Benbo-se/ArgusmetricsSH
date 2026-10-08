"""No log line writes an email address in full.

Most of the code masked addresses with mask_email; a dozen log lines across
five files did not, and the backend log is kept for days (docs/data-map.md,
#144). This reads the source, so a new unmasked line fails here rather than
in a log somebody reads later.
"""
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
# A {placeholder} in a logger f-string whose expression ends in "email".
PLACEHOLDER = re.compile(r"\{([^{}]*email)\}")


def test_every_logged_email_is_masked():
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "logger." not in line:
                continue
            for expression in PLACEHOLDER.findall(line):
                if not expression.strip().startswith(("mask_email(", "_mask(")):
                    offenders.append(f"{path.relative_to(APP.parent)}:{number}: {{{expression}}}")
    assert not offenders, "log lines with an unmasked address:\n" + "\n".join(offenders)
