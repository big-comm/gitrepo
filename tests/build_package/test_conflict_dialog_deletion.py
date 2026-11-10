"""Confirming a deletion in the conflict dialog applies it and closes the dialog.

Closing the dialog from the alert's response only closed the alert: the files
were deleted and the operation went on, while the dialog stayed open as if
"Delete and Apply" had done nothing.
"""

import subprocess
import time

import pytest

from .git_fixtures import create_repository_with_remote, run_git


def _display_available():
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gtk
    except (ImportError, ValueError):
        return False
    # init_check() is True even without a display (see test_error_toast.py).
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        return False
    Adw.init()
    return True


pytestmark = pytest.mark.skipif(not _display_available(), reason="needs a display")


@pytest.fixture
def stash_deletes_updated_files(tmp_path):
    """The stash deletes a file origin changed: restoring it leaves a modify/delete conflict."""
    repository, remote = create_repository_with_remote(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.name", "Other")
    run_git(other, "config", "user.email", "other@example.invalid")
    (other / "tracked.txt").write_text("changed on origin\n", encoding="utf-8")
    run_git(other, "commit", "-am", "change")
    run_git(other, "push", "origin", "main")

    (repository / "tracked.txt").unlink()
    run_git(repository, "stash", "push", "-m", "gitrepo-pull-main")
    run_git(repository, "pull", "--ff-only", "origin", "main")
    subprocess.run(["git", "stash", "pop", "--index"], cwd=repository, capture_output=True)
    assert run_git(repository, "status", "--porcelain").stdout.startswith("UD tracked.txt")
    return repository


def _spin_until(condition, seconds=5):
    from gi.repository import GLib

    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while not condition() and time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.01)
    return condition()


def test_delete_and_apply_closes_the_dialog(stash_deletes_updated_files, monkeypatch):
    from gi.repository import Adw

    from gitrepo.build_package.gui.dialogs.conflict_dialog import ConflictDialog

    alerts = []
    new_alert = Adw.AlertDialog.new
    monkeypatch.setattr(Adw.AlertDialog, "new", lambda *args: alerts.append(new_alert(*args)) or alerts[-1])

    parent = Adw.Window()
    parent.present()
    dialog = ConflictDialog(parent, ["tracked.txt"], repo_root=str(stash_deletes_updated_files))
    results = []
    dialog.connect("conflicts-resolved", lambda _dialog, ok: results.append(ok))
    dialog.present()
    _spin_until(dialog.get_mapped)

    dialog.on_auto_theirs_clicked(None)  # the stash's side: the file is deleted
    dialog.on_apply_clicked(None)
    assert len(alerts) == 1

    # What a click on "Delete and Apply" does: the response, then the alert closes.
    alerts[0].emit("response", "delete")
    alerts[0].force_close()

    assert _spin_until(lambda: not dialog.get_visible())
    assert results == [True]
    status = run_git(stash_deletes_updated_files, "status", "--porcelain").stdout
    assert status.startswith("D  tracked.txt")
    parent.destroy()
