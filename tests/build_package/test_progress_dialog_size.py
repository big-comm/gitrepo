"""The progress window keeps its size, however much a command prints.

The logger sends every message to the status line as well as to the log. A
"Download updates" that merged many files logged git's whole output as one
message, one line per file, and the window grew past the screen (760x660 to
760x3105 for 150 files).
"""

import time

import pytest


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


pytestmark = [
    pytest.mark.skipif(not _display_available(), reason="needs a display"),
    # PyGObject warns on every main-loop iteration under Python 3.14.
    pytest.mark.filterwarnings("ignore:'asyncio.get_event_loop_policy' is deprecated:DeprecationWarning"),
]

MERGE_OUTPUT = "Updating 0ffdabe..1234567\nFast-forward\n" + "\n".join(
    f" locale/lang{index}.po | 120 +++++-----" for index in range(150)
)


def _spin(seconds=0.5):
    from gi.repository import GLib

    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.005)


@pytest.fixture
def dialog():
    from gi.repository import Adw

    from gitrepo.build_package.gui.dialogs.progress_dialog import ProgressDialog

    parent = Adw.Window()
    parent.present()
    progress = ProgressDialog(parent, "Downloading updates", "Checking...")
    progress.present()
    _spin()
    yield progress
    progress.close()
    parent.destroy()


def test_long_command_output_does_not_grow_the_window(dialog):
    size = dialog.get_width(), dialog.get_height()

    dialog.set_status(MERGE_OUTPUT)
    dialog.append_detail(MERGE_OUTPUT, style="dim")
    _spin()
    assert (dialog.get_width(), dialog.get_height()) == size

    dialog.set_status("word " * 3000)  # One endless paragraph.
    _spin()
    assert (dialog.get_width(), dialog.get_height()) == size


def test_status_shows_the_first_line_and_the_log_keeps_everything(dialog):
    dialog.set_status("\n  " + MERGE_OUTPUT)
    dialog.append_detail(MERGE_OUTPUT)
    _spin()
    assert dialog.status_label.get_text() == "Updating 0ffdabe..1234567"
    log = dialog.details_buffer.get_text(*dialog.details_buffer.get_bounds(), False)
    assert "locale/lang149.po" in log
