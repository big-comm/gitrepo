# intentional-log: startup failures remain visible when no GUI error surface exists.
#
# gui/main_gui.py - Entry point for Build Package GUI interface
#

import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from gitrepo.common.premium_style import premium_css
from gitrepo.common.render_environment import configure_gtk_renderer

configure_gtk_renderer()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.config import APP_DESC, APP_NAME, APP_VERSION
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from gitrepo.build_package.gui.main_window import MainWindow


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
        return """
            row.combo popover contents modelbutton {
                min-width: 250px;
            }
            .content-canvas {
                --dim-opacity: 72%;
            }
            .content-canvas row label.subtitle,
            .content-canvas .caption.dim-label {
                font-size: inherit;
                line-height: 1.35;
            }
            @media (prefers-contrast: more) {
                .content-canvas {
                    --dim-opacity: 90%;
                }
            }
            .build-package-expanded-header {
                background-image: linear-gradient(120deg,
                    alpha(@accent_bg_color, 0.18),
                    alpha(@accent_bg_color, 0.06) 58%,
                    alpha(#8b5cf6, 0.10));
                box-shadow: none;
            }
            .build-package-page-hero {
                min-height: 56px;
                padding: 0 32px 44px;
                border-bottom: 1px solid alpha(@accent_color, 0.20);
                background-image: linear-gradient(120deg,
                    alpha(@accent_bg_color, 0.18),
                    alpha(@accent_bg_color, 0.06) 58%,
                    alpha(#8b5cf6, 0.10));
            }
            .build-package-page-hero-icon {
                min-width: 56px;
                min-height: 56px;
            }
            .build-package-hero-subtitle {
                opacity: 0.82;
            }
            .build-package-sidebar .navigation-sidebar row {
                min-height: 36px;
                margin: 0;
                border-radius: 8px;
            }
        """

    @staticmethod
    def _get_component_css():
        return """
            .build-package-status-grid flowboxchild {
                min-width: 190px;
                padding: 0;
            }
            .build-package-status-card {
                min-height: 52px;
                padding: 10px 12px;
                border-radius: 12px;
                border: 1px solid alpha(currentColor, 0.09);
                background-color: @card_bg_color;
                box-shadow: 0 1px 3px alpha(black, 0.06);
            }
            .build-package-destinations flowboxchild {
                min-width: 205px;
                padding: 0;
            }
            .build-package-destination-card {
                min-height: 132px;
                padding: 16px;
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.09);
                background-color: @card_bg_color;
                box-shadow: 0 2px 8px alpha(black, 0.06);
                transition: 180ms ease;
            }
            .build-package-destination-card:hover {
                border-color: alpha(@accent_color, 0.42);
                background-color: alpha(@accent_bg_color, 0.07);
                box-shadow: 0 7px 18px alpha(black, 0.10);
                transform: translateY(-2px);
            }
            .build-package-action-button {
                min-height: 44px;
                font-weight: bold;
            }
            .build-package-primary-action {
                min-height: 48px;
                font-weight: bold;
                font-size: 1.05em;
            }
            .build-package-warning-banner {
                margin-bottom: 2px;
            }
        """

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
            self.main_window.switch_to_page("behavior")

    def on_refresh_activated(self, _action, _param):
        if self.main_window and hasattr(self.main_window, "refresh_all_widgets"):
            self.main_window.refresh_all_widgets()

    def on_shortcuts_activated(self, _action, _param):
        shortcuts_data = [
            (_("Quit"), "&lt;Ctrl&gt;Q"),
            (_("Open behavior settings"), "&lt;Ctrl&gt;comma"),
            (_("Keyboard Shortcuts"), "&lt;Ctrl&gt;question"),
            (_("Refresh Status"), "&lt;Ctrl&gt;R"),
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
