"""Page shells: one destination hosting several widgets."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from gitrepo.common.page_hero import BuildPackagePageHero as PageHero


class TabbedPage(Gtk.Box):
    """Group related widgets under one hero and an inline view switcher.

    Sibling contexts — a package repository and the AUR, or the three kinds of
    setting — stay one destination instead of competing for sidebar rows.
    """

    def __init__(
        self, icon_name: str, title: str, description: str, tabs: list[tuple[str, str, str, Gtk.Widget]]
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.append(PageHero(icon_name, title, description))

        self.stack = Adw.ViewStack()
        self.stack.set_vexpand(True)

        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.add_css_class("build-package-page-switcher")

        switcher_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        switcher_row.set_halign(Gtk.Align.CENTER)
        switcher_row.set_margin_top(14)
        switcher_row.append(switcher)
        self.append(switcher_row)

        for name, tab_title, tab_icon, widget in tabs:
            self.stack.add_titled_with_icon(widget, name, tab_title, tab_icon)
        self.append(self.stack)

    def show_tab(self, name: str) -> None:
        """Reveal one hosted context by name."""
        self.stack.set_visible_child_name(name)


class StackedPage(Gtk.Box):
    """Show every hosted section in one scroll, under a single hero.

    Settings are scanned, not navigated: hiding half of them behind a tab adds a
    decision before the user can even look.
    """

    def __init__(self, icon_name: str, title: str, description: str, sections: list[Gtk.Widget]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.append(PageHero(icon_name, title, description))
        for section in sections:
            self.append(section)
