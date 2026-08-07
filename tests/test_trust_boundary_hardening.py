"""Guards on the shared primitives: credentials, atomic writes, diagnostics."""

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr" / "share"))

from gitrepo.build_iso.core.history_store import BuildHistoryStore  # noqa: E402
from gitrepo.common.atomic_file import AtomicWriteError, atomic_write_text  # noqa: E402
from gitrepo.common.diagnostic_redaction import redact_diagnostic  # noqa: E402


class TestRedaction:
    @pytest.mark.parametrize(
        "secret",
        [
            "ghp_ABCDEFGHIJKL1234",
            "github_pat_11ABCDEFG0123456789abcdef",
        ],
    )
    def test_a_token_never_reaches_the_log(self, secret):
        assert secret not in redact_diagnostic(f"fatal: bad credentials {secret}")

    def test_credentials_in_a_remote_url_are_removed(self):
        line = "fatal: unable to access 'https://someone:github_pat_0123456789abcdefghij@github.com/o/r.git/'"

        redacted = redact_diagnostic(line)

        assert "github_pat_0123456789abcdefghij" not in redacted
        # The host stays, so the message still says which remote failed.
        assert "github.com/o/r" in redacted

    def test_an_ordinary_url_is_left_alone(self):
        line = "Cloning into 'repo' from https://github.com/org/repo.git"

        assert redact_diagnostic(line) == line


class TestAtomicWrite:
    def test_the_failure_message_names_the_cause(self, tmp_path):
        target = tmp_path / "sub" / "file.json"
        target.parent.mkdir()
        target.parent.chmod(0o500)
        try:
            with pytest.raises(AtomicWriteError) as failure:
                atomic_write_text(target, "{}")
        finally:
            target.parent.chmod(0o700)

        # "could not publish /path" alone gives the user nothing to act on.
        # The cause comes from the C library, so it follows the active locale;
        # compare against strerror rather than an English string.
        assert str(failure.value) != f"could not publish {target}"
        assert os.strerror(errno.EACCES) in str(failure.value)

    def test_an_interrupt_leaves_no_temporary_file(self, tmp_path):
        # KeyboardInterrupt is how both CLI apps normally exit; `except
        # Exception` did not catch it, so every interrupted write leaked.
        script = tmp_path / "interrupt.py"
        script.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'usr' / 'share')!r})\n"
            "from gitrepo.common.atomic_file import atomic_write_text\n"
            "class Boom(str):\n"
            "    def __len__(self):\n"
            "        raise KeyboardInterrupt\n"
            f"try:\n    atomic_write_text({str(tmp_path / 'target.json')!r}, Boom('x'))\n"
            "except BaseException:\n    pass\n",
            encoding="utf-8",
        )

        subprocess.run([sys.executable, str(script)], check=False, capture_output=True)

        leftovers = [entry.name for entry in tmp_path.iterdir() if entry.name.startswith(".target.json.")]
        assert leftovers == []

    def test_a_successful_write_still_publishes(self, tmp_path):
        target = tmp_path / "file.json"

        atomic_write_text(target, '{"a": 1}')

        assert target.read_text(encoding="utf-8") == '{"a": 1}'
        assert os.stat(target).st_mode & 0o777 == 0o600


class TestHistoryStore:
    def test_a_recovered_file_stops_blocking_writes(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{not json", encoding="utf-8")
        store = BuildHistoryStore(str(path))

        assert store.load() == []
        assert store.last_error

        # The user deletes the corrupt file; history must start working again.
        path.unlink()
        assert store.load() == []
        assert store.last_error == ""
        assert store.add({"iso": "x"}) is True
