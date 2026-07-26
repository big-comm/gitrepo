#
# gui/main_window.py - Main window for GTK4 interface
#

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.build_package import BuildPackage
from gitrepo.build_package.core.config import APP_DESC, APP_NAME, APP_VERSION
from gitrepo.build_package.core.repository_snapshot import RepositorySnapshot
from gitrepo.build_package.core.settings import Settings
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .dialogs.progress_dialog import OperationRunner
from .branch_actions import BranchActionsMixin
from .gtk_adapters import GTKConflictResolver, GTKMenuSystem
from .gtk_logger import GTKLogger
from .repository_actions import RepositoryActionsMixin
from .widgets.advanced_widget import AdvancedWidget
from .widgets.aur_widget import AURWidget
from .widgets.branch_widget import BranchWidget
from .widgets.commit_widget import CommitWidget
from .widgets.package_widget import PackageWidget
from .widgets.settings_widgets import BehaviorSettingsWidget, TokenSettingsWidget
from .widgets.page_shells import StackedPage, TabbedPage


class MainWindow(RepositoryActionsMixin, BranchActionsMixin, Adw.ApplicationWindow):
    """Main application window using GTK4 + Libadwaita"""

    __gtype_name__ = "MainWindow"

    def __init__(self, application):
        super().__init__(application=application)

        self.application = application
        self.build_package = None
        self._repository_context = _("Checking repository…")

        # Initialize settings first
        self.settings = Settings()

        # Initialize GTK components
        self.logger = GTKLogger(self)
        self.menu_system = GTKMenuSystem(self)  # New GTK menu system
        self.operation_runner = OperationRunner(self)

        # Create UI programmatically
        self.create_ui()

        # Initialize BuildPackage with GUI dependencies
        self.init_build_package()

        # Setup actions
        self.setup_actions()

        # Set window properties
        self.set_default_size(1100, 680)
        self.set_size_request(1000, 600)
        self.set_title(_("Build Package"))

    def create_ui(self):
        """Create the main UI programmatically"""

        # Main layout - Toast overlay as outermost wrapper
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # ── OverlaySplitView as main layout ──
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_min_sidebar_width(260)
        self.split_view.set_max_sidebar_width(320)
        self.split_view.set_sidebar_width_fraction(0.28)
        self.toast_overlay.set_child(self.split_view)

        # ══════════════════════════════════════
        # SIDEBAR PANE
        # ══════════════════════════════════════
        sidebar_toolbar = Adw.ToolbarView()

        # Match Build ISO: navigation starts at the top without a duplicated
        # application identity bar.
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar_box.add_css_class("build-package-sidebar")
        sidebar_box.set_margin_start(12)
        sidebar_box.set_margin_end(12)
        sidebar_box.set_margin_top(6)
        sidebar_box.set_margin_bottom(12)

        # Local repository navigation.
        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        self.nav_list.connect("row-selected", self.on_nav_row_selected)

        nav_group = Adw.PreferencesGroup()
        nav_group.add(self.nav_list)
        sidebar_box.append(nav_group)

        # GitHub automation is deliberately separated from local Git. These
        # pages remain discoverable even when their optional workflows are off.
        self.github_nav_list = Gtk.ListBox()
        self.github_nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.github_nav_list.add_css_class("navigation-sidebar")
        self.github_nav_list.connect("row-selected", self.on_nav_row_selected)

        github_group = Adw.PreferencesGroup()
        github_group.set_title(_("GitHub"))
        github_group.add(self.github_nav_list)
        sidebar_box.append(github_group)

        sidebar_scroll.set_child(sidebar_box)
        sidebar_toolbar.set_content(sidebar_scroll)
        sidebar_toolbar.add_css_class("sidebar-pane")

        self.split_view.set_sidebar(sidebar_toolbar)

        # ══════════════════════════════════════
        # CONTENT PANE
        # ══════════════════════════════════════
        content_toolbar = Adw.ToolbarView()

        # Content header bar
        self.content_header = Adw.HeaderBar()
        self.content_header.set_show_start_title_buttons(False)

        # Page title condenses into the header after the hero scrolls away.
        self.compact_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.compact_header_icon = Gtk.Image.new_from_icon_name("build-package-overview")
        self.compact_header_icon.set_pixel_size(18)
        self.compact_header_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.compact_header.append(self.compact_header_icon)
        self.window_title = Adw.WindowTitle(title=_("Start Here"), subtitle=self._repository_context)
        self.compact_header.append(self.window_title)
        self.compact_header.set_visible(False)
        self.content_header.set_title_widget(self.compact_header)
        self.content_header.add_css_class("build-package-expanded-header")

        self._create_hamburger_menu()

        content_toolbar.add_top_bar(self.content_header)

        # Content stack with scroll wrapper
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

    def init_build_package(self):
        """Initialize BuildPackage with GUI logger and menu"""
        try:
            self.build_package = BuildPackage(
                logger=self.logger,
                menu_system=self.menu_system,  # Use new GTK menu system
            )

            # Initialize conflict resolver with GTK support
            self.build_package.conflict_resolver = GTKConflictResolver(
                logger=self.logger,
                menu_system=self.menu_system,
                parent_window=self,
                strategy=self.settings.get("conflict_strategy", "interactive"),
            )

            # Set settings in build_package
            self.build_package.settings = self.settings

            # Create navigation and pages after build_package is ready
            self.create_navigation_and_pages()

            self.refresh_all_widgets()

        except Exception as e:
            self.show_error_dialog(_("Failed to initialize: {0}").format(str(e)))

    def create_navigation_and_pages(self):
        """Create the four destinations of the packaging journey."""

        # Publishing owns the workspace facts it acts on; packaging and the
        # settings group their sibling contexts behind a view switcher.
        self.commit_widget = CommitWidget(self.build_package)
        self.branch_widget = BranchWidget(self.build_package)
        self.package_widget = PackageWidget(self.build_package, self.settings, show_hero=False)
        self.aur_widget = AURWidget(self.build_package, self.settings, show_hero=False)
        self.behavior_widget = BehaviorSettingsWidget(self, self.settings, show_hero=False)
        self.tokens_widget = TokenSettingsWidget(self, show_hero=False)
        self.advanced_widget = AdvancedWidget(self.build_package, show_hero=False)

        self.packages_page = TabbedPage(
            "build-package-package",
            _("Build and publish packages"),
            _("Start a build on GitHub Actions from this repository or from a community source."),
            [
                ("repository", _("This repository"), "build-package-package", self.package_widget),
                ("aur", _("AUR"), "build-package-aur", self.aur_widget),
            ],
        )
        # Settings stay one scroll: behavior, then GitHub access, then the
        # destructive maintenance that keeps its own warning banner.
        self.settings_page = StackedPage(
            "build-package-advanced",
            _("Settings and repository maintenance"),
            _("Local Git behavior, GitHub access, and the destructive operations that need confirmation."),
            [self.behavior_widget, self.tokens_widget, self.advanced_widget],
        )

        self.connect_widget_signals()

        pages = [
            (self.commit_widget, "publish", _("Publish Changes"), "build-package-commit", "local"),
            (self.branch_widget, "branches", _("Organize Branches"), "build-package-branches", "local"),
            (self.packages_page, "packages", _("Packages"), "build-package-package", "github"),
            (self.settings_page, "settings", _("Settings"), "build-package-advanced", "local"),
        ]

        self.nav_rows = {}
        self.page_headers = {}

        for widget, page_id, title, icon_name, section in pages:
            self.content_stack.add_titled_with_icon(widget, page_id, title, icon_name)
            self.page_headers[page_id] = (title, icon_name)
            self._append_navigation_row(page_id, title, icon_name, section)

        self.nav_list.select_row(self.nav_list.get_row_at_index(0))
        self.content_stack.set_visible_child_name("publish")

        GLib.idle_add(self.update_nav_badges)

    def _append_navigation_row(self, page_id, title, icon_name, section="local"):
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.set_margin_start(10)
        content.set_margin_end(10)
        content.set_margin_top(6)
        content.set_margin_bottom(6)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        content.append(icon)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.set_hexpand(True)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        content.append(title_label)

        badge_label = Gtk.Label()
        badge_label.add_css_class("badge")
        badge_label.add_css_class("numeric")
        badge_label.set_visible(False)
        badge_label.set_valign(Gtk.Align.CENTER)
        content.append(badge_label)

        button = Gtk.Button(child=content)
        button.add_css_class("navigation-button")
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])
        target_list = self.github_nav_list if section == "github" else self.nav_list
        target_list.append(button)

        nav_row = button.get_parent()
        nav_row.page_id = page_id
        nav_row.badge = badge_label
        nav_row.nav_list = target_list
        button.connect("clicked", lambda _button: target_list.select_row(nav_row))
        self.nav_rows[page_id] = nav_row

    def connect_widget_signals(self):
        """Connect signals from all widgets"""

        # Overview widget signals
        self.commit_widget.connect("quick-action", self.on_quick_action)
        self.commit_widget.connect("refresh-requested", self.on_overview_refresh)

        # Commit widget signals
        self.commit_widget.connect("commit-requested", self.on_commit_requested)
        self.commit_widget.connect("pull-requested", self.on_pull_requested)
        self.commit_widget.connect("undo-commit-requested", self.on_undo_commit_requested)

        self.package_widget.connect("package-build-requested", self.on_package_build_requested)
        self.package_widget.connect("commit-and-build-requested", self.on_commit_and_build_requested)
        self.aur_widget.connect("aur-build-requested", self.on_aur_build_requested)

        # Branch widget signals
        self.branch_widget.connect("branch-selected", self.on_branch_selected)
        self.branch_widget.connect("merge-requested", self.on_merge_requested)
        self.branch_widget.connect("cleanup-requested", self.on_branch_cleanup_requested)

        # Advanced widget signals
        self.advanced_widget.connect("cleanup-branches-requested", self.on_cleanup_branches_requested)
        self.advanced_widget.connect("cleanup-actions-requested", self.on_cleanup_actions_requested)
        self.advanced_widget.connect("cleanup-tags-requested", self.on_cleanup_tags_requested)
        self.advanced_widget.connect("revert-commit-requested", self.on_revert_commit_requested)

    def _create_hamburger_menu(self):
        """Create a compact menu for secondary application information."""
        # Keep the window menu aligned with the application-wide actions.
        menu = Gio.Menu()
        tools_section = Gio.Menu()
        tools_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append_section(None, tools_section)

        about_section = Gio.Menu()
        about_section.append(_("About Build Package"), "app.about")
        menu.append_section(None, about_section)

        # Create menu button with hamburger icon
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text(_("Main Menu"))

        # Add to content header bar (pack_end places it on the right, before window controls)
        self.content_header.pack_end(menu_button)

    def setup_actions(self):
        """Setup application actions"""
        # Refresh action
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh_activated)
        self.add_action(refresh_action)

        # Pull latest action
        pull_action = Gio.SimpleAction.new("pull", None)
        pull_action.connect("activate", self.on_pull_activated)
        self.add_action(pull_action)

        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences_activated)
        self.add_action(preferences_action)

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activated)
        self.add_action(about_action)

    def on_preferences_activated(self, _action, _param):
        """Keep Ctrl+, useful while making settings visible in the sidebar."""
        self.switch_to_page("settings")

    def on_about_activated(self, _action, _param):
        """Handle about action - show About dialog"""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name=APP_NAME,
            application_icon="org.bigcommunity.buildpackage",
            developer_name="BigCommunity Team",
            version=APP_VERSION,
            copyright="Copyright © 2024-2025 BigCommunity Team",
            license_type=Gtk.License.MIT_X11,
            website="https://github.com/big-comm/build-package",
            issue_url="https://github.com/big-comm/build-package/issues",
            developers=["BigCommunity Team <team@bigcommunity.org>"],
            comments=APP_DESC,
        )
        about.present()

    def _apply_header_snapshot(self, snapshot):
        if not snapshot.is_repository:
            self._repository_context = _("No repository")
        else:
            repository_name = snapshot.repository_name or _("Local Git repository")
            branch = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
            self._repository_context = _("{0} • {1}").format(repository_name, branch)
        self.window_title.set_subtitle(self._repository_context)

    # Signal handlers for widget operations
    def on_refresh_activated(self, _action, _param):
        """Handle refresh action"""
        self.refresh_all_widgets()
        self.show_toast(_("Refreshing status…"))

    def on_pull_activated(self, _action, _param):
        """Handle pull latest action"""
        self.on_pull_requested(None)

    def show_toast(self, message):
        """Show success toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def show_error_toast(self, message):
        """Show error toast for minor validation messages (5 s timeout)."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        toast.add_css_class("error")
        self.toast_overlay.add_toast(toast)

    def show_error_dialog(self, message: str) -> None:
        """Show persistent AlertDialog for critical operation failures.

        Use instead of show_error_toast when the error requires user
        acknowledgement: failed push/pull, auth errors, init failures.
        """
        dialog = Adw.AlertDialog(heading=_("Error"), body=message)
        dialog.add_response("close", _("Close"))
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present(self)

    def show_info_toast(self, message):
        """Show info toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        # toast.add_css_class("info")
        self.toast_overlay.add_toast(toast)

    def on_nav_row_selected(self, list_box, row):
        """Handle navigation row selection."""
        if row and hasattr(row, "page_id"):
            other_list = self.github_nav_list if list_box is self.nav_list else self.nav_list
            if other_list.get_selected_row() is not None:
                other_list.unselect_all()
            self._show_page(row.page_id)

    def switch_to_page(self, page_id):
        """Switch pages while keeping sidebar selection and header context in sync."""
        row = self.nav_rows.get(page_id)
        if row and row.nav_list.get_selected_row() is not row:
            row.nav_list.select_row(row)
            return
        self._show_page(page_id)

    def _show_page(self, page_id):
        if page_id not in self.page_headers:
            return
        self.content_stack.set_visible_child_name(page_id)
        title, icon_name = self.page_headers[page_id]
        self.window_title.set_title(title)
        self.window_title.set_subtitle(self._repository_context)
        self.compact_header_icon.set_from_icon_name(icon_name)
        self._apply_page_footer(page_id)
        self._reset_content_scroll()
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

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
            self.content_header.remove_css_class("build-package-expanded-header")
        else:
            self.content_header.add_css_class("build-package-expanded-header")
        self.compact_header.set_visible(is_condensed)

    def refresh_features(self):
        """Reconcile optional workflow content without changing navigation."""
        self.package_widget.sync_feature_enabled()
        self.aur_widget.sync_feature_enabled()
        self.behavior_widget.sync_from_settings()

    def refresh_all_widgets(self):
        """Capture repository state off the GTK main loop and discard stale replies."""
        self._snapshot_generation = getattr(self, "_snapshot_generation", 0) + 1
        generation = self._snapshot_generation
        self._set_repository_checking()

        def capture():
            snapshot = RepositorySnapshot.capture()
            GLib.idle_add(self._apply_repository_snapshot, generation, snapshot)

        threading.Thread(target=capture, daemon=True).start()

    def _set_repository_checking(self):
        self._repository_context = _("Checking repository…")
        self.window_title.set_subtitle(self._repository_context)
        for attribute in ("repo_status_label", "branch_status_label", "changes_status_label"):
            if hasattr(self, attribute):
                getattr(self, attribute).set_text(_("Checking…"))

    def _apply_repository_snapshot(self, generation, snapshot):
        if generation != self._snapshot_generation:
            return False
        self._repository_snapshot = snapshot
        self.build_package.is_git_repo = snapshot.is_repository
        self._apply_header_snapshot(snapshot)
        for attribute in ("commit_widget", "package_widget", "branch_widget", "advanced_widget"):
            widget = getattr(self, attribute, None)
            if widget and hasattr(widget, "apply_snapshot"):
                widget.apply_snapshot(snapshot)
        self.update_nav_badges(snapshot)
        return False

    def update_nav_badges(self, snapshot=None):
        """Update badges without running a Git probe on the GTK main loop."""
        if not hasattr(self, "nav_rows"):
            return False
        snapshot = snapshot or getattr(self, "_repository_snapshot", None)
        if not snapshot or "publish" not in self.nav_rows:
            return False
        row = self.nav_rows["publish"]
        row.badge.remove_css_class("warning")
        changes = len(snapshot.changed_files) if snapshot.has_changes else 0
        row.badge.set_visible(changes > 0)
        if changes:
            row.badge.set_text(str(changes))
            row.badge.add_css_class("warning")
            label = _("Commit ({0} pending changes)").format(changes)
        elif snapshot.has_changes is None:
            label = _("Commit (status unavailable)")
        else:
            label = _("Commit")
        row.update_property([Gtk.AccessibleProperty.LABEL], [label])
        return False

    def send_system_notification(self, title, body, icon="package-x-generic"):
        """Send a desktop notification through the owning application."""
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon.new(icon))
        notification.set_priority(Gio.NotificationPriority.NORMAL)
        if self.application:
            self.application.send_notification(None, notification)
