from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import gitrepo.build_iso.core.iso_builder as iso_builder_module
from gitrepo.build_iso.core.iso_builder import (
    ISOBuilder,
    detect_build_substep,
    iter_terminal_records,
    parse_mksquashfs_progress,
    parse_xorriso_progress,
)
from gitrepo.build_iso.gui.dialogs.progress_dialog import (
    BuildProgressDialog,
    build_step_states,
)
from gitrepo.build_iso.gui.dialogs import progress_dialog as progress_dialog_module


def _builder(tmp_path: Path, callbacks: dict | None = None) -> ISOBuilder:
    return ISOBuilder(
        {
            "container_engine": "docker",
            "output_dir": str(tmp_path),
        },
        callbacks,
    )


@pytest.mark.parametrize(
    ("phase", "step_index", "fraction"),
    [
        ("check_engine", 0, 0.0),
        ("check_space", 0, 0.0),
        ("pull_image", 1, 0.08),
        ("container_build", 2, 0.15),
        ("move_files", 3, 0.9),
        ("cleanup", 4, 0.97),
    ],
)
def test_build_phases_map_to_five_stable_steps(phase, step_index, fraction):
    assert ISOBuilder.step_index_for_phase(phase) == step_index
    assert ISOBuilder.total_progress_for_phase(phase) == pytest.approx(fraction)


def test_container_substeps_own_most_of_total_progress():
    assert ISOBuilder.total_progress_for_build_substep("profile") == pytest.approx(0.15)
    assert ISOBuilder.total_progress_for_build_substep("compress", 0.46) == pytest.approx(0.669)
    assert ISOBuilder.total_progress_for_build_substep("image", 0.9931) == pytest.approx(0.898965)
    assert ISOBuilder.total_progress_for_phase("container_build", 1.0) == pytest.approx(0.9)


def test_container_phase_starts_with_profile_substep(tmp_path):
    substeps = []
    progress = []
    builder = _builder(
        tmp_path,
        {
            "on_build_substep": lambda substep, fraction: substeps.append((substep, fraction)),
            "on_progress": lambda fraction, text: progress.append((fraction, text)),
        },
    )

    builder._phase("container_build")

    assert substeps == [("profile", 0.0)]
    assert progress[-1][0] == pytest.approx(0.15)


def test_restarted_squashfs_percentage_never_moves_progress_backwards(monkeypatch, tmp_path):
    monkeypatch.setattr(iso_builder_module, "_", lambda message: message)
    progress = []
    builder = _builder(tmp_path, {"on_progress": lambda fraction, text: progress.append((fraction, text))})

    builder._handle_container_record("[ = ] 10780/13476 80%", replaces_line=True)
    builder._handle_container_record("[ / ] 2695/13476 20%", replaces_line=True)

    assert progress == [(pytest.approx(0.72), "Compressing filesystem — 80%")]


def test_terminal_records_emit_carriage_return_updates_without_waiting_for_newline():
    stream = BytesIO(b"Creating filesystem\n[ / ] 0/13476 0%\r[ = ] 6200/13476 46%\rDone\n")

    assert list(iter_terminal_records(stream)) == [
        ("Creating filesystem", False),
        ("[ / ] 0/13476 0%", True),
        ("[ = ] 6200/13476 46%", True),
        ("Done", False),
    ]


def test_mksquashfs_progress_updates_live_line_and_total_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(iso_builder_module, "_", lambda message: message)
    progress = []
    live_lines = []
    builder = _builder(
        tmp_path,
        {
            "on_progress": lambda fraction, text: progress.append((fraction, text)),
            "on_live_log": lambda color, text: live_lines.append((color, text)),
        },
    )

    builder._handle_container_record("[ = ] 6200/13476 46%", replaces_line=True)

    assert live_lines == [("white", "[ = ] 6200/13476 46%")]
    assert progress[-1][0] == pytest.approx(0.669)
    assert progress[-1][1] == "Compressing filesystem — 46%"


def test_xorriso_progress_updates_image_substep_and_total_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(iso_builder_module, "_", lambda message: message)
    progress = []
    substeps = []
    builder = _builder(
        tmp_path,
        {
            "on_progress": lambda fraction, text: progress.append((fraction, text)),
            "on_build_substep": lambda substep, fraction: substeps.append((substep, fraction)),
        },
    )

    builder._handle_container_record("xorriso : UPDATE : 99.31% done", replaces_line=True)

    assert substeps[-1] == ("image", pytest.approx(0.9931))
    assert progress[-1][0] == pytest.approx(0.898965)
    assert progress[-1][1] == "Creating ISO image — 99%"


