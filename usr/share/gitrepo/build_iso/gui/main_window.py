#
# gui/main_window.py - Main window for Build ISO GTK4 interface
#

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import APP_NAME
from gitrepo.build_iso.core.container_manager import ContainerManager, capture_disk_status
from gitrepo.build_iso.core.settings import Settings
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from .widgets.build_widget import BuildWidget
from .widgets.container_widget import ContainerWidget
from .widgets.history_widget import HistoryWidget
from .widgets.settings_widget import SettingsWidget


class MainWindow(Adw.ApplicationWindow):
    """Main application window using GTK4 + Libadwaita"""

    __gtype_name__ = "BuildISOMainWindow"

    def __init__(self, application):
        super().__init__(application=application)

        self.application = application
        self.settings = Settings()
        self._environment_generation = 0
        # Create UI
        self.create_ui()
        self.create_navigation_and_pages()
        self.setup_actions()

        # Window properties
        self.set_default_size(1100, 680)
        self.set_size_request(1000, 600)
        self.set_title(APP_NAME)
        GLib.idle_add(self.refresh_environment)

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
        self.nav_list.connect("row-selected", self.on_nav_row_selected)

        nav_group = Adw.PreferencesGroup()
        nav_group.add(self.nav_list)
        sidebar_box.append(nav_group)

        sidebar_scroll.set_child(sidebar_box)
        sidebar_toolbar.set_content(sidebar_scroll)
        sidebar_toolbar.add_css_class("sidebar-pane")

        self.split_view.set_sidebar(sidebar_toolbar)

        # ── CONTENT ──
        content_toolbar = Adw.ToolbarView()

        self.content_header = Adw.HeaderBar()
        self.content_header.set_show_start_title_buttons(False)

        self.compact_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.compact_header_icon = Gtk.Image()
        self.compact_header_icon.set_pixel_size(18)
        self.compact_header_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.compact_header.append(self.compact_header_icon)
        self.compact_header_title = Gtk.Label()
        self.compact_header_title.add_css_class("heading")
        self.compact_header.append(self.compact_header_title)
        self.compact_header.set_visible(False)
        self.content_header.set_title_widget(self.compact_header)

        self._create_hamburger_menu()
        content_toolbar.add_top_bar(self.content_header)

        self.scrolled_content = Gtk.ScrolledWindow()
        self.scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_content.set_vexpand(True)
        self.scrolled_content.set_hexpand(True)
        self.scrolled_content.set_propagate_natural_height(True)
        self.scrolled_content.get_vadjustment().connect("value-changed", self._on_content_scroll_changed)

        self.content_stack = Adw.ViewStack()
        self.content_stack.set_vhomogeneous(False)
        self.content_stack.add_css_class("content-canvas")
        self.scrolled_content.set_child(self.content_stack)

        content_toolbar.set_content(self.scrolled_content)
        # Pages that own a primary action publish a footer; it lives outside the
        # scrolled area so the action never scrolls out of reach.
        self._content_toolbar = content_toolbar
        self._visible_footer = None
        self.split_view.set_content(content_toolbar)

    def create_navigation_and_pages(self):
        """Create the three destinations of the ISO journey."""

        # The environment is a prerequisite, not a journey: it lives inside the
        # settings page and is announced on the build page when it breaks.
        self.container_widget = ContainerWidget(self.settings)
        self.build_widget = BuildWidget(self.settings)
        self.history_widget = HistoryWidget(self.settings)
        self.settings_widget = SettingsWidget(self.settings)
        self.settings_widget.append_environment_section(self.container_widget)

        self.connect_widget_signals()

        pages = [
            (self.build_widget, "build", _("Create ISO"), "build-iso-create"),
            (self.history_widget, "history", _("Generated ISOs"), "build-iso-history"),
            (self.settings_widget, "settings", _("Settings"), "build-iso-settings"),
        ]

        self.nav_rows = {}
        self.page_headers = {}

        for widget, page_id, title, icon_name in pages:
            self.content_stack.add_titled_with_icon(widget, page_id, title, icon_name)
            self.page_headers[page_id] = (title, icon_name)
            self._append_navigation_row(page_id, title, icon_name)

        self.nav_list.select_row(self.nav_list.get_row_at_index(0))
        self.content_stack.set_visible_child_name("build")

    def _append_navigation_row(self, page_id, title, icon_name):
        nav_row = Adw.ActionRow(title=title)
        nav_row.set_activatable(True)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(24)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        nav_row.add_prefix(icon)

        badge_label = Gtk.Label()
        badge_label.add_css_class("badge")
        badge_label.add_css_class("numeric")
        badge_label.set_visible(False)
        badge_label.set_valign(Gtk.Align.CENTER)
        nav_row.add_suffix(badge_label)

        nav_row.update_property([Gtk.AccessibleProperty.LABEL], [title])
        nav_row.page_id = page_id
        nav_row.badge = badge_label
        nav_row.connect("activated", lambda _row: self.nav_list.select_row(nav_row))
        self.nav_list.append(nav_row)
        self.nav_rows[page_id] = nav_row

    def connect_widget_signals(self):
        """Connect signals from widgets"""
        self.build_widget.connect("build-requested", self.on_build_requested)
        self.build_widget.connect("open-environment", lambda _widget: self.on_navigate_to(_widget, "settings"))
        self.settings_widget.connect("settings-saved", self.on_settings_saved)
        self.container_widget.connect("refresh-requested", lambda _widget: self.refresh_environment())

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
        refresh_action.connect("activate", lambda _action, _param: self.refresh_all())
        self.add_action(refresh_action)

    # ── Navigation ──

    def on_nav_row_selected(self, _listbox, row):
        """Handle sidebar navigation"""
        if row and hasattr(row, "page_id"):
            self.content_stack.set_visible_child_name(row.page_id)
            title, icon_name = self.page_headers[row.page_id]
            self.compact_header_title.set_text(title)
            self.compact_header_icon.set_from_icon_name(icon_name)
            self._apply_page_footer(row.page_id)
            self._reset_content_scroll()
            if row.page_id == "build":
                self.build_widget.ensure_catalog_loaded()
            elif row.page_id == "settings":
                self.refresh_environment()

    def _apply_page_footer(self, page_id):
        """Show only the footer owned by the visible page."""
        page = self.content_stack.get_child_by_name(page_id)
        footer = getattr(page, "page_footer", None)
        if footer is self._visible_footer:
            return
        if self._visible_footer is not None:
            self._content_toolbar.remove(self._visible_footer)
        if footer is not None:
            self._content_toolbar.add_bottom_bar(footer)
        self._visible_footer = footer

    def _reset_content_scroll(self):
        adjustment = self.scrolled_content.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())
        self._set_header_condensed(False)
        GLib.idle_add(self._finish_content_scroll_reset)

    def _finish_content_scroll_reset(self):
        adjustment = self.scrolled_content.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())
        self._set_header_condensed(False)
        return False

    def _on_content_scroll_changed(self, adjustment):
        self._set_header_condensed(adjustment.get_value() > 24)

    def _set_header_condensed(self, is_condensed):
        if is_condensed:
            self.content_header.remove_css_class("build-iso-expanded-header")
        else:
            self.content_header.add_css_class("build-iso-expanded-header")
        self.compact_header.set_visible(is_condensed)

    def on_navigate_to(self, widget, page_id):
        """Navigate to a specific page from dashboard"""
        self.content_stack.set_visible_child_name(page_id)
        if page_id in self.nav_rows:
            row = self.nav_rows[page_id]
            self.nav_list.select_row(row)

    def on_settings_saved(self, widget):
        """Handle settings saved - refresh dashboard and build widget"""
        self.refresh_environment()
        self.build_widget.refresh()

    def on_build_requested(self, widget, config):
        """Handle build request from build widget"""
        from gitrepo.build_iso.gui.dialogs.progress_dialog import BuildProgressDialog

        dialog = BuildProgressDialog(self, config)
        dialog.connect("build-completed", self.on_build_completed)
        dialog.start_build()

    def on_build_completed(self, dialog, success, iso_path, error_msg):
        """Handle build completion"""
        if success:
            self.show_toast(_("Build completed! ISO: {0}").format(os.path.basename(iso_path)))
            self.history_widget.refresh()
        else:
            self.show_toast(_("Build failed: {0}").format(error_msg))
        self._notify_build_completed(success, iso_path, error_msg)
        self.refresh_environment()

    def _notify_build_completed(self, success, iso_path, error_msg):
        """Reach the user with a desktop notification after a long build."""
        if success:
            notification = Gio.Notification.new(_("ISO build finished"))
            notification.set_body(
                _("{0} is ready in {1}").format(os.path.basename(iso_path), os.path.dirname(iso_path))
            )
            if iso_path:
                target = GLib.Variant.new_string(os.path.dirname(iso_path))
                notification.set_default_action_and_target_value("app.open-build-folder", target)
                notification.add_button_with_target_value(_("Open Folder"), "app.open-build-folder", target)
        else:
            notification = Gio.Notification.new(_("ISO build failed"))
            notification.set_body(error_msg or _("Open Build ISO to review the terminal log."))
            notification.set_priority(Gio.NotificationPriority.HIGH)
        self.application.send_notification("build-iso-result", notification)

    # ── Utilities ──

    def refresh_all(self):
        """Refresh all widgets"""
        self.refresh_environment()
        self.build_widget.refresh()

    def refresh_environment(self):
        """Probe the environment once and distribute the resulting snapshot."""
        self._environment_generation += 1
        generation = self._environment_generation
        self.container_widget.set_checking()
        thread = threading.Thread(target=self._probe_environment, args=(generation,), daemon=True)
        thread.start()
        return False

    def _probe_environment(self, generation: int) -> None:
        manager = ContainerManager(self.settings.container_engine_preference)
        status = manager.capture_status(self.settings.container_image)
        disk_status = capture_disk_status(self.settings.output_dir)
        GLib.idle_add(self._apply_environment_status, generation, manager, status, disk_status)

    def _apply_environment_status(self, generation, manager, status, disk_status):
        if generation != self._environment_generation:
            return False
        self.build_widget.apply_environment(status, disk_status)
        self.container_widget.apply_status(manager, status)
        self._update_environment_badge(status)
        return False

    def _update_environment_badge(self, status):
        """Count the environment problems that block a build on the sidebar."""
        pending = int(not status.is_engine_ready) + int(not status.is_image_available)
        row = self.nav_rows.get("settings")
        if row is None:
            return
        row.badge.set_text(str(pending))
        row.badge.set_visible(pending > 0)
        row.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Settings — {0} environment item(s) need attention").format(pending) if pending else _("Settings")],
        )

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
