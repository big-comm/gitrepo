"""Open paths and links through the desktop, and say so when it fails.

Spawning ``xdg-open`` and ignoring the result turns a button into a control
that sometimes does nothing and never explains why. The GTK launchers report
their outcome, and they are the portal-aware path on a sandboxed session.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .translation import _  # noqa: E402


def _parent_window(widget: Gtk.Widget | None) -> Gtk.Window | None:
    """Return the window a launcher should be modal to, if there is one."""
    root = widget.get_root() if widget is not None else None
    return root if isinstance(root, Gtk.Window) else None


def _report(widget: Gtk.Widget | None, message: str) -> None:
    """Surface *message* on the nearest toast overlay, or on the window."""
    root = widget.get_root() if widget is not None else None
    if root is not None and hasattr(root, "show_toast"):
        root.show_toast(message)
        return
    overlay = getattr(root, "toast_overlay", None)
    if overlay is not None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        overlay.add_toast(toast)


def _finish(
    launcher_result: Gio.AsyncResult,
    widget: Gtk.Widget | None,
    failure_message: str,
    finish: Callable[[Gio.AsyncResult], object],
) -> None:
    try:
        finish(launcher_result)
    except Exception as error:  # GLib.Error and anything the portal raises
        _report(widget, f"{failure_message} {error.message if hasattr(error, 'message') else error}")


def open_path(widget: Gtk.Widget | None, path: str) -> None:
    """Open *path* with the desktop's handler for it."""
    if not path:
        return
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
    launcher.launch(
        _parent_window(widget),
        None,
        lambda source, result, _data=None: _finish(
            result, widget, _("Could not open {0}:").format(path), source.launch_finish
        ),
    )


def open_folder(widget: Gtk.Widget | None, path: str) -> None:
    """Reveal *path* in the desktop's file manager."""
    if not path:
        return
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
    launcher.open_containing_folder(
        _parent_window(widget),
        None,
        lambda source, result, _data=None: _finish(
            result, widget, _("Could not open the folder for {0}:").format(path), source.open_containing_folder_finish
        ),
    )


def open_uri(widget: Gtk.Widget | None, uri: str) -> None:
    """Open *uri* in the desktop's handler for its scheme."""
    if not uri:
        return
    launcher = Gtk.UriLauncher.new(uri)
    launcher.launch(
        _parent_window(widget),
        None,
        lambda source, result, _data=None: _finish(
            result, widget, _("Could not open {0}:").format(uri), source.launch_finish
        ),
    )
