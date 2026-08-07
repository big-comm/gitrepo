# intentional-log: startup failures remain visible when no GUI error surface exists.
#
# gui/main_gui.py - Entry point for Build Package GUI interface
#

import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from gitrepo.common.premium_style import card_css, hero_css, premium_css
from gitrepo.common.render_environment import configure_gtk_renderer

configure_gtk_renderer()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.config import APP_DESC, APP_NAME, APP_VERSION
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from gitrepo.build_package.gui.main_window import MainWindow

# Sidebar order, reused by the Ctrl+<number> shortcuts.
PAGE_ORDER = ("publish", "branches", "packages", "settings")


class BuildPackageApplication(Adw.Application):
    """Main application class for the Build Package GTK4 interface."""

    def __init__(self):
        super().__init__(application_id="org.bigcommunity.gitrepo", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.main_window = None
        self.setup_actions()

    def setup_actions(self):
        """Set up application-wide actions and accelerators."""
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

        # Direct page access keeps an eight-page sidebar reachable from the keyboard.
        page_action = Gio.SimpleAction.new("goto-page", GLib.VariantType.new("s"))
        page_action.connect("activate", self.on_goto_page)
        self.add_action(page_action)
        for index, page_id in enumerate(PAGE_ORDER, start=1):
            self.set_accels_for_action(f"app.goto-page('{page_id}')", [f"<Ctrl>{index}"])

    def do_activate(self):
        """Create or present the primary window."""
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.present()

    def do_startup(self):
        """Register icons, styles, and the application menu."""
        Adw.Application.do_startup(self)
        self._setup_icon_theme()
        self._setup_css()
        self.setup_menu()

    def _setup_icon_theme(self):
        """Expose project-owned scalable icons to GTK's icon theme."""
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icons_dir = os.path.join(project_root, "icons")
            if os.path.isdir(icons_dir):
                icon_theme.add_search_path(icons_dir)

    def _setup_css(self):
        """Load shared premium styles plus Build Package-specific polish."""
        from gi.repository import Gdk

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data((premium_css() + self._get_default_css()).encode("utf-8"))

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    @staticmethod
    def _get_default_css():
        return BuildPackageApplication._get_layout_css() + BuildPackageApplication._get_component_css()

    @staticmethod
    def _get_layout_css():
        return (
            hero_css("build-package")
            + """
            .build-package-sidebar .navigation-sidebar row {
                min-height: 36px;
                margin: 0;
                border-radius: 8px;
            }
        """
        )

    @staticmethod
    def _get_component_css():
        return (
            card_css("build-package", status_min_height="52px", destination_min_width="205px")
            + """
            .build-package-status-grid flowboxchild {
                min-width: 190px;
                padding: 0;
            }
            .build-package-warning-banner {
                margin-bottom: 2px;
            }
            .build-package-progress-card {
                padding: 16px 18px;
                border-radius: 16px;
                border: 1px solid alpha(currentColor, 0.08);
                background-color: @card_bg_color;
                box-shadow: 0 1px 3px alpha(black, 0.05);
            }
            .build-package-progress-status {
                font-size: 1.1em;
                font-weight: 700;
            }
            .build-package-progress-bar trough,
            .build-package-progress-bar progress {
                min-height: 8px;
                border-radius: 99px;
            }
            .build-package-log-card {
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.08);
                background-color: @card_bg_color;
            }
            .build-package-log-header {
                padding: 6px 8px 2px 14px;
            }
            .build-package-log-view {
                background-color: transparent;
                font-size: 0.92em;
            }
            .build-package-action-bar {
                padding: 10px 20px 14px;
            }
            .build-package-diff-sidebar {
                background-color: @sidebar_bg_color;
            }
            .build-package-diff-pane {
                background-color: @view_bg_color;
            }
            .build-package-diff-view {
                background-color: transparent;
                font-size: 0.92em;
            }
            .build-package-page-switcher {
                min-width: 320px;
            }
            .build-package-step-number {
                min-width: 24px;
                min-height: 24px;
                border-radius: 99px;
                background-color: alpha(@accent_bg_color, 0.16);
                color: @accent_color;
                font-weight: 700;
                font-size: 0.85em;
            }
            .build-package-command-block {
                padding: 8px 10px;
                border-radius: 10px;
                background-color: alpha(currentColor, 0.06);
                font-family: monospace;
                font-size: 0.88em;
            }
            .build-package-confirmation-header-icon {
                padding: 8px;
                border-radius: 99px;
                color: @accent_color;
                background-color: alpha(@accent_bg_color, 0.14);
            }
            .build-package-confirmation-list {
                border: 1px solid alpha(currentColor, 0.08);
            }
            .build-package-confirmation-row {
                padding: 11px 14px;
            }
            .build-package-confirmation-label {
                font-weight: 600;
                letter-spacing: 0.02em;
            }
            .build-package-confirmation-value {
                font-weight: 700;
            }
            .build-package-confirmation-multiline-value {
                font-weight: 400;
                font-size: 0.95em;
            }
            .build-package-confirmation-command {
                padding: 9px 11px;
                border-radius: 9px;
                color: @accent_color;
                background-color: alpha(@accent_bg_color, 0.10);
                font-family: monospace;
                font-size: 0.9em;
            }
            .build-package-confirmation-section {
                color: @accent_color;
                font-weight: 700;
            }
            .build-package-confirmation-item-icon {
                color: @accent_color;
            }
            .build-package-confirmation-item {
                font-size: 0.9em;
            }
            .build-package-github-action {
                padding: 10px 12px;
                border-radius: 11px;
                color: @accent_color;
                background-color: alpha(@accent_bg_color, 0.12);
            }
            .build-package-pr-card {
                padding: 12px 18px;
                border-radius: 12px;
                border: 1px solid alpha(currentColor, 0.08);
                background-color: alpha(currentColor, 0.04);
            }
            .build-package-pr-source {
                color: @accent_color;
                font-weight: 700;
            }
            .build-package-pr-arrow {
                color: @accent_color;
            }
            .build-package-pr-target {
                color: @success_color;
                font-weight: 700;
            }
            /* Libadwaita banners have no destructive appearance of their own,
               so the destructive page states it in colour and weight. */
            .build-package-warning-banner > revealer > widget {
                background-color: alpha(@error_color, 0.14);
                border-radius: 12px;
            }
            .build-package-warning-banner label {
                color: @error_color;
                font-weight: 700;
            }
        """
        )

    def setup_menu(self):
        """Set up the application menu."""
        menu = Gio.Menu()
        app_section = Gio.Menu()
        app_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        app_section.append(_("About Build Package"), "app.about")
        menu.append_section(None, app_section)
        self.set_menubar(menu)

    def on_quit_activated(self, _action, _param):
        self.quit()

    def on_about_activated(self, _action, _param):
        about_dialog = Adw.AboutWindow(
            transient_for=self.main_window,
            application_name=APP_NAME,
            application_icon="org.bigcommunity.buildpackage",
            developer_name="BigCommunity Team",
            version=APP_VERSION,
            comments=APP_DESC,
            website="https://github.com/big-comm/build-package",
            issue_url="https://github.com/big-comm/build-package/issues",
            copyright="Copyright © 2024-2025 BigCommunity Team",
            license_type=Gtk.License.MIT_X11,
        )
        about_dialog.set_developers(["BigCommunity Team <team@bigcommunity.org>"])
        about_dialog.set_translator_credits(_("translator-credits"))
        about_dialog.present()

    def on_preferences_activated(self, _action, _param):
        if self.main_window:
            self.main_window.switch_to_page("settings")

    def on_refresh_activated(self, _action, _param):
        if self.main_window and hasattr(self.main_window, "refresh_all_widgets"):
            self.main_window.refresh_all_widgets()

    def on_goto_page(self, _action, target):
        if self.main_window and target:
            self.main_window.switch_to_page(target.get_string())

    def on_shortcuts_activated(self, _action, _param):
        shortcuts_data = [
            (_("Quit"), "&lt;Ctrl&gt;Q"),
            (_("Open behavior settings"), "&lt;Ctrl&gt;comma"),
            (_("Keyboard Shortcuts"), "&lt;Ctrl&gt;question"),
            (_("Refresh Status"), "&lt;Ctrl&gt;R"),
            (_("Publish Changes"), "&lt;Ctrl&gt;1"),
            (_("Organize Branches"), "&lt;Ctrl&gt;2"),
            (_("Packages"), "&lt;Ctrl&gt;3"),
            (_("Settings"), "&lt;Ctrl&gt;4"),
        ]
        shortcut_items = "\n".join(
            f'<child><object class="GtkShortcutsShortcut">'
            f'<property name="title">{GLib.markup_escape_text(title)}</property>'
            f'<property name="accelerator">{accelerator}</property>'
            f"</object></child>"
            for title, accelerator in shortcuts_data
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <interface>
          <object class="GtkShortcutsWindow" id="shortcuts_window">
            <property name="modal">true</property>
            <child>
              <object class="GtkShortcutsSection">
                <property name="section-name">shortcuts</property>
                <property name="title">{GLib.markup_escape_text(_("General"))}</property>
                <child>
                  <object class="GtkShortcutsGroup">
                    <property name="title">{GLib.markup_escape_text(_("Application"))}</property>
                    {shortcut_items}
                  </object>
                </child>
              </object>
            </child>
          </object>
        </interface>"""
        builder = Gtk.Builder.new_from_string(xml, -1)
        shortcuts_window = builder.get_object("shortcuts_window")
        shortcuts_window.set_transient_for(self.main_window)
        shortcuts_window.present()


def main():
    """Main entry point for the GUI interface."""
    try:
        Adw.init()
        app = BuildPackageApplication()
        return app.run(sys.argv)
    except Exception as exc:
        print(_("GUI Error: {0}").format(exc))
        try:
            error_dialog = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=_("Failed to start GUI interface"),
            )
            error_dialog.format_secondary_text(str(exc))
            error_dialog.run()
            error_dialog.destroy()
        except Exception:
            print(_("Fatal GUI Error: {0}").format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
