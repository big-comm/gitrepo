# intentional-log: startup failures remain visible when no GUI error surface exists.
#
# gui/main_gui.py - Entry point for Build ISO GUI interface
#

import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from gitrepo.common.render_environment import configure_gtk_renderer
from gitrepo.common.premium_style import premium_css

configure_gtk_renderer()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import APP_DESCRIPTION, APP_ID, APP_NAME, APP_VERSION
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from gitrepo.build_iso.gui.main_window import MainWindow


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

    def _get_default_css(self):
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
            .build-action-button {
                min-height: 48px;
                font-weight: bold;
                font-size: 1.1em;
            }
            .build-iso-expanded-header {
                background-image: linear-gradient(120deg,
                    alpha(@accent_bg_color, 0.18),
                    alpha(@accent_bg_color, 0.06) 58%,
                    alpha(#8b5cf6, 0.10));
                box-shadow: none;
            }
            .build-iso-page-hero {
                min-height: 56px;
                padding: 0 32px 44px;
                border-bottom: 1px solid alpha(@accent_color, 0.20);
                background-image: linear-gradient(120deg,
                    alpha(@accent_bg_color, 0.18),
                    alpha(@accent_bg_color, 0.06) 58%,
                    alpha(#8b5cf6, 0.10));
            }
            .build-iso-page-hero-icon {
                min-width: 56px;
                min-height: 56px;
            }
            .build-iso-hero-subtitle {
                opacity: 0.82;
            }
            .build-iso-status-card {
                min-height: 104px;
                padding: 14px;
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.09);
                background-color: @card_bg_color;
                box-shadow: 0 2px 8px alpha(black, 0.06);
            }
            .build-iso-destinations flowboxchild {
                min-width: 180px;
                padding: 0;
            }
            .build-iso-destination-card {
                min-height: 126px;
                padding: 16px;
                border-radius: 14px;
                border: 1px solid alpha(currentColor, 0.09);
                background-color: @card_bg_color;
                box-shadow: 0 2px 8px alpha(black, 0.06);
                transition: 180ms ease;
            }
            .build-iso-destination-card:hover {
                border-color: alpha(@accent_color, 0.42);
                background-color: alpha(@accent_bg_color, 0.07);
                box-shadow: 0 7px 18px alpha(black, 0.10);
                transform: translateY(-2px);
            }
            .build-steps {
                margin: 2px 0 4px;
            }
            .build-substeps {
                padding: 7px 9px;
                border-radius: 10px;
                background-color: alpha(currentColor, 0.045);
            }
            .build-step-marker {
                min-width: 28px;
                min-height: 28px;
                border-radius: 99px;
                background-color: alpha(currentColor, 0.08);
                font-weight: bold;
            }
            .build-substep-marker {
                min-width: 20px;
                min-height: 20px;
                border-radius: 99px;
                background-color: alpha(currentColor, 0.08);
                font-size: 0.82em;
                font-weight: bold;
            }
            .step-active .build-step-marker {
                color: @accent_fg_color;
                background-color: @accent_bg_color;
            }
            .step-active .build-substep-marker {
                color: @accent_fg_color;
                background-color: @accent_bg_color;
            }
            .step-complete .build-step-marker {
                color: white;
                background-color: @success_color;
            }
            .step-complete .build-substep-marker {
                color: white;
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

    def on_shortcuts_activated(self, _action, _param):
        shortcuts_data = [
            (_("Quit"), "&lt;Ctrl&gt;Q"),
            (_("Keyboard Shortcuts"), "&lt;Ctrl&gt;question"),
            (_("Refresh Status"), "&lt;Ctrl&gt;R"),
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
