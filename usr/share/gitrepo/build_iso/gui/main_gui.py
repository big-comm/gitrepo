# intentional-log: startup failures remain visible when no GUI error surface exists.
#
# gui/main_gui.py - Entry point for Build ISO GUI interface
#

import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from gitrepo.common.render_environment import configure_gtk_renderer
from gitrepo.common.premium_style import card_css, hero_css, premium_css

configure_gtk_renderer()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import APP_DESCRIPTION, APP_ID, APP_NAME, APP_VERSION
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from gitrepo.build_iso.gui.main_window import MainWindow

# Sidebar order, reused by the Ctrl+<number> shortcuts.
PAGE_ORDER = ("dashboard", "build", "profiles", "container", "history", "settings")


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

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self.on_shortcuts_activated)
        self.add_action(shortcuts_action)
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>question"])

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh_activated)
        self.add_action(refresh_action)
        self.set_accels_for_action("app.refresh", ["<Ctrl>R", "F5"])

        folder_action = Gio.SimpleAction.new("open-build-folder", GLib.VariantType.new("s"))
        folder_action.connect("activate", self.on_open_build_folder)
        self.add_action(folder_action)

        # Direct page access keeps a six-page sidebar reachable from the keyboard.
        page_action = Gio.SimpleAction.new("goto-page", GLib.VariantType.new("s"))
        page_action.connect("activate", self.on_goto_page)
        self.add_action(page_action)
        for index, page_id in enumerate(PAGE_ORDER, start=1):
            self.set_accels_for_action(f"app.goto-page('{page_id}')", [f"<Ctrl>{index}"])

    def do_activate(self):
        """Called when the application is activated"""
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.present()

    def do_startup(self):
        """Called when the application starts up"""
        Adw.Application.do_startup(self)
        self._setup_icon_theme()
        self._setup_css()
        self.setup_menu()

    def _setup_icon_theme(self):
        """Add project icon directory to icon theme search path"""
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icons_dir = os.path.join(project_root, "icons")
            if os.path.isdir(icons_dir):
                icon_theme.add_search_path(icons_dir)

    def _setup_css(self):
        """Setup custom CSS styles"""
        from gi.repository import Gdk

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data((premium_css() + self._get_default_css()).encode("utf-8"))

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    @staticmethod
    def _get_default_css():
        return (
            hero_css("build-iso")
            + card_css("build-iso", status_min_height="104px", destination_min_width="180px")
            + BuildISOApplication._get_build_page_css()
        )

    @staticmethod
    def _get_build_page_css():
        return (
            BuildISOApplication._get_dashboard_css()
            + BuildISOApplication._get_progress_css()
            + BuildISOApplication._get_progress_log_css()
            + BuildISOApplication._get_progress_state_css()
        )

    @staticmethod
    def _get_dashboard_css():
        return """
            .build-summary-value {
                font-weight: 700;
            }
            .build-flow-step {
                padding: 12px 14px;
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.09);
                background-color: @card_bg_color;
            }
            .build-flow-number {
                min-width: 30px;
                min-height: 30px;
                border-radius: 99px;
                background-color: alpha(currentColor, 0.10);
                font-weight: bold;
            }
            .build-flow-step.flow-done .build-flow-number {
                color: white;
                background-color: @success_color;
            }
            .build-flow-step.flow-current .build-flow-number {
                color: @accent_fg_color;
                background-color: @accent_bg_color;
            }
        """

    @staticmethod
    def _get_progress_css():
        return """
            .build-progress-card {
                padding: 18px 20px 16px;
                border-radius: 16px;
                border: 1px solid alpha(currentColor, 0.08);
                background-color: @card_bg_color;
                box-shadow: 0 1px 3px alpha(black, 0.05);
            }
            .build-progress-percent {
                font-size: 2.4em;
                font-weight: 800;
                letter-spacing: -0.02em;
            }
            .build-progress-status {
                font-weight: 600;
                opacity: 0.85;
            }
            .build-stat-caption {
                font-size: 0.78em;
                font-weight: 700;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                opacity: 0.55;
            }
            .build-stat-value {
                font-size: 1.05em;
                font-weight: 700;
            }
            .build-progress-bar trough,
            .build-progress-bar progress {
                min-height: 8px;
                border-radius: 99px;
            }
            .build-steps {
                margin: 6px 0 2px;
            }
            .build-substeps {
                padding: 8px 4px 0;
                border-top: 1px solid alpha(currentColor, 0.08);
            }
        """

    @staticmethod
    def _get_progress_log_css():
        return """
            .build-log-card {
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.08);
                background-color: @card_bg_color;
            }
            .build-log-header {
                padding: 6px 8px 2px 14px;
            }
            .build-log-view {
                background-color: transparent;
                font-size: 0.92em;
            }
            .build-action-bar {
                padding: 10px 20px 14px;
            }
            .build-step-marker {
                min-width: 28px;
                min-height: 28px;
                border-radius: 99px;
                background-color: alpha(currentColor, 0.08);
                font-weight: bold;
            }
            .build-substep-marker {
                min-width: 9px;
                min-height: 9px;
                padding: 0;
                font-size: 0;
                border-radius: 99px;
                background-color: alpha(currentColor, 0.22);
            }
            .build-substep-title {
                opacity: 0.7;
            }
        """

    @staticmethod
    def _get_progress_state_css():
        return """
            .step-active .build-step-marker {
                color: @accent_fg_color;
                background-color: @accent_bg_color;
            }
            .step-active .build-substep-marker {
                background-color: @accent_bg_color;
            }
            .step-active .build-substep-title {
                opacity: 1;
            }
            .step-complete .build-step-marker {
                color: white;
                background-color: @success_color;
            }
            .step-complete .build-substep-marker {
                background-color: @success_color;
            }
            .step-failed .build-step-marker,
            .step-cancelled .build-step-marker,
            .step-failed .build-substep-marker,
            .step-cancelled .build-substep-marker {
                color: white;
                background-color: @error_color;
            }
            .step-pending .build-step-title {
                opacity: 0.62;
            }
            .step-pending .build-substep-title {
                opacity: 0.58;
            }
            .step-active .build-step-title,
            .step-complete .build-step-title,
            .step-active .build-substep-title,
            .step-complete .build-substep-title {
                font-weight: bold;
            }
        """

    def setup_menu(self):
        """Setup application menu"""
        menu = Gio.Menu()
        app_section = Gio.Menu()
        app_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        app_section.append(_("About Build ISO"), "app.about")
        menu.append_section(None, app_section)
        self.set_menubar(menu)

    def on_quit_activated(self, _action, _param):
        self.quit()

    def on_about_activated(self, _action, _param):
        about_dialog = Adw.AboutWindow(
            transient_for=self.main_window,
            application_name=APP_NAME,
            application_icon="build-iso",
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

    def on_refresh_activated(self, _action, _param):
        if self.main_window:
            self.main_window.refresh_all()

    def on_open_build_folder(self, _action, target):
        """Open an existing build folder through the desktop file manager."""
        from gitrepo.common import child_process as subprocess

        path = target.get_string() if target else ""
        if path and os.path.isdir(path):
            subprocess.Popen(["xdg-open", path])

    def on_goto_page(self, _action, target):
        if self.main_window and target:
            self.main_window.on_navigate_to(self.main_window, target.get_string())

    def on_shortcuts_activated(self, _action, _param):
        shortcuts_data = [
            (_("Quit"), "&lt;Ctrl&gt;Q"),
            (_("Keyboard Shortcuts"), "&lt;Ctrl&gt;question"),
            (_("Refresh Status"), "&lt;Ctrl&gt;R"),
            (_("Start Here"), "&lt;Ctrl&gt;1"),
            (_("Create ISO"), "&lt;Ctrl&gt;2"),
            (_("Choose Profile"), "&lt;Ctrl&gt;3"),
            (_("Build Environment"), "&lt;Ctrl&gt;4"),
            (_("Generated ISOs"), "&lt;Ctrl&gt;5"),
            (_("Settings"), "&lt;Ctrl&gt;6"),
        ]

        shortcut_items = "\n".join(
            f'<child><object class="GtkShortcutsShortcut">'
            f'<property name="title">{GLib.markup_escape_text(title)}</property>'
            f'<property name="accelerator">{accel}</property>'
            f"</object></child>"
            for title, accel in shortcuts_data
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