def test_installing_xorriso_package_does_not_start_iso_image_substep(tmp_path):
    substeps = []
    progress = []
    builder = _builder(
        tmp_path,
        {
            "on_build_substep": lambda substep, fraction: substeps.append((substep, fraction)),
            "on_progress": lambda fraction, text: progress.append((fraction, text)),
        },
    )

    builder._handle_container_record("==> Prepare [Base installation] (rootfs)", replaces_line=False)
    progress_after_system_marker = list(progress)
    builder._handle_container_record("installing xorriso...", replaces_line=False)
    builder._handle_container_record("Packages (124) squashfs-tools  xorriso", replaces_line=False)

    assert substeps == [("system", 0.0)]
    assert progress == progress_after_system_marker


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("[ / ] 0/13476 0%", 0.0),
        ("[ = ] 6200/13476 46%", 0.46),
        ("not a progress line", None),
    ],
)
def test_mksquashfs_progress_parser(line, expected):
    assert parse_mksquashfs_progress(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("xorriso : UPDATE : 99.31% done", 0.9931),
        ("xorriso : UPDATE : 100.00% done", 1.0),
        ("not xorriso progress", None),
    ],
)
def test_xorriso_progress_parser(line, expected):
    assert parse_xorriso_progress(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("BP=>[RUNNING] Starting ISO build process", "profile"),
        ("==> Prepare [Base installation] (rootfs)", "system"),
        ("==> Prepare [Desktop installation] (desktopfs)", "system"),
        ("==> Prepare [/iso/boot]", "boot"),
        ("==> Generating SquashFS image for /rootfs", "compress"),
        ("==> Start [Build ISO]", "compress"),
        ("==> Creating ISO image...", "image"),
        ("xorriso 1.5.6", None),
        ("installing xorriso...", None),
        ("Packages (124) squashfs-tools  xorriso", None),
        ("downloading xorriso-1.5.6.pl02-4-x86_64.pkg.tar.zst", None),
        ("ordinary package output", None),
    ],
)
def test_build_output_markers_select_observable_substeps(line, expected):
    assert detect_build_substep(line) == expected


def test_progress_dialog_uses_numbered_steps_without_pulsing_bar():
    source = (Path(__file__).parents[2] / "usr/share/gitrepo/build_iso/gui/dialogs/progress_dialog.py").read_text(
        encoding="utf-8"
    )

    assert "BuildStepIndicator" in source
    assert '_("Prepare environment")' in source
    assert '_("Update image")' in source
    assert '_("Build ISO")' in source
    assert '_("Publish files")' in source
    assert '_("Finish")' in source
    assert "BuildSubstepIndicator" in source
    assert '_("Prepare profile")' in source
    assert '_("Install system")' in source
    assert '_("Prepare boot")' in source
    assert '_("Compress files")' in source
    assert '_("Create ISO image")' in source
    assert "progress_bar.pulse()" not in source
    assert '"on_live_log"' in source


def test_progress_log_scroll_is_coalesced_until_layout(monkeypatch):
    scheduled = []
    calls = []
    end_mark = object()
    dialog = SimpleNamespace(
        _log_scroll_source_id=None,
        _log_end_mark=end_mark,
        log_buffer=SimpleNamespace(
            get_end_iter=lambda: "end",
            move_mark=lambda *args: calls.append(("move", args)),
        ),
        log_view=SimpleNamespace(scroll_to_mark=lambda *args: calls.append(args)),
    )
    dialog._scroll_log_to_end = lambda: BuildProgressDialog._scroll_log_to_end(dialog)
    monkeypatch.setattr(
        progress_dialog_module.GLib,
        "idle_add",
        lambda callback: scheduled.append(callback) or 17,
    )

    BuildProgressDialog._request_log_scroll_to_end(dialog)
    BuildProgressDialog._request_log_scroll_to_end(dialog)

    assert dialog._log_scroll_source_id == 17
    assert len(scheduled) == 1
    assert scheduled[0]() is False
    assert dialog._log_scroll_source_id is None
    assert calls == [
        ("move", (end_mark, "end")),
        (end_mark, 0.0, True, 0.0, 1.0),
    ]


@pytest.mark.parametrize(
    ("active_index", "outcome", "expected"),
    [
        (2, None, ("complete", "complete", "active", "pending", "pending")),
        (2, "failed", ("complete", "complete", "failed", "pending", "pending")),
        (2, "cancelled", ("complete", "complete", "cancelled", "pending", "pending")),
        (4, "succeeded", ("complete", "complete", "complete", "complete", "complete")),
    ],
)
def test_build_step_states_do_not_complete_unreached_steps(active_index, outcome, expected):
    assert build_step_states(active_index, 5, outcome) == expected
