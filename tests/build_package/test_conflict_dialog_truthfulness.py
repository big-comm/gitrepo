"""The conflict dialog must not claim a resolution it has not verified."""

from types import SimpleNamespace

import pytest

from gitrepo.build_package.gui.dialogs import conflict_dialog
from gitrepo.build_package.gui.dialogs.conflict_dialog import ConflictDialog


MARKED = "line\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> incoming\n"


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "f.txt").write_text(MARKED, encoding="utf-8")
    return SimpleNamespace(repo_root=str(tmp_path))


def test_a_file_that_still_has_markers_is_refused(repository, tmp_path):
    # Reporting success here staged the markers with `git add` and published
    # them; the old code only printed a warning and returned True.
    assert ConflictDialog.apply_resolution(repository, "f.txt", "manual") is False


def test_an_edited_file_is_accepted(repository, tmp_path):
    (tmp_path / "f.txt").write_text("resolved by hand\n", encoding="utf-8")

    assert ConflictDialog.apply_resolution(repository, "f.txt", "manual") is True


@pytest.mark.parametrize("marker", ["<<<<<<<", "=======", ">>>>>>>"])
def test_each_marker_alone_is_enough_to_refuse(repository, tmp_path, marker):
    (tmp_path / "f.txt").write_text(f"a\n{marker} x\nb\n", encoding="utf-8")

    assert ConflictDialog.apply_resolution(repository, "f.txt", "manual") is False


def test_an_unreadable_file_is_refused_not_assumed_resolved(repository, tmp_path):
    (tmp_path / "f.txt").unlink()

    assert ConflictDialog.apply_resolution(repository, "f.txt", "manual") is False


def test_opening_the_editor_does_not_post_to_a_missing_overlay():
    # The toast was added to self.toast_overlay, which create_ui never builds,
    # so it was never shown and the control it named does not exist.
    with open(conflict_dialog.__file__, "r", encoding="utf-8") as stream:
        code = "\n".join(line for line in stream.read().splitlines() if not line.lstrip().startswith("#"))

    assert "add_toast(" not in code
    assert "Adw.Toast.new(" not in code
    assert "Mark as Edited" not in code


def test_a_failed_apply_keeps_the_dialog_open():
    with open(conflict_dialog.__file__, "r", encoding="utf-8") as stream:
        text = stream.read()

    body = text.split("def _apply_resolutions", 1)[1].split("\n    def ", 1)[0]
    # Closing on failure hid both the reason and the half-resolved working tree.
    assert "if not success:" in body
    assert body.index("if not success:") < body.index("self.close()")
