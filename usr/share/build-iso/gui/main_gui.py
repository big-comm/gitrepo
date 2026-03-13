#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_gui.py - Entry point for Build ISO GUI interface
#

import os
import sys

# Add the project root directory to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import APP_DESCRIPTION, APP_ID, APP_NAME, APP_VERSION
from core.translation_utils import _
from gi.repository import Adw, Gio, Gtk

from gui.main_window import MainWindow


class BuildISOApplication(Adw.Application):
    """Main application class for Build ISO GTK4 interface"""

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        self.main_window = None
        self.setup_actions()

    def setup_actions(self):
        """Setup application-wide actions"""
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit_activated)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>Q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activated)
        self.add_action(about_action)

        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences_activated)
        self.add_action(preferences_action)
        self.set_accels_for_action("app.preferences", ["<Ctrl>comma"])

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self.on_shortcuts_activated)
        self.add_action(shortcuts_action)
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>question"])

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh_activated)
        self.add_action(refresh_action)
        self.set_accels_for_action("app.refresh", ["<Ctrl>R", "F5"])

    def do_activate(self):
        """Called when the application is activated"""
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.present()

    def do_startup(self):
        """Called when the application starts up"""
        Adw.Application.do_startup(self)
        self._setup_css()
        self.setup_menu()

    def _setup_css(self):
        """Setup custom CSS styles"""
        from gi.repository import Gdk

        css_provider = Gtk.CssProvider()

        # Try external CSS first
        css_path = os.path.join(os.path.dirname(__file__), '..', 'resources', 'style.css')
        if os.path.exists(css_path):
            css_provider.load_from_path(css_path)
        else:
            css_provider.load_from_data(self._get_default_css().encode("utf-8"))

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _get_default_css(self):
        return """
            .wide-dropdown popover.menu {
                min-width: 280px;
            }
            .wide-dropdown popover.menu modelbutton {
                min-width: 260px;
            }
            row.combo popover contents modelbutton {
                min-width: 250px;
            }
            .sidebar-listbox row {
                border-radius: 10px;
                margin: 2px 6px;
                padding: 2px 4px;
                transition: all 200ms ease;
            }
            .sidebar-listbox row:hover:not(:selected) {
                background-color: alpha(@accent_bg_color, 0.1);
            }
            .sidebar-listbox row:selected {
                background-color: alpha(@accent_bg_color, 0.85);
                color: @accent_fg_color;
                border-radius: 10px;
            }
            .sidebar-listbox row:selected label.title {
                color: @accent_fg_color;
                font-weight: bold;
            }
            .sidebar-listbox row:selected label.subtitle {
                color: alpha(@accent_fg_color, 0.85);
            }
            .sidebar-listbox row:selected image {
                color: @accent_fg_color;
            }
            .status-ok { color: #32CD32; }
            .status-warning { color: #FFD93D; }
            .status-error { color: #FF6B6B; }
            .build-action-button {
                min-height: 48px;
                font-weight: bold;
                font-size: 1.1em;
            }
            .terminal-view {
                font-family: monospace;
                font-size: 0.9em;
            }
        """

    def setup_menu(self):
        """Setup application menu"""
        menu = Gio.Menu()
        app_section = Gio.Menu()
        app_section.append(_("Preferences"), "app.preferences")
        app_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        app_section.append(_("About Build ISO"), "app.about")
        menu.append_section(None, app_section)
        self.set_menubar(menu)

    def on_quit_activated(self, action, param):
        self.quit()

    def on_about_activated(self, action, param):
        about_dialog = Adw.AboutWindow(
            transient_for=self.main_window,
            application_name=APP_NAME,
            application_icon="media-optical-symbolic",
            developer_name="BigCommunity Team",
            version=APP_VERSION,
            comments=APP_DESCRIPTION,
            website="https://github.com/big-comm/build-iso",
            issue_url="https://github.com/big-comm/build-iso/issues",
            copyright="Copyright © 2024-2025 BigCommunity Team",
            license_type=Gtk.License.GPL_3_0,
        )
        about_dialog.set_developers(["BigCommunity Team <team@bigcommunity.org>"])
        about_dialog.set_translator_credits(_("translator-credits"))
        about_dialog.present()

    def on_preferences_activated(self, action, param):
        if self.main_window:
            self.main_window.show_settings_page()

    def on_refresh_activated(self, action, param):
        if self.main_window:
            self.main_window.refresh_all()

    def on_shortcuts_activated(self, action, param):
        shortcuts_window = Gtk.ShortcutsWindow(transient_for=self.main_window)

        section = Gtk.ShortcutsSection(visible=True)
        section.set_title(_("General"))

        group = Gtk.ShortcutsGroup(visible=True)
        group.set_title(_("Application"))

        shortcuts = [
            (_("Quit"), "<Ctrl>Q"),
            (_("Preferences"), "<Ctrl>comma"),
            (_("Keyboard Shortcuts"), "<Ctrl>question"),
            (_("Refresh Status"), "<Ctrl>R"),
        ]
        for title, accelerator in shortcuts:
            shortcut = Gtk.ShortcutsShortcut(visible=True, title=title, accelerator=accelerator)
            group.add_shortcut(shortcut)

        section.add_group(group)
        shortcuts_window.add_section(section)
        shortcuts_window.present()


def main():
    """Main entry point for Build ISO GUI"""
    try:
        Adw.init()
        app = BuildISOApplication()
        return app.run(sys.argv)
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
