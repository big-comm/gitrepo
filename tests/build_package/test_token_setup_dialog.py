"""The token dialog opens for someone with no token saved yet."""

import pytest


@pytest.fixture
def gtk(build_package_modules):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Adw, Gdk, Gtk

    # Without a display GTK 4 still answers init_check() with True, and the
    # first widget then crashes the whole run; only a real display is enough.
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("no display for GTK widgets")
    return Adw, Gtk


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def test_the_token_dialog_opens_with_a_hidden_token_field(gtk, monkeypatch):
    Adw, Gtk = gtk
    from gitrepo.build_package.gui.repository_actions import RepositoryActionsMixin

    presented = []
    monkeypatch.setattr(Adw.MessageDialog, "present", lambda dialog: presented.append(dialog))

    class Window(RepositoryActionsMixin, Gtk.Window):
        build_package = type("Bp", (), {"organization": "biglinux"})()

    Window()._show_token_setup_dialog(lambda: True, "Build", "Starting")

    (dialog,) = presented
    (token_entry,) = [w for w in _descendants(dialog.get_extra_child()) if isinstance(w, Gtk.PasswordEntry)]
    assert token_entry.get_property("placeholder-text") == "ghp_..."
    assert token_entry.get_show_peek_icon()
    # The token is saved for the destination, so the dialog names it and asks no username.
    assert "github.com/biglinux" in dialog.get_body()
    assert not [w for w in _descendants(dialog.get_extra_child()) if type(w) is Gtk.Entry]
