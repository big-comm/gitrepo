"""Publishing to one organization or both, from the Packages page cards."""

import importlib

import pytest


@pytest.fixture
def page(build_package_modules, monkeypatch, tmp_path):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gtk

    # Without a display GTK 4 still answers init_check() with True, and the
    # first widget then crashes the whole run; only a real display is enough.
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("no display for GTK widgets")
    monkeypatch.setenv("LANGUAGE", "en")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings_module, _store = build_package_modules
    build = importlib.import_module("gitrepo.build_package.core.build_package")
    widgets = importlib.import_module("gitrepo.build_package.gui.widgets.package_widget")
    monkeypatch.setattr(widgets.TokenStore, "read_all", staticmethod(lambda: [("big-comm", "a")]))
    bp = build.BuildPackage()
    bp.set_organization("big-comm")
    widget = widgets.PackageWidget(bp, settings_module.Settings(str(tmp_path / "gitrepo")), show_hero=False)
    return widget, bp


def test_the_page_builds_with_the_principal_card_marked(page):
    widget, bp = page
    cards = widget._destination_cards
    assert cards["big-comm"].get_active() and not cards["biglinux"].get_active()
    assert widget.destination_summary.get_label() == "Will be published by: BigCommunity"


def test_marking_the_second_card_publishes_to_both(page):
    widget, bp = page
    widget._destination_cards["biglinux"].set_active(True)
    assert bp.publish_targets() == ["big-comm", "biglinux"]
    assert widget.destination_summary.get_label() == "Will be published by: BigCommunity and BigLinux"


def test_the_last_marked_card_cannot_be_unmarked(page):
    widget, bp = page
    widget._destination_cards["big-comm"].set_active(False)
    assert widget._destination_cards["big-comm"].get_active()
    assert bp.publish_targets() == ["big-comm"]


def test_unmarking_the_principal_promotes_the_other(page):
    widget, bp = page
    widget._destination_cards["biglinux"].set_active(True)
    widget._destination_cards["big-comm"].set_active(False)
    assert bp.publish_targets() == ["biglinux"]
    assert bp.organization == "biglinux"
