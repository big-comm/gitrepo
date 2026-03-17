#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_window.py - Main window for Build ISO GTK4 interface
#

import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import APP_NAME, APP_VERSION
from core.settings import Settings
from core.translation_utils import _
from gi.repository import Adw, Gio, GLib, Gtk

from .gtk_logger import GTKLogger
from .widgets.build_widget import BuildWidget
from .widgets.container_widget import ContainerWidget
from .widgets.dashboard_widget import DashboardWidget
from .widgets.history_widget import HistoryWidget
from .widgets.profiles_widget import ProfilesWidget
from .widgets.settings_widget import SettingsWidget


class MainWindow(Adw.ApplicationWindow):
    """Main application window using GTK4 + Libadwaita"""

    __gtype_name__ = "BuildISOMainWindow"

    def __init__(self, application):
        super().__init__(application=application)

        self.application = application
        self.settings = Settings()
        self.logger = GTKLogger()

        # Create UI
        self.create_ui()
        self.create_navigation_and_pages()
        self.setup_actions()

        # Window properties
        self.set_default_size(1100, 700)
        self.set_size_request(900, 600)
        self.set_title(APP_NAME)

    def create_ui(self):
        """Create the main UI programmatically"""

        # Toast overlay as outermost wrapper
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # OverlaySplitView as main layout
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_min_sidebar_width(260)
        self.split_view.set_max_sidebar_width(320)
        self.split_view.set_sidebar_width_fraction(0.28)
        self.toast_overlay.set_child(self.split_view)

        # ── SIDEBAR ──
        sidebar_toolbar = Adw.ToolbarView()

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)

        app_title = Gtk.Label(label=APP_NAME)
        app_title.add_css_class("heading")
        sidebar_header.set_title_widget(app_title)

        sidebar_toolbar.add_top_bar(sidebar_header)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        sidebar_box.set_margin_start(12)
        sidebar_box.set_margin_end(12)
        sidebar_box.set_margin_top(6)
        sidebar_box.set_margin_bottom(12)

        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        self.nav_list.add_css_class("sidebar-listbox")
        self.nav_list.connect("row-selected", self.on_nav_row_selected)

        nav_group = Adw.PreferencesGroup()
        nav_group.add(self.nav_list)
        sidebar_box.append(nav_group)

        sidebar_scroll.set_child(sidebar_box)
        sidebar_toolbar.set_content(sidebar_scroll)

        self.split_view.set_sidebar(sidebar_toolbar)

        # ── CONTENT ──
        content_toolbar = Adw.ToolbarView()

        self.content_header = Adw.HeaderBar()
        self.content_header.set_show_start_title_buttons(False)

        self.window_title = Adw.WindowTitle(title=APP_NAME, subtitle=f"v{APP_VERSION}")
        self.content_header.set_title_widget(self.window_title)

        self._create_hamburger_menu()
        content_toolbar.add_top_bar(self.content_header)

        scrolled_content = Gtk.ScrolledWindow()
        scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_content.set_vexpand(True)
        scrolled_content.set_hexpand(True)
        scrolled_content.set_propagate_natural_height(True)

        self.content_stack = Adw.ViewStack()
        self.content_stack.set_vhomogeneous(False)
        scrolled_content.set_child(self.content_stack)

        content_toolbar.set_content(scrolled_content)
        self.split_view.set_content(content_toolbar)

    def create_navigation_and_pages(self):
        """Create navigation items and pages"""

        # Create widgets
        self.dashboard_widget = DashboardWidget(self.settings, self.logger)
        self.build_widget = BuildWidget(self.settings, self.logger)
        self.profiles_widget = ProfilesWidget(self.settings)
        self.container_widget = ContainerWidget(self.settings, self.logger)
        self.history_widget = HistoryWidget(self.settings)
        self.settings_widget = SettingsWidget(self.settings)

        # Connect signals
        self.connect_widget_signals()

        pages = [
            (self.dashboard_widget, "dashboard", _("Dashboard"), "speedometer-symbolic"),
            (self.build_widget, "build", _("Build ISO"), "media-optical-symbolic"),
            (self.profiles_widget, "profiles", _("Profiles"), "folder-symbolic"),
            (self.container_widget, "container", _("Container"), "system-run-symbolic"),
            (self.history_widget, "history", _("History"), "document-open-recent-symbolic"),
            (self.settings_widget, "settings", _("Settings"), "preferences-system-symbolic"),
        ]

        self.nav_rows = {}

        for widget, page_id, title, icon_name in pages:
            self.content_stack.add_titled_with_icon(widget, page_id, title, icon_name)

            nav_row = Adw.ActionRow()
            nav_row.set_title(title)
            nav_row.set_activatable(True)
            nav_row.page_id = page_id

            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            nav_row.add_prefix(icon)

            badge_label = Gtk.Label()
            badge_label.add_css_class("badge")
            badge_label.add_css_class("numeric")
            badge_label.set_visible(False)
            badge_label.set_valign(Gtk.Align.CENTER)
            nav_row.add_suffix(badge_label)
            nav_row.badge = badge_label

            self.nav_rows[page_id] = nav_row
            self.nav_list.append(nav_row)

        # Select first page
        self.nav_list.select_row(self.nav_list.get_row_at_index(0))
        self.content_stack.set_visible_child_name("dashboard")

    def connect_widget_signals(self):
        """Connect signals from widgets"""
        self.dashboard_widget.connect("navigate-to", self.on_navigate_to)
        self.dashboard_widget.connect("start-build", self.on_start_build_from_dashboard)
        self.build_widget.connect("build-requested", self.on_build_requested)
        self.container_widget.connect("container-action", self.on_container_action)
        self.profiles_widget.connect("navigate-to", self.on_navigate_to)
        self.profiles_widget.connect("profile-selected", self.on_profile_selected)
        self.settings_widget.connect("settings-saved", self.on_settings_saved)

    def _create_hamburger_menu(self):
        """Create hamburger menu button"""
        menu = Gio.Menu()
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About"), "app.about")

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text(_("Main Menu"))
        self.content_header.pack_end(menu_button)

    def setup_actions(self):
        """Setup window-level actions"""
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda a, p: self.refresh_all())
        self.add_action(refresh_action)

    # ── Navigation ──

    def on_nav_row_selected(self, listbox, row):
        """Handle sidebar navigation"""
        if row and hasattr(row, "page_id"):
            self.content_stack.set_visible_child_name(row.page_id)
            self.window_title.set_subtitle(row.get_title())
            # Refresh dashboard when navigating to it
            if row.page_id == "dashboard":
                self.dashboard_widget.refresh()

    def show_settings_page(self):
        """Navigate to settings page"""
        self.on_navigate_to(None, "settings")

    def on_navigate_to(self, widget, page_id):
        """Navigate to a specific page from dashboard"""
        self.content_stack.set_visible_child_name(page_id)
        if page_id in self.nav_rows:
            row = self.nav_rows[page_id]
            self.nav_list.select_row(row)

    def on_start_build_from_dashboard(self, widget):
        """Navigate to build page and start"""
        self.on_navigate_to(widget, "build")

    def on_profile_selected(self, widget, distro_key, edition):
        """Handle profile selection - configure build widget and navigate to build"""
        self.build_widget.set_build_config(distro_key, edition)
        self.on_navigate_to(widget, "build")

    def on_settings_saved(self, widget):
        """Handle settings saved - refresh dashboard and build widget"""
        self.dashboard_widget.refresh()
        self.build_widget.refresh()

    def on_build_requested(self, widget, config):
        """Handle build request from build widget"""
        from gui.dialogs.progress_dialog import BuildProgressDialog

        dialog = BuildProgressDialog(self, config, self.logger)
        dialog.connect("build-completed", self.on_build_completed)
        dialog.start_build()

    def on_build_completed(self, dialog, success, iso_path, error_msg):
        """Handle build completion"""
        if success:
            self.show_toast(_("Build completed! ISO: {0}").format(os.path.basename(iso_path)))
            self.history_widget.refresh()
        else:
            self.show_toast(_("Build failed: {0}").format(error_msg))
        self.dashboard_widget.refresh()

    def on_container_action(self, widget, action_name):
        """Handle container management actions"""
        pass  # Handled internally by ContainerWidget

    # ── Utilities ──

    def refresh_all(self):
        """Refresh all widgets"""
        self.dashboard_widget.refresh()
        self.build_widget.refresh()
        self.container_widget.refresh()

    def show_toast(self, message: str):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(5)
        self.toast_overlay.add_toast(toast)

    def show_error_dialog(self, message: str):
        """Show an error dialog"""
        dialog = Adw.AlertDialog(
            heading=_("Error"),
            body=message,
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self)
