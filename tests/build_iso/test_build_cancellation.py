# intentional-log: the fake child prints one line so the reader has something
# to consume before it stalls; that is the condition under test.
"""Cancellation reaches the child that is actually running."""

import subprocess
import sys
import threading
import time
from pathlib import Path

import gitrepo.build_iso.core.iso_builder as iso_builder_module
from gitrepo.build_iso.core.iso_builder import ISOBuilder


PROGRESS_DIALOG = Path(__file__).parents[2] / "usr/share/gitrepo/build_iso/gui/dialogs/progress_dialog.py"


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def _stalled_child() -> subprocess.Popen:
    """A real child that prints one line and then never speaks again."""
    return subprocess.Popen(
        [sys.executable, "-c", "import sys, time; print('pulling'); sys.stdout.flush(); time.sleep(300)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def test_cancel_terminates_a_pull_that_stopped_producing_output(tmp_path, monkeypatch):
    builder = _builder(tmp_path)
    started = threading.Event()
    child: dict[str, subprocess.Popen] = {}

    def fake_popen(argv, **kwargs):
        child["process"] = _stalled_child()
        started.set()
        return child["process"]

    monkeypatch.setattr(iso_builder_module.subprocess, "Popen", fake_popen)

    outcome: dict[str, bool] = {}
    worker = threading.Thread(target=lambda: outcome.update(pulled=builder._pull_image()), daemon=True)
    worker.start()

    assert started.wait(timeout=10)
    # Give the reader time to block on a line that will never arrive.
    time.sleep(0.5)
    builder.cancel()
    worker.join(timeout=20)

    assert not worker.is_alive(), "cancel must unblock a phase waiting on a stalled child"
    assert outcome["pulled"] is False
    assert child["process"].poll() is not None, "the child must be terminated, not left running"
    assert child["process"].returncode is not None, "the child must be reaped, not left as a zombie"


def test_a_child_started_after_cancellation_is_killed_immediately(tmp_path, monkeypatch):
    builder = _builder(tmp_path)
    builder.cancel()
    child = _stalled_child()

    monkeypatch.setattr(iso_builder_module.subprocess, "Popen", lambda argv, **kwargs: child)

    assert builder._pull_image() is False
    assert child.poll() is not None


def test_cancellation_owner_is_released_after_a_normal_phase(tmp_path, monkeypatch):
    builder = _builder(tmp_path)

    monkeypatch.setattr(
        iso_builder_module.subprocess,
        "Popen",
        lambda argv, **kwargs: subprocess.Popen(
            [sys.executable, "-c", "print('done')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ),
    )

    assert builder._pull_image() is True
    # Nothing is left registered, so a later cancel cannot signal a dead pid.
    assert builder._active_process is None


def test_closing_the_progress_dialog_cannot_detach_a_running_build():
    source = PROGRESS_DIALOG.read_text(encoding="utf-8")
    close_handler = source.split("def _on_close_request", 1)[1].split("def _stop_timer", 1)[0]

    # Closing while running routes through the same confirmation as the button.
    assert "if self._build_running:" in close_handler
    assert "self._on_cancel_clicked(None)" in close_handler
    assert "return True" in close_handler
    # A finished dialog releases the timer and the process-wide style handler.
    assert "self._stop_timer()" in close_handler
    assert "self._disconnect_style_manager()" in close_handler


def test_both_progress_dialogs_disconnect_the_shared_style_manager():
    package_dialog = Path(__file__).parents[2] / "usr/share/gitrepo/build_package/gui/dialogs/progress_dialog.py"

    for path in (PROGRESS_DIALOG, package_dialog):
        source = path.read_text(encoding="utf-8")
        assert "self._style_handler = self._style_manager.connect(" in source
        assert "self._style_manager.disconnect(self._style_handler)" in source
