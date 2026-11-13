"""The TOTP arithmetic, against the published vectors.

app/utils/totp.py is written from the standard library rather than taken from
a package, which is only defensible if it is checked against something that
is not itself. These are the test values from the RFCs: if they pass, an
authenticator app and this server agree on what the code is.

Few functions with many assertions each, on purpose: the README and the home
page state a test count, and sixteen vectors are one fact.
"""
import base64

from app.utils import totp

# Both RFCs use this key, the ASCII string, not its base32 form.
RFC_KEY = b"12345678901234567890"
RFC_SECRET = base64.b32encode(RFC_KEY).decode("ascii")

# RFC 4226, appendix D: counter and six-digit HOTP value.
RFC_4226 = [
    (0, "755224"), (1, "287082"), (2, "359152"), (3, "969429"), (4, "338314"),
    (5, "254676"), (6, "287922"), (7, "162583"), (8, "399871"), (9, "520489"),
]

# RFC 6238, appendix B, SHA-1 rows: unix time and eight-digit TOTP value.
RFC_6238 = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]

NOW = 1_700_000_000


def test_the_codes_match_rfc_4226_and_rfc_6238():
    """HOTP by counter, then TOTP by time: through the raw function at eight
    digits, as the RFC prints them, and through the one the login calls at six."""
    for counter, expected in RFC_4226:
        assert totp.hotp(RFC_KEY, counter) == expected, f"counter {counter}"

    for timestamp, expected in RFC_6238:
        step = totp.step_at(timestamp)
        six = expected[-6:]

        assert totp.hotp(RFC_KEY, step, digits=8) == expected, f"time {timestamp}"
        assert totp.code_at(RFC_SECRET, step) == six, f"time {timestamp}"
        assert totp.matching_step(RFC_SECRET, six, timestamp=timestamp) == step, (
            f"the RFC's own code for {timestamp} is not accepted at {timestamp}"
        )


def test_a_code_is_accepted_one_step_either_side_and_no_further():
    step = totp.step_at(NOW)

    for offset in (-1, 0, 1):
        code = totp.code_at(RFC_SECRET, step + offset)
        assert totp.matching_step(RFC_SECRET, code, timestamp=NOW) == step + offset
    for offset in (-2, 2, 10, -10):
        code = totp.code_at(RFC_SECRET, step + offset)
        assert totp.matching_step(RFC_SECRET, code, timestamp=NOW) is None, (
            f"a code {offset} steps away was accepted"
        )

    # A step already used is not accepted again, nor is one before it.
    code = totp.code_at(RFC_SECRET, step)
    assert totp.matching_step(RFC_SECRET, code, after_step=step - 1, timestamp=NOW) == step
    assert totp.matching_step(RFC_SECRET, code, after_step=step, timestamp=NOW) is None
    assert totp.matching_step(RFC_SECRET, code, after_step=step + 1, timestamp=NOW) is None


def test_anything_else_is_refused():
    right = totp.code_at(RFC_SECRET, totp.step_at(NOW))
    live = {totp.code_at(RFC_SECRET, totp.step_at(NOW) + o) for o in (-1, 0, 1)}
    wrong = next(
        candidate for candidate in (f"{(int(right) + n) % 1_000_000:06d}" for n in range(1, 9))
        if candidate not in live
    )

    assert totp.matching_step(RFC_SECRET, wrong, timestamp=NOW) is None
    # Full-width digits are what some phone keyboards produce.
    for junk in ["", "12345", "1234567", "abcdef", "12 456", "１２３４５６", None]:
        assert totp.matching_step(RFC_SECRET, junk, timestamp=NOW) is None, repr(junk)
    assert totp.matching_step("not base32 !", right, timestamp=NOW) is None


def test_a_new_secret_and_the_uri_an_authenticator_reads():
    secret = totp.generate_secret()

    assert len(secret) == 32
    assert len(base64.b32decode(secret)) == 20, "not 160 bits"
    assert totp.generate_secret() != secret

    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "anna+test@example.com", "Argus Metrics")
    assert uri.startswith("otpauth://totp/Argus%20Metrics%3Aanna%2Btest%40example.com?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=Argus%20Metrics" in uri
    assert "digits=6" in uri and "period=30" in uri and "algorithm=SHA1" in uri
