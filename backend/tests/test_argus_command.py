"""The operator command, and the part of it that edits a file.

Running this instance had become a set of commands to be handed over one at a
time: the right compose file, the right container name, the right module path,
and a reminder to edit docker/.env and restart afterwards. That is notes, not
an operational story, and notes are how a step gets skipped.

Most of `argus` is a thin passthrough and would only be testing docker. The
part worth testing is `admin`, because it writes to the file that holds the
instance's secrets, and a script that rewrites .env badly is a bad afternoon.
"""
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARGUS = ROOT / "argus"

pytestmark = pytest.mark.skipif(
    not ARGUS.exists(),
    reason=f"{ARGUS} not in this checkout (the development container mounts "
           "only backend/). Expected to run in CI.",
)

EXISTING = """SECRET_KEY=a-secret-worth-not-losing
BASE_URL=https://argusmetrics.io
# ADMIN_EMAILS=example@example.com
DATA_RETENTION_DAYS=730
"""


@pytest.fixture
def instance(tmp_path):
    """A copy of the script beside its own docker/.env, so the real one is
    never the thing under test."""
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / ".env").write_text(EXISTING)
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n")
    script = tmp_path / "argus"
    script.write_bytes(ARGUS.read_bytes())
    script.chmod(0o755)
    return tmp_path


def run(instance, *args):
    """Run the script, never restarting anything."""
    env = {**os.environ, "ARGUS_NO_RESTART": "1"}
    result = subprocess.run(
        [str(instance / "argus"), *args],
        capture_output=True, text=True, env=env, cwd=str(instance),
    )
    return result.returncode, result.stdout + result.stderr


def env_text(instance):
    return (instance / "docker" / ".env").read_text()


class TestAdding:
    def test_it_writes_the_address(self, instance):
        code, _ = run(instance, "admin", "add", "anna@example.com")

        assert code == 0
        assert "ADMIN_EMAILS=anna@example.com" in env_text(instance)

    def test_a_second_address_is_appended(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        run(instance, "admin", "add", "bo@bolag.se")

        assert "ADMIN_EMAILS=anna@example.com,bo@bolag.se" in env_text(instance)

    def test_the_same_address_twice_is_not_two_entries(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        code, output = run(instance, "admin", "add", "ANNA@example.com")

        assert code == 0
        assert "already an administrator" in output
        assert env_text(instance).count("anna@example.com") == 1

    def test_something_that_is_not_an_address_is_refused(self, instance):
        code, output = run(instance, "admin", "add", "just-a-word")

        assert code != 0
        assert "does not look like an address" in output
        assert "ADMIN_EMAILS=" not in env_text(instance).replace(
            "# ADMIN_EMAILS=", ""
        )

    def test_it_asks_which_address(self, instance):
        code, output = run(instance, "admin", "add")

        assert code != 0
        assert "which address" in output


class TestTheFileSurvives:
    """It holds the instance's secrets. Rewriting it badly is the risk."""

    def test_every_other_line_is_untouched(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        after = env_text(instance)

        for line in EXISTING.splitlines():
            if line.startswith("# ADMIN_EMAILS"):
                continue
            assert line in after, f"lost: {line}"

    def test_the_secret_key_is_not_touched(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        run(instance, "admin", "add", "bo@bolag.se")
        run(instance, "admin", "remove", "anna@example.com")

        assert "SECRET_KEY=a-secret-worth-not-losing" in env_text(instance)

    def test_a_commented_example_is_left_commented(self, instance):
        """Uncommenting it would set the address in the example as an
        administrator, which is somebody else's."""
        run(instance, "admin", "add", "anna@example.com")

        assert "# ADMIN_EMAILS=example@example.com" in env_text(instance)
        assert "example@example.com" not in env_text(instance).replace(
            "# ADMIN_EMAILS=example@example.com", ""
        )

    def test_editing_repeatedly_does_not_duplicate_the_key(self, instance):
        for address in ("a@example.com", "b@example.com", "c@example.com"):
            run(instance, "admin", "add", address)

        active = [
            line for line in env_text(instance).splitlines()
            if line.startswith("ADMIN_EMAILS=")
        ]
        assert len(active) == 1, f"the key appears {len(active)} times: {active}"


class TestRemoving:
    def test_it_takes_one_out_and_leaves_the_rest(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        run(instance, "admin", "add", "bo@bolag.se")

        code, _ = run(instance, "admin", "remove", "anna@example.com")

        assert code == 0
        text = env_text(instance)
        assert "anna@example.com" not in text
        assert "bo@bolag.se" in text

    def test_case_does_not_matter(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        run(instance, "admin", "remove", "ANNA@EXAMPLE.COM")

        assert "anna@example.com" not in env_text(instance)


class TestListing:
    def test_an_empty_setting_says_nobody_can_get_in(self, instance):
        code, output = run(instance, "admin", "list")

        assert code == 0
        assert "Nobody" in output and "404" in output

    def test_it_lists_what_is_configured(self, instance):
        run(instance, "admin", "add", "anna@example.com")
        run(instance, "admin", "add", "bo@bolag.se")

        _, output = run(instance, "admin", "list")

        assert "anna@example.com" in output and "bo@bolag.se" in output


class TestTheHelpIsUsable:
    def test_it_runs_with_no_arguments(self, instance):
        code, output = run(instance)

        assert code == 0
        assert "argus - run this Argusmetrics instance" in output

    def test_an_unknown_command_fails_and_shows_the_help(self, instance):
        """Silently doing nothing is how a typo looks like success."""
        code, output = run(instance, "nonsense")

        assert code != 0
        assert "unknown command" in output
        assert "waitlist" in output

    def test_every_dispatched_command_appears_in_the_help(self):
        """A command nobody can discover is one nobody uses."""
        import re

        source = ARGUS.read_text()
        dispatch = source.split("# --- dispatch")[1]
        commands = set(re.findall(r"^\s{4}([a-z]+)\)", dispatch, re.M))
        commands -= {"help"}

        usage = source.split("cat <<'TEXT'")[1].split("TEXT")[0]
        missing = sorted(c for c in commands if c not in usage)

        assert not missing, f"not in the help text: {missing}"
