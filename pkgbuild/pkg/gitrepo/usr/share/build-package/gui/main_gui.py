#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_gui.py - Entry point for GUI interface
#

import sys
import os

# Add the project root directory to the Python path
# This allows importing modules like 'core' from anywhere in the project
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio
from core.translation_utils import _
from gui.main_window import MainWindow # Changed to absolute import for consistency

class BuildPackageApplication(Adw.Application):
    """Main application class for GTK4 interface"""
    
    def __init__(self):
        super().__init__(
            application_id='org.bigcommunity.gitrepo',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        
        self.main_window = None
        self.setup_actions()
    
    def setup_actions(self):
        """Setup application-wide actions"""
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit_activated)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>Q"])
        
        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activated)
        self.add_action(about_action)
        
        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences_activated)
        self.add_action(preferences_action)
        self.set_accels_for_action("app.preferences", ["<Ctrl>comma"])
        
        # Keyboard shortcuts action
        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self.on_shortcuts_activated)
        self.add_action(shortcuts_action)
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>question"])
        
        # Refresh action
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh_activated)
        self.add_action(refresh_action)
        self.set_accels_for_action("app.refresh", ["<Ctrl>R", "F5"])
        
        # Welcome action
        welcome_action = Gio.SimpleAction.new("welcome", None)
        welcome_action.connect("activate", self.on_welcome_activated)
        self.add_action(welcome_action)
        self.set_accels_for_action("app.welcome", ["F1"])
    
    def do_activate(self):
        """Called when the application is activated"""
        if not self.main_window:
            self.main_window = MainWindow(self)
        
        self.main_window.present()
    
    def do_startup(self):
        """Called when the application starts up"""
        Adw.Application.do_startup(self)
        
        # Load custom CSS for UI adjustments
        self._setup_css()
        
        # Setup application menu
        self.setup_menu()
    
    def _setup_css(self):
        """Setup custom CSS styles"""
        from gi.repository import Gdk
        
        css_provider = Gtk.CssProvider()
        css_data = """
            /* Make dropdown popups wider to show full text */
            .wide-dropdown popover.menu {
                min-width: 280px;
            }
            
            .wide-dropdown popover.menu modelbutton {
                min-width: 260px;
            }
            
            /* Ensure dropdown list items don't truncate */
            row.combo popover contents modelbutton {
                min-width: 250px;
            }
        """
        css_provider.load_from_data(css_data.encode('utf-8'))
        
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
    
    def setup_menu(self):
        """Setup application menu"""
        menu = Gio.Menu()
        
        # Application section
        app_section = Gio.Menu()
        app_section.append(_("Preferences"), "app.preferences")
        app_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        app_section.append(_("About Build Package"), "app.about")
        menu.append_section(None, app_section)
        
        # Set as primary menu
        self.set_menubar(menu)
    
    def on_quit_activated(self, action, param):
        """Handle quit action"""
        self.quit()
    
    def on_about_activated(self, action, param):
        """Show about dialog"""
        from core.config import APP_NAME, APP_VERSION, APP_DESC

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
            license_type=Gtk.License.MIT_X11
        )
        
        # Add developers
        about_dialog.set_developers([
            "BigCommunity Team <team@bigcommunity.org>"
        ])
        
        # Add translators
        about_dialog.set_translator_credits(_("translator-credits"))
        
        about_dialog.present()
    
    def on_preferences_activated(self, action, param):
        """Show preferences window"""
        if self.main_window and hasattr(self.main_window, 'settings'):
            from gui.dialogs.settings_dialog import SettingsDialog

            # Create and show settings dialog
            settings_dialog = SettingsDialog(
                self.main_window,
                self.main_window.settings
            )

            def on_settings_changed(dialog):
                # Refresh build_package settings when changed
                if hasattr(self.main_window, 'build_package') and self.main_window.build_package:
                    # Update conflict resolver strategy
                    if hasattr(self.main_window.build_package, 'conflict_resolver'):
                        new_strategy = self.main_window.settings.get("conflict_strategy", "interactive")
                        self.main_window.build_package.conflict_resolver.strategy = new_strategy

                # Show toast
                self.main_window.show_toast(_("Settings updated"))

            settings_dialog.connect('settings-changed', on_settings_changed)
            settings_dialog.present()
        else:
            # Fallback
            if self.main_window:
                self.main_window.show_info_toast(_("Settings not available"))
    
    def on_refresh_activated(self, action, param):
        """Handle refresh action"""
        if self.main_window and hasattr(self.main_window, 'refresh_all_widgets'):
            self.main_window.refresh_all_widgets()
    
    def on_welcome_activated(self, action, param):
        """Handle welcome action"""
        if self.main_window and hasattr(self.main_window, 'show_welcome_dialog'):
            self.main_window.show_welcome_dialog()
    
    def on_shortcuts_activated(self, action, param):
        """Show keyboard shortcuts window"""
        shortcuts_window = Gtk.ShortcutsWindow(
            transient_for=self.main_window
        )
        
        # Create shortcuts section
        section = Gtk.ShortcutsSection(visible=True)
        section.set_title(_("General"))
        
        # Add shortcuts
        shortcuts = [
            (_("Quit"), "<Ctrl>Q"),
            (_("Preferences"), "<Ctrl>comma"),
            (_("Keyboard Shortcuts"), "<Ctrl>question"),
            (_("Refresh Status"), "<Ctrl>R"),
            (_("Welcome Screen"), "F1"),
        ]
        
        group = Gtk.ShortcutsGroup(visible=True)
        group.set_title(_("Application"))
        
        for title, accelerator in shortcuts:
            shortcut = Gtk.ShortcutsShortcut(
                visible=True,
                title=title,
                accelerator=accelerator
            )
            group.add_shortcut(shortcut)
        
        section.add_group(group)
        shortcuts_window.add_section(section)
        shortcuts_window.present()

def main():
    """Main entry point for GUI interface"""
    try:
        # Initialize Adwaita
        Adw.init()
        
        # Create and run application
        app = BuildPackageApplication()
        exit_code = app.run(sys.argv)
        
        return exit_code
        
    except Exception as e:
        print(f"GUI Error: {e}")
        # Import Gtk for emergency error dialog
        try:
            error_dialog = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=_("Failed to start GUI interface")
            )
            error_dialog.format_secondary_text(str(e))
            error_dialog.run()
            error_dialog.destroy()
        except:
            print(f"Fatal GUI Error: {e}")
        
        return 1

if __name__ == "__main__":
    sys.exit(main())