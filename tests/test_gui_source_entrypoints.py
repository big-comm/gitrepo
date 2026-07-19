"""Contract tests for the source-tree GUI entrypoints."""

import os
import runpy
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARE_ROOT = PROJECT_ROOT / "usr/share"


class ExecRequested(RuntimeError):
    """Stop the test after capturing the requested process replacement."""


@pytest.mark.parametrize(
    ("relative_script", "expected_module"),
    (
        ("gitrepo/build_package/main.py", "gitrepo.build_package.gui.main_gui"),
        ("gitrepo/build_iso/main.py", "gitrepo.build_iso.gui.main_gui"),
    ),
)
def test_main_py_starts_canonical_gui_module(
    monkeypatch: pytest.MonkeyPatch,
    relative_script: str,
    expected_module: str,
) -> None:
    script = SHARE_ROOT / relative_script
    captured: dict[str, object] = {}

    def capture_exec(executable: str, arguments: list[str], environment: dict[str, str]) -> None:
        captured.update(executable=executable, arguments=arguments, environment=environment)
        raise ExecRequested

    monkeypatch.setattr(os, "execve", capture_exec)
    monkeypatch.setattr(sys, "argv", [str(script), "--example"])
    monkeypatch.setenv("PYTHONPATH", "/existing/python/path")

    with pytest.raises(ExecRequested):
        runpy.run_path(str(script), run_name="__main__")

    assert captured["executable"] == sys.executable
    assert captured["arguments"] == [sys.executable, "-m", expected_module, "--example"]
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["PYTHONPATH"] == f"{SHARE_ROOT}{os.pathsep}/existing/python/path"
