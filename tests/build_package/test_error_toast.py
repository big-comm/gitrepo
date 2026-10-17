"""An error toast must reach the overlay; Adw.Toast takes no CSS class of its own."""

from types import SimpleNamespace

import pytest


def test_error_toast_is_shown_in_red(build_package_modules):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk

    if not Gtk.init_check():
        pytest.skip("no display for GTK widgets")
    from gitrepo.build_package.gui.main_window import MainWindow

    shown = []
    window = SimpleNamespace(toast_overlay=SimpleNamespace(add_toast=shown.append))

    MainWindow.show_error_toast(window, "Source and target are the same branch.")

    (toast,) = shown
    title = toast.get_custom_title()
    assert title.get_label() == "Source and target are the same branch."
    assert title.has_css_class("error")
