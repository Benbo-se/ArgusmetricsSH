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


def test_ci_actually_has_the_script():
    """Fails in CI if the file the tests below need is not where they look.

    These skipped locally and failed in CI on their first push, because the
    script changed and the tests did not, and a skip reads as green. A skip is
    correct where the file genuinely is not checked out; it is a lie in CI.
    """
    import os

    if not os.environ.get("CI"):
        pytest.skip("only meaningful where the whole repository is checked out")

    assert ARGUS.exists(), f"{ARGUS} is missing in CI, so these tests skip"

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


def run(instance, *args, answer=None):
    """Run the script, never restarting anything.

    `answer` is fed to the prompt, since `admin add` and `admin remove` ask
    rather than taking an address as an argument. They ask because an address
    on the command line is an address that can be pasted from an example, and
    one was: "din-adress@argusmetrics.io" went into a live instance verbatim.
    """
    env = {**os.environ, "ARGUS_NO_RESTART": "1", "ARGUS_CONTAINER": "no-such-container"}
    result = subprocess.run(
        [str(instance / "argus"), *args],
        capture_output=True, text=True, env=env, cwd=str(instance),
        input=answer if answer is not None else "",
    )
    return result.returncode, result.stdout + result.stderr


def with_admins(instance, value):
    """Put addresses in ADMIN_EMAILS directly, so the tests that are about the
    file do not need a running instance to get one in."""
    path = instance / "docker" / ".env"
    path.write_text(path.read_text() + f"\nADMIN_EMAILS={value}\n")


def env_text(instance):
    return (instance / "docker" / ".env").read_text()


class TestAddingAsksRatherThanTakingAnAddress:
    """The failure this shape exists to prevent.

    `admin add you@example.com` accepted anything that looked like an address,
    said "Done, sign in as it", and the address in the example ended up in a
    live instance's configuration. It asks now, and the choices come from the
    accounts that exist, so there is nothing to type wrong.
    """

    def test_it_takes_no_address_argument(self):
        source = ARGUS.read_text()
        add_block = source.split("        add)")[1].split("        remove)")[0]

        assert "choose_account" in add_block, (
            "admin add no longer asks; if it takes an address again, an "
            "example can be pasted into a live instance"
        )
        assert '"${1:-}"' not in add_block, "admin add reads an argument again"

    def test_it_says_so_when_there_are_no_accounts_to_choose_from(self, instance):
        """No container here, so the list is empty. Refusing is the answer:
        an address with no account can never sign in to use the page."""
        code, output = run(instance, "admin", "add", answer="1\n")

        assert code != 0
        assert "No accounts" in output
        assert "bootstrap" in output
        assert "ADMIN_EMAILS=" not in env_text(instance).replace(
            "# ADMIN_EMAILS=", ""
        )


class TestTheFileSurvives:
    """It holds the instance's secrets. Rewriting it badly is the risk."""

    def test_every_other_line_is_untouched(self, instance):
        with_admins(instance, "anna@example.com,bo@bolag.se")
        run(instance, "admin", "remove", answer="1\n")
        after = env_text(instance)

        for line in EXISTING.splitlines():
            if line.startswith("# ADMIN_EMAILS"):
                continue
            assert line in after, f"lost: {line}"

    def test_the_secret_key_is_not_touched(self, instance):
        with_admins(instance, "anna@example.com,bo@bolag.se")
        run(instance, "admin", "remove", answer="1\n")

        assert "SECRET_KEY=a-secret-worth-not-losing" in env_text(instance)

    def test_a_commented_example_is_left_commented(self, instance):
        """Uncommenting it would make the address in the example an
        administrator, which is somebody else's."""
        with_admins(instance, "anna@example.com,bo@bolag.se")
        run(instance, "admin", "remove", answer="1\n")

        assert "# ADMIN_EMAILS=example@example.com" in env_text(instance)

    def test_editing_repeatedly_does_not_duplicate_the_key(self, instance):
        with_admins(instance, "a@example.com,b@example.com,c@example.com")
        for _ in range(2):
            run(instance, "admin", "remove", answer="1\n")

        active = [
            line for line in env_text(instance).splitlines()
            if line.startswith("ADMIN_EMAILS=")
        ]
        assert len(active) == 1, f"the key appears {len(active)} times: {active}"


class TestRemoving:
    def test_it_takes_the_chosen_one_out_and_leaves_the_rest(self, instance):
        with_admins(instance, "anna@example.com,bo@bolag.se")

        code, output = run(instance, "admin", "remove", answer="1\n")

        assert code == 0, output
        text = env_text(instance)
        assert "anna@example.com" not in text
        assert "bo@bolag.se" in text

    def test_it_lists_them_so_there_is_nothing_to_type(self, instance):
        with_admins(instance, "anna@example.com,bo@bolag.se")

        _, output = run(instance, "admin", "remove", answer="2\n")

        assert "anna@example.com" in output and "bo@bolag.se" in output

    def test_a_number_nobody_offered_is_refused(self, instance):
        with_admins(instance, "anna@example.com")

        code, _ = run(instance, "admin", "remove", answer="7\n")

        assert code != 0
        assert "anna@example.com" in env_text(instance)

    def test_something_that_is_not_a_number_is_refused(self, instance):
        with_admins(instance, "anna@example.com")

        code, _ = run(instance, "admin", "remove", answer="anna\n")

        assert code != 0
        assert "anna@example.com" in env_text(instance)

    def test_removing_the_last_one_works(self, instance):
        """It did not. With pipefail, grep exits 1 when it keeps nothing,
        which is exactly what removing the last administrator looks like, and
        set -e abandoned the function before the file was written."""
        with_admins(instance, "anna@example.com")

        code, _ = run(instance, "admin", "remove", answer="1\n")

        assert code == 0
        assert "anna@example.com" not in env_text(instance)

    def test_it_says_so_when_there_is_nobody_to_remove(self, instance):
        code, output = run(instance, "admin", "remove", answer="1\n")

        assert code != 0
        assert "nothing to remove" in output


class TestListing:
    def test_an_empty_setting_says_nobody_can_get_in(self, instance):
        code, output = run(instance, "admin", "list")

        assert code == 0
        assert "Nobody" in output and "404" in output

    def test_it_lists_what_is_configured(self, instance):
        with_admins(instance, "anna@example.com,bo@bolag.se")

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
