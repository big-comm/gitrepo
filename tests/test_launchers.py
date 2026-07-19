from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = PROJECT_ROOT / "usr" / "bin"
LAUNCHER_HELPER = PROJECT_ROOT / "usr" / "lib" / "gitrepo" / "launcher.bash"
LAUNCHERS = ("gitrepo", "bpkg", "build-iso", "biso")


def test_launcher_helper_owns_strict_mode_and_python_exec() -> None:
    source = LAUNCHER_HELPER.read_text(encoding="utf-8")

    assert "set -o errexit" in source
    assert "set -o nounset" in source
    assert "set -o pipefail" in source
    assert 'exec /usr/bin/python3 -m "$module" "$@"' in source


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_use_bash_and_the_shared_helper(name: str) -> None:
    source = (BIN_DIR / name).read_text(encoding="utf-8")

    assert source.startswith("#!/usr/bin/bash\n")
    assert "../lib/gitrepo/launcher.bash" in source
    assert source.count("gitrepo_exec_python_module") == 1


@pytest.mark.parametrize("name", ("bpkg", "biso"))
@pytest.mark.parametrize("option", ("--help", "--version"))
def test_cli_launchers_run_from_an_unrelated_directory(tmp_path: Path, name: str, option: str) -> None:
    result = subprocess.run(
        [str(BIN_DIR / name), option],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_gitrepo_rejects_too_many_directories() -> None:
    result = subprocess.run(
        [str(BIN_DIR / "gitrepo"), "one", "two"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "GitRepo accepts at most one directory.\n"


def test_gitrepo_rejects_a_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = subprocess.run(
        [str(BIN_DIR / "gitrepo"), str(missing)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"Not a directory: {missing}\n"
