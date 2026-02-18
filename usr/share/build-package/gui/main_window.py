#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_window.py - Main window for GTK4 interface
#

import os
import threading

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.build_package import BuildPackage
from core.config import APP_VERSION
from core.git_utils import GitUtils
from core.settings import Settings
from core.translation_utils import _
from gi.repository import Adw, Gio, GLib, Gtk

from .dialogs.preferences_dialog import PreferencesDialog
from .dialogs.progress_dialog import OperationRunner
from .dialogs.welcome_dialog import WelcomeDialog, should_show_welcome
from .gtk_adapters import GTKConflictResolver, GTKMenuSystem
from .gtk_logger import GTKLogger
from .gtk_menu import GTKMenu
from .widgets.advanced_widget import AdvancedWidget
from .widgets.aur_widget import AURWidget
from .widgets.branch_widget import BranchWidget
from .widgets.commit_widget import CommitWidget
from .widgets.overview_widget import OverviewWidget
from .widgets.package_widget import PackageWidget


class MainWindow(Adw.ApplicationWindow):
    """Main application window using GTK4 + Libadwaita"""

    __gtype_name__ = "MainWindow"

    def __init__(self, application):
        super().__init__(application=application)

        self.application = application
        self.build_package = None

        # Initialize settings first
        self.settings = Settings()

        # Initialize GTK components
        self.logger = GTKLogger(self)
        self.menu_system = GTKMenuSystem(self)  # New GTK menu system
        self.menu = GTKMenu(self)  # Keep old for compatibility
        self.operation_runner = OperationRunner(self)

        # Create UI programmatically
        self.create_ui()

        # Initialize BuildPackage with GUI dependencies
        self.init_build_package()

        # Setup actions
        self.setup_actions()

        # Set window properties
        self.set_default_size(1000, 600)
        self.set_size_request(800, 600)  # Force minimum size
        self.set_title(_("Build Package"))

        # Show welcome dialog on first run (after window is shown)
        GLib.idle_add(self._check_show_welcome)

    def create_ui(self):
        """Create the main UI programmatically"""

        # Main layout - Toast overlay as outermost wrapper
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # ── OverlaySplitView as main layout ──
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_min_sidebar_width(260)
        self.split_view.set_max_sidebar_width(320)
        self.split_view.set_sidebar_width_fraction(0.32)
        self.toast_overlay.set_child(self.split_view)

        # ══════════════════════════════════════
        # SIDEBAR PANE
        # ══════════════════════════════════════
        sidebar_toolbar = Adw.ToolbarView()

        # Sidebar header bar
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)

        # App icon on the left
        app_icon = Gtk.Image.new_from_icon_name("gitrepo")
        app_icon.set_pixel_size(20)
        sidebar_header.pack_start(app_icon)

        # Centered app title
        app_title = Gtk.Label(label=_("Build Package"))
        app_title.add_css_class("heading")
        sidebar_header.set_title_widget(app_title)

        sidebar_toolbar.add_top_bar(sidebar_header)

        # Scrollable sidebar content
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        sidebar_box.set_margin_start(12)
        sidebar_box.set_margin_end(12)
        sidebar_box.set_margin_top(6)
        sidebar_box.set_margin_bottom(12)

        # Navigation list inside a PreferencesGroup for card-style look
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

        # ══════════════════════════════════════
        # CONTENT PANE
        # ══════════════════════════════════════
        content_toolbar = Adw.ToolbarView()

        # Content header bar
        self.content_header = Adw.HeaderBar()
        self.content_header.set_show_start_title_buttons(False)

        # Center title: repo name + branch as subtitle
        self.window_title = Adw.WindowTitle(title=_("No repository"))
        self.content_header.set_title_widget(self.window_title)

        # Add hamburger menu button (on the right)
        self._create_hamburger_menu()

        content_toolbar.add_top_bar(self.content_header)

        # Content stack with scroll wrapper
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

            # Populate header title with repo info immediately
            self.refresh_status()

        except Exception as e:
            self.show_error_toast(_("Failed to initialize: {0}").format(str(e)))

    def create_navigation_and_pages(self):
        """Create navigation items and corresponding pages based on enabled features"""

        # Core widgets (always visible)
        self.overview_widget = OverviewWidget(self.build_package)
        self.commit_widget = CommitWidget(self.build_package)
        self.branch_widget = BranchWidget(self.build_package)
        self.advanced_widget = AdvancedWidget(self.build_package)

        # Optional widgets (based on feature flags)
        if self.settings.get("package_features_enabled", False):
            self.package_widget = PackageWidget(self.build_package)
        else:
            self.package_widget = None

        if self.settings.get("aur_features_enabled", False):
            self.aur_widget = AURWidget(self.build_package)
        else:
            self.aur_widget = None

        # Connect widget signals
        self.connect_widget_signals()

        # Build pages list dynamically
        pages = [
            (self.overview_widget, "overview", _("Overview"), "view-list-symbolic"),
            (
                self.commit_widget,
                "commit",
                _("Commit and Push"),
                "document-save-symbolic",
            ),
        ]

        # Add package feature if enabled
        if self.package_widget:
            pages.append((
                self.package_widget,
                "package",
                _("Generate Package"),
                "package-x-generic-symbolic",
            ))

        # Add AUR feature if enabled
        if self.aur_widget:
            pages.append((
                self.aur_widget,
                "aur",
                _("AUR Package"),
                "system-software-install-symbolic",
            ))

        # Always show branches and advanced
        pages.extend([
            (
                self.branch_widget,
                "branches",
                _("Branches"),
                "media-playlist-consecutive-symbolic",
            ),
            (
                self.advanced_widget,
                "advanced",
                _("Advanced"),
                "preferences-system-symbolic",
            ),
        ])

        # Store nav rows for badge updates
        self.nav_rows = {}

        for widget, page_id, title, icon_name in pages:
            self.content_stack.add_titled_with_icon(widget, page_id, title, icon_name)

            # Create navigation row
            nav_row = Adw.ActionRow()
            nav_row.set_title(title)
            nav_row.set_activatable(True)
            nav_row.page_id = page_id

            # Add icon (decorative — row title is the accessible label)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            nav_row.add_prefix(icon)

            # Add badge placeholder (hidden by default)
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
        self.content_stack.set_visible_child_name("overview")

        # Initial badge update
        GLib.idle_add(self.update_nav_badges)

    def connect_widget_signals(self):
        """Connect signals from all widgets"""

        # Overview widget signals
        self.overview_widget.connect("quick-action", self.on_quick_action)
        self.overview_widget.connect("refresh-requested", self.on_overview_refresh)

        # Commit widget signals
        self.commit_widget.connect("commit-requested", self.on_commit_requested)
        self.commit_widget.connect("push-requested", self.on_pull_requested)
        self.commit_widget.connect(
            "undo-commit-requested", self.on_undo_commit_requested
        )

        # Package widget signals (only if enabled)
        if self.package_widget:
            self.package_widget.connect(
                "package-build-requested", self.on_package_build_requested
            )
            self.package_widget.connect(
                "commit-and-build-requested", self.on_commit_and_build_requested
            )

        # AUR widget signals (only if enabled)
        if self.aur_widget:
            self.aur_widget.connect("aur-build-requested", self.on_aur_build_requested)

        # Branch widget signals
        self.branch_widget.connect("branch-selected", self.on_branch_selected)
        self.branch_widget.connect("merge-requested", self.on_merge_requested)
        self.branch_widget.connect(
            "cleanup-requested", self.on_branch_cleanup_requested
        )

        # Advanced widget signals
        self.advanced_widget.connect(
            "cleanup-branches-requested", self.on_cleanup_branches_requested
        )
        self.advanced_widget.connect(
            "cleanup-actions-requested", self.on_cleanup_actions_requested
        )
        self.advanced_widget.connect(
            "cleanup-tags-requested", self.on_cleanup_tags_requested
        )
        self.advanced_widget.connect(
            "revert-commit-requested", self.on_revert_commit_requested
        )

    def _create_hamburger_menu(self):
        """Create hamburger menu button with Preferences and About options"""
        # Create menu model
        menu = Gio.Menu()

        # Add menu items
        menu.append(_("Preferences"), "win.preferences")
        menu.append(_("About"), "win.about")

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

        # Welcome action (to show welcome dialog manually)
        welcome_action = Gio.SimpleAction.new("show-welcome", None)
        welcome_action.connect("activate", self.on_show_welcome_activated)
        self.add_action(welcome_action)

        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences_activated)
        self.add_action(preferences_action)

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activated)
        self.add_action(about_action)

    def _check_show_welcome(self):
        """Check if welcome dialog should be shown and show it"""
        if should_show_welcome(self.settings):
            self.show_welcome_dialog()
        return False  # Don't repeat idle callback

    def show_welcome_dialog(self):
        """Show the welcome dialog"""
        dialog = WelcomeDialog(self, self.settings)
        dialog.present()

    def on_show_welcome_activated(self, action, param):
        """Handle show welcome action"""
        self.show_welcome_dialog()

    def on_preferences_activated(self, action, param):
        """Handle preferences action - show Preferences dialog"""
        dialog = PreferencesDialog(self, self.settings)
        dialog.present(self)  # Pass parent for modal behavior

    def on_about_activated(self, action, param):
        """Handle about action - show About dialog"""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="GitRepo",
            application_icon="gitrepo",
            developer_name="BigCommunity",
            version=APP_VERSION,
            copyright="© 2024-2025 BigCommunity",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/big-comm/gitrepo",
            issue_url="https://github.com/big-comm/gitrepo/issues",
            developers=["BigCommunity Team"],
            comments=_("Git repository manager for building and deploying packages"),
        )
        about.present()

    def refresh_status(self):
        """Refresh repository status display"""
        if not self.build_package:
            return

        # Repository status
        if self.build_package.is_git_repo:
            repo_name = GitUtils.get_repo_name()
            if hasattr(self, "repo_status_label"):
                self.repo_status_label.set_text(
                    repo_name if repo_name else _("Git Repository")
                )
                self.repo_status_label.add_css_class("success")
            # Update header bar title with repo name (already in owner/repo format)
            if repo_name:
                self.window_title.set_title(repo_name)
        else:
            if hasattr(self, "repo_status_label"):
                self.repo_status_label.set_text(_("Not a Git repository"))
                self.repo_status_label.add_css_class("warning")
            self.window_title.set_title(_("No repository"))

        # Current branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            if hasattr(self, "branch_status_label"):
                self.branch_status_label.set_text(current_branch)
            # Update header bar subtitle with branch name
            self.window_title.set_subtitle(f"⎇ {current_branch}")
        else:
            if hasattr(self, "branch_status_label"):
                self.branch_status_label.set_text(_("Unknown"))
            self.window_title.set_subtitle("")

        # Changes status
        if hasattr(self, "changes_status_label"):
            if GitUtils.has_changes():
                self.changes_status_label.set_text(_("Uncommitted changes"))
                self.changes_status_label.add_css_class("warning")
            else:
                self.changes_status_label.set_text(_("Clean working tree"))
                self.changes_status_label.add_css_class("success")

    # Signal handlers for widget operations
    def on_quick_action(self, widget, action_id):
        """Handle quick action from overview"""
        if action_id == "commit":
            self.switch_to_page("commit")
        elif action_id == "pull":
            self.on_pull_requested(widget)
        elif action_id == "package_testing":
            self.switch_to_page("package")
            # Could pre-select testing package type
        elif action_id == "package_stable":
            self.switch_to_page("package")
        elif action_id == "aur":
            self.switch_to_page("aur")

    def on_overview_refresh(self, widget):
        """Handle overview refresh request"""
        self.refresh_all_widgets()

    def on_commit_requested(self, widget, commit_message):
        """Handle commit request from commit widget - show branch confirmation first"""
        current_branch = GitUtils.get_current_branch()
        username = self.build_package.github_user_name or "unknown"
        dev_branch = f"dev-{username}"

        # Store commit message for later use
        self._pending_commit_message = commit_message

        # Check if on a protected branch
        is_protected = current_branch in ["main", "master"]

        # Show confirmation dialog
        self._show_commit_branch_dialog(current_branch, dev_branch, is_protected)

    def _show_commit_branch_dialog(self, current_branch, dev_branch, is_protected):
        """Show dialog to confirm target branch for commit"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)

        if is_protected:
            dialog.set_heading(_("⚠️ Commit to Protected Branch?"))
            dialog.set_body(
                _(
                    "You are about to commit directly to '{0}'.\n\n"
                    "This is usually protected. Consider using your development branch instead."
                ).format(current_branch)
            )
        else:
            dialog.set_heading(_("Confirm Commit Branch"))
            dialog.set_body(_("Choose where to commit your changes:"))

        # Visual content
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(400, -1)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Current branch info
        current_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        current_box.set_halign(Gtk.Align.CENTER)

        icon_name = "dialog-warning-symbolic" if is_protected else "emblem-ok-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        if is_protected:
            icon.add_css_class("warning")
        else:
            icon.add_css_class("success")
        current_box.append(icon)

        branch_label = Gtk.Label()
        if is_protected:
            branch_label.set_markup(
                _("<b>Current:</b> <span foreground='#FF6B6B'>{0}</span>").format(
                    current_branch
                )
            )
        else:
            branch_label.set_markup(
                _("<b>Current:</b> <span foreground='#00CED1'>{0}</span>").format(
                    current_branch
                )
            )
        current_box.append(branch_label)

        content_box.append(current_box)

        # Dev branch suggestion
        if current_branch != dev_branch:
            suggestion_label = Gtk.Label()
            suggestion_label.set_markup(
                _(
                    "<span foreground='#888888'>Your dev branch:</span> <span foreground='#32CD32'>{0}</span>"
                ).format(dev_branch)
            )
            suggestion_label.set_margin_top(8)
            content_box.append(suggestion_label)

        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)

        # Responses
        dialog.add_response("cancel", _("Cancel"))

        if current_branch != dev_branch:
            dialog.add_response("dev", _("Use {0}").format(dev_branch))
            dialog.set_response_appearance("dev", Adw.ResponseAppearance.SUGGESTED)

        # Add main branch option if not already on main
        if current_branch not in ["main", "master"]:
            dialog.add_response("main", _("Send to main"))

        if is_protected:
            dialog.add_response(
                "current", _("Commit to {0} anyway").format(current_branch)
            )
            dialog.set_response_appearance(
                "current", Adw.ResponseAppearance.DESTRUCTIVE
            )
        else:
            dialog.add_response("current", _("Commit to {0}").format(current_branch))
            if current_branch == dev_branch:
                dialog.set_response_appearance(
                    "current", Adw.ResponseAppearance.SUGGESTED
                )

        dialog.set_default_response(
            "dev" if current_branch != dev_branch else "current"
        )
        dialog.set_close_response("cancel")

        dialog.connect(
            "response", self._on_commit_branch_response, current_branch, dev_branch
        )
        dialog.present()

    def _on_commit_branch_response(self, dialog, response, current_branch, dev_branch):
        """Handle commit branch dialog response"""
        if response == "cancel":
            self._pending_commit_message = None
            return

        # Determine target branch based on response
        if response == "main":
            target_branch = "main"
        elif response == "dev":
            target_branch = dev_branch
        else:
            target_branch = current_branch

        # If we need to switch branches first
        if target_branch != current_branch:
            self._switch_then_commit(target_branch, self._pending_commit_message)
        else:
            self._do_commit(self._pending_commit_message, target_branch)

        self._pending_commit_message = None

    def _switch_then_commit(self, target_branch, commit_message):
        """Switch branch, sync remote, restore stash, commit — delegates to core/branch_handler.py."""
        from core.branch_handler import switch_and_commit

        self.operation_runner.run_with_progress(
            lambda: switch_and_commit(self.build_package, target_branch, commit_message),
            _("Switching and Committing"),
            _("Switching to {0} and committing...").format(target_branch),
        )

    def _do_commit(self, commit_message, target_branch):
        """Execute commit on current branch"""

        def commit_operation():
            return self._execute_commit(commit_message, target_branch)

        self.operation_runner.run_with_progress(
            commit_operation,
            _("Committing Changes"),
            _("Committing to {0}...").format(target_branch),
        )

    def _execute_commit(self, commit_message, target_branch=None):
        """Stage, commit, and push — delegates to core/commit_handler.py."""
        from core.commit_handler import execute_commit as _execute

        return _execute(self.build_package, commit_message, target_branch)

    def on_pull_requested(self, widget):
        """Handle pull request"""

        def pull_operation():
            # Import V2 operation
            from core.pull_operations import pull_latest_v2

            # Use V2 operation with intelligent conflict handling
            return pull_latest_v2(self.build_package)

        self.operation_runner.run_with_progress(
            pull_operation,
            _("Pulling Changes"),
            _("Pulling latest changes from remote repository..."),
        )

    def on_undo_commit_requested(self, widget):
        """Handle undo last commit request — delegates to core/branch_handler.py."""
        from core.branch_handler import undo_last_commit

        self.operation_runner.run_with_progress(
            lambda: undo_last_commit(self.build_package),
            _("Undoing Commit"),
            _("Undoing last commit (keeping changes)..."),
        )

    def on_package_build_requested(self, widget, package_type, tmate, has_commit_msg):
        """Handle package build request"""

        def build_operation():
            # Import V2 operation
            from core.package_operations import commit_and_generate_package_v2

            # Use V2 operation
            return commit_and_generate_package_v2(
                self.build_package,
                branch_type=package_type,
                commit_message=None,
                tmate_option=tmate,
            )

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            build_operation,
            _("Building Package"),
            _("Building {0} package...").format(package_type),
        )

    def on_commit_and_build_requested(
        self, widget, package_type, commit_message, tmate
    ):
        """Handle commit and build request"""

        def commit_and_build_operation():
            # Import V2 operation
            from core.package_operations import commit_and_generate_package_v2

            # Use V2 operation
            return commit_and_generate_package_v2(
                self.build_package,
                branch_type=package_type,
                commit_message=commit_message,
                tmate_option=tmate,
            )

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            commit_and_build_operation,
            _("Commit and Build"),
            _("Committing changes and building {0} package...").format(package_type),
        )

    def on_aur_build_requested(self, widget, package_name, tmate):
        """Handle AUR build request"""

        def aur_build_operation():
            self.build_package.args.aur = package_name
            self.build_package.args.tmate = tmate
            return self.build_package.build_aur_package()

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            aur_build_operation,
            _("Building AUR Package"),
            _("Building AUR package: {0}").format(package_name),
        )

    def _ensure_token_and_run(self, operation, title, description):
        """Ensure GitHub token is available before running a package operation.

        If token is missing, shows a GTK dialog to guide the user through setup.
        If token is available (or setup succeeds), runs the operation.
        """
        github_api = self.build_package.github_api

        # Check if token is already available
        if github_api.token:
            self.operation_runner.run_with_progress(operation, title, description)
            return

        # Try to read from file (in case it was created externally)
        token = github_api.get_github_token_optional()
        if token:
            github_api.token = token
            github_api.headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}",
            }
            self.operation_runner.run_with_progress(operation, title, description)
            return

        # Token not found - show setup dialog
        self._show_token_setup_dialog(operation, title, description)

    def _show_token_setup_dialog(
        self, pending_operation, pending_title, pending_description
    ):
        """Show GTK dialog to set up GitHub token"""

        from core.config import TOKEN_FILE
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True
        )
        dialog.set_heading(_("GitHub Token Setup"))
        dialog.set_body(
            _("A GitHub Personal Access Token is required for package operations.\n\n"
              "To create one:\n"
              "1. Go to: github.com/settings/tokens\n"
              "2. Click 'Generate new token (classic)'\n"
              "3. Select scopes: 'repo' and 'workflow'\n"
              "4. Copy the generated token")
        )
        
        # Create content box with entry fields
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        
        # Username field
        username_label = Gtk.Label(label=_("GitHub Username:"), xalign=0)
        username_entry = Gtk.Entry()
        username_entry.set_placeholder_text(_("your-username"))
        content_box.append(username_label)
        content_box.append(username_entry)
        
        # Token field
        token_label = Gtk.Label(label=_("GitHub Token:"), xalign=0)
        token_entry = Gtk.PasswordEntry()
        token_entry.set_show_peek_icon(True)
        token_entry.set_placeholder_text("ghp_...")
        content_box.append(token_label)
        content_box.append(token_entry)
        
        # Link to GitHub settings
        link_label = Gtk.Label()
        link_label.set_markup(
            '<a href="https://github.com/settings/tokens">'
            + _("Open GitHub Token Settings") + '</a>'
        )
        link_label.set_margin_top(8)
        content_box.append(link_label)
        
        dialog.set_extra_child(content_box)
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save and Continue"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        
        def on_response(dialog, response):
            if response == "save":
                username = username_entry.get_text().strip()
                token_text = token_entry.get_text().strip()
                
                if not username or not token_text:
                    self.show_error_toast(_("Username and token are required"))
                    dialog.close()
                    return
                
                # Save token to file
                token_file = os.path.expanduser(TOKEN_FILE)
                try:
                    organization = self.build_package.organization
                    mode = 'a' if os.path.exists(token_file) else 'w'
                    with open(token_file, mode) as f:
                        f.write(f"{organization}={token_text}\n")
                    os.chmod(token_file, 0o600)
                    
                    # Update the API instance
                    github_api = self.build_package.github_api
                    github_api.token = token_text
                    github_api.headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"token {token_text}"
                    }
                    
                    self.show_error_toast(_("✓ Token saved successfully"))
                    dialog.close()
                    
                    # Now run the pending operation
                    self.operation_runner.run_with_progress(
                        pending_operation, pending_title, pending_description
                    )
                    
                except Exception as e:
                    self.show_error_toast(_("Error saving token: {0}").format(e))
                    dialog.close()
            else:
                dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()
    
    def on_branch_selected(self, widget, branch_name):
        """Handle branch selection - switch to selected branch intelligently"""
        current_branch = GitUtils.get_current_branch()
        
        # Don't switch if already on this branch
        if branch_name == current_branch:
            return  # Silently ignore
        
        # Check for local changes
        has_changes = GitUtils.has_changes()
        
        if has_changes:
            # Show confirmation dialog with options
            self._show_branch_switch_dialog(branch_name, current_branch)
        else:
            # No changes, switch directly
            self._do_branch_switch(branch_name, stash_first=False)
    
    def _show_branch_switch_dialog(self, target_branch, current_branch):
        """Show dialog asking what to do with local changes"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True
        )
        dialog.set_heading(_("Uncommitted Changes Detected"))
        dialog.set_body(
            _("You have uncommitted changes. Choose how to proceed:")
        )
        
        # Add visual content with icon and branch info - wrapper for min width
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)  # Force minimum width
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(32)
        content_box.set_margin_end(32)
        content_box.set_halign(Gtk.Align.CENTER)
        
        # Warning icon
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(56)
        icon.add_css_class("warning")
        content_box.append(icon)
        
        # Branch info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_box.set_valign(Gtk.Align.CENTER)
        
        from_label = Gtk.Label()
        from_label.set_markup(_("<b>Current:</b>  <span foreground='#FFA500'>{0}</span>").format(current_branch))
        from_label.set_halign(Gtk.Align.START)
        info_box.append(from_label)
        
        to_label = Gtk.Label()
        to_label.set_markup(_("<b>Switch to:</b>  <span foreground='#00CED1'>{0}</span>").format(target_branch))
        to_label.set_halign(Gtk.Align.START)
        info_box.append(to_label)
        
        content_box.append(info_box)
        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)
        
        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard and Switch"))
        dialog.add_response("stash", _("Stash and Switch"))
        
        dialog.set_response_appearance("stash", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("stash")
        dialog.set_close_response("cancel")
        
        dialog.connect("response", self._on_branch_switch_response, target_branch)
        dialog.present()
    
    def _on_branch_switch_response(self, dialog, response, target_branch):
        """Handle branch switch dialog response"""
        if response == "stash":
            self._do_branch_switch(target_branch, stash_first=True)
        elif response == "discard":
            self._do_branch_switch(target_branch, discard_first=True)
        # Cancel does nothing
    
    def _do_branch_switch(self, target_branch, stash_first=False, discard_first=False):
        """Perform branch switch — delegates git logic to core/branch_handler.py."""
        from core.branch_handler import switch_branch

        result = switch_branch(self.build_package, target_branch, stash_first=stash_first, discard_first=discard_first)
        msg = result["message"]
        if result["message_type"] == "error":
            self.show_error_toast(msg)
        elif result["message_type"] == "info":
            self.show_info_toast(msg)
        else:
            self.show_toast(msg)

        if result["success"]:
            if hasattr(self, "branch_widget"):
                self.branch_widget.refresh_branches()
            self.refresh_all_widgets()

    def on_merge_requested(self, widget, source_branch, target_branch, auto_merge):
        """Handle merge request - create PR or create branch if target doesn't exist"""
        if not GitUtils.branch_exists(target_branch):
            self._show_create_branch_dialog(source_branch, target_branch)
            return

        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            self._show_no_remote_error()
            return

        self._show_merge_confirmation(source_branch, target_branch, auto_merge)

    def _show_create_branch_dialog(self, source_branch, target_branch):
        """Show dialog to create a branch that doesn't exist and push to remote"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)

        dialog.set_heading(_("Create Branch '{0}'?").format(target_branch))
        dialog.set_body(
            _(
                "The branch '{0}' doesn't exist yet.\n\nWould you like to create it from '{1}' and push to remote?"
            ).format(target_branch, source_branch)
        )

        # Visual content - wrapper for consistent width
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Flow visualization
        flow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        flow_box.set_halign(Gtk.Align.CENTER)

        source_label = Gtk.Label()
        source_label.set_markup(_("<span foreground='#FFA500'><b>{0}</b></span>").format(source_branch))
        flow_box.append(source_label)

        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(24)
        flow_box.append(arrow)

        target_label = Gtk.Label()
        target_label.set_markup(
            _("<span foreground='#32CD32'><b>{0}</b></span> <span foreground='#888888'>(new)</span>").format(
                target_branch
            )
        )
        flow_box.append(target_label)

        content_box.append(flow_box)

        info_label = Gtk.Label()
        info_label.set_markup(
            _("<span foreground='#00CED1'>This will copy all code from '{0}' to the new '{1}' branch</span>").format(
                source_branch, target_branch
            )
        )
        info_label.set_wrap(True)
        info_label.set_margin_top(8)
        content_box.append(info_label)

        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)

        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create and Push"))

        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_create_branch_response, source_branch, target_branch)
        dialog.present()

    def _on_create_branch_response(self, dialog, response, source_branch, target_branch):
        """Handle create branch dialog response — delegates to core/branch_handler.py."""
        if response != "create":
            return

        from core.branch_handler import create_branch_and_push

        self.operation_runner.run_with_progress(
            lambda: create_branch_and_push(self.build_package, source_branch, target_branch),
            _("Creating Branch"),
            _("Creating '{0}' from '{1}' and pushing...").format(target_branch, source_branch),
        )

    def _on_configure_remote_response(self, dialog, response):
        """Handle configure remote dialog response — delegates to core/branch_handler.py."""
        if response != "configure":
            return

        url = self._remote_url_entry.get_text().strip()
        if not url:
            self.show_error_toast(_("Please enter a valid URL"))
            return

        from core.branch_handler import configure_remote_and_push

        self.operation_runner.run_with_progress(
            lambda: configure_remote_and_push(self.build_package, url),
            _("Configuring Remote"),
            _("Setting up remote origin and pushing..."),
        )

    def _show_merge_confirmation(self, source_branch, target_branch, auto_merge):
        """Show merge confirmation dialog"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True
        )
        
        dialog.set_heading(_("Confirm Pull Request"))
        dialog.set_body(_("Create a Pull Request to merge changes?"))
        
        # Visual content
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        
        # Branch flow visualization
        flow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        flow_box.set_halign(Gtk.Align.CENTER)
        
        source_label = Gtk.Label()
        source_label.set_markup(_("<span foreground='#FFA500'><b>{0}</b></span>").format(source_branch))
        flow_box.append(source_label)
        
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(24)
        flow_box.append(arrow)
        
        target_label = Gtk.Label()
        target_label.set_markup(_("<span foreground='#32CD32'><b>{0}</b></span>").format(target_branch))
        flow_box.append(target_label)
        
        content_box.append(flow_box)
        
        # Auto-merge status
        merge_status = Gtk.Label()
        if auto_merge:
            merge_status.set_markup(_("<span foreground='#00CED1'>✓ Auto-merge enabled</span>"))
        else:
            merge_status.set_markup(_("<span foreground='#888888'>Manual approval required</span>"))
        merge_status.set_margin_top(8)
        content_box.append(merge_status)
        
        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)
        
        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create PR"))
        
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")
        
        dialog.connect("response", self._on_merge_confirm_response, source_branch, target_branch, auto_merge)
        dialog.present()
    
    def _on_merge_confirm_response(self, dialog, response, source_branch, target_branch, auto_merge):
        """Handle merge confirmation response"""
        if response != "create":
            return
        
        def merge_operation():
            return self.build_package.github_api.create_pull_request(
                source_branch, target_branch, auto_merge, self.build_package.logger
            )
        
        merge_type = _("Auto-merge") if auto_merge else _("Manual")
        self.operation_runner.run_with_progress(
            merge_operation,
            _("Creating Pull Request"),
            _("{0}: {1} → {2}").format(merge_type, source_branch, target_branch)
        )
    
    def on_branch_cleanup_requested(self, widget):
        """Handle branch cleanup request"""
        self.on_cleanup_branches_requested(widget)
    
    def on_cleanup_branches_requested(self, widget):
        """Handle cleanup branches request"""
        def cleanup_operation():
            return GitUtils.cleanup_old_branches(self.build_package.logger)
        
        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Cleaning Up Branches"),
            _("Removing old development branches...")
        )
    
    def on_cleanup_actions_requested(self, widget, status_type):
        """Handle cleanup actions request"""
        def cleanup_operation():
            return self.build_package.github_api.clean_action_jobs(
                status_type, self.build_package.logger
            )
        
        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Cleaning Up Actions"),
            _("Removing {0} GitHub Actions...").format(status_type)
        )
    
    def on_cleanup_tags_requested(self, widget):
        """Handle cleanup tags request"""
        def cleanup_operation():
            return self.build_package.github_api.clean_all_tags(
                self.build_package.logger
            )
        
        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Cleaning Up Tags"),
            _("Removing all repository tags...")
        )
    
    def on_revert_commit_requested(self, widget, commit_hash, method):
        """Handle commit revert request — delegates to revert_operations."""
        from core.revert_operations import execute_revert_by_hash

        def revert_operation():
            return execute_revert_by_hash(self.build_package, commit_hash, method)

        self.operation_runner.run_with_progress(
            revert_operation,
            _("Reverting Commit"),
            _("Reverting commit {0} using {1} method...").format(commit_hash[:7], method)
        )
    
    def on_refresh_activated(self, action, param):
        """Handle refresh action"""
        self.refresh_status()
        self.show_toast(_("Status refreshed"))
    
    def on_pull_activated(self, action, param):
        """Handle pull latest action"""
        if not self.build_package or not self.build_package.is_git_repo:
            self.show_error_toast(_("Not in a Git repository"))
            return
        
        # Run pull operation asynchronously
        self.run_async_operation(
            GitUtils.git_pull,
            self.logger,
            success_message=_("Successfully pulled latest changes"),
            error_message=_("Failed to pull changes")
        )
    
    def run_async_operation(self, func, *args, success_message=None, error_message=None):
        """Run operation in a background thread to avoid blocking the UI."""

        def _thread_func():
            try:
                result = func(*args)

                def _on_done():
                    if result:
                        self.show_toast(success_message or _("Operation completed"))
                    else:
                        self.show_error_toast(error_message or _("Operation failed"))
                    self.refresh_status()
                    return False

                GLib.idle_add(_on_done)
            except Exception as exc:
                err_msg = _("Operation failed: {0}").format(str(exc))
                GLib.idle_add(lambda msg=err_msg: self.show_error_toast(msg) or False)

        thread = threading.Thread(target=_thread_func, daemon=True)
        thread.start()
    
    def show_toast(self, message):
        """Show success toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)
    
    def show_error_toast(self, message):
        """Show error toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        toast.add_css_class("error")
        self.toast_overlay.add_toast(toast)
    
    def show_info_toast(self, message):
        """Show info toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        # toast.add_css_class("info")
        self.toast_overlay.add_toast(toast)
    
    def on_nav_row_selected(self, list_box, row):
        """Handle navigation row selection"""
        if row:
            page_id = row.page_id
            self.switch_to_page(page_id)
    
    def switch_to_page(self, page_id):
        """Switch to specific page"""
        self.content_stack.set_visible_child_name(page_id)

        # In collapsed mode, ensure sidebar overlay closes
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    def refresh_features(self):
        """Dynamically update navigation and pages when feature settings change"""
        package_enabled = self.settings.get("package_features_enabled", False)
        aur_enabled = self.settings.get("aur_features_enabled", False)

        # Handle package widget
        if package_enabled and self.package_widget is None:
            self.package_widget = PackageWidget(self.build_package)
            self.package_widget.connect(
                "package-build-requested", self.on_package_build_requested
            )
            self.package_widget.connect(
                "commit-and-build-requested", self.on_commit_and_build_requested
            )
            self.content_stack.add_titled_with_icon(
                self.package_widget,
                "package",
                _("Generate Package"),
                "package-x-generic-symbolic",
            )
        elif not package_enabled and self.package_widget is not None:
            self.content_stack.remove(self.package_widget)
            self.package_widget = None

        # Handle AUR widget
        if aur_enabled and self.aur_widget is None:
            self.aur_widget = AURWidget(self.build_package)
            self.aur_widget.connect("aur-build-requested", self.on_aur_build_requested)
            self.content_stack.add_titled_with_icon(
                self.aur_widget,
                "aur",
                _("AUR Package"),
                "system-software-install-symbolic",
            )
        elif not aur_enabled and self.aur_widget is not None:
            self.content_stack.remove(self.aur_widget)
            self.aur_widget = None

        self._rebuild_nav_list()

        if hasattr(self, "overview_widget"):
            self.overview_widget.refresh_quick_actions()

    def _rebuild_nav_list(self):
        """Rebuild navigation sidebar respecting current feature state"""
        current_page = self.content_stack.get_visible_child_name()

        # Remove all existing nav rows
        for nav_row in list(self.nav_rows.values()):
            self.nav_list.remove(nav_row)
        self.nav_rows.clear()

        pages = [
            (self.overview_widget, "overview", _("Overview"), "view-list-symbolic"),
            (
                self.commit_widget,
                "commit",
                _("Commit and Push"),
                "document-save-symbolic",
            ),
        ]
        if self.package_widget:
            pages.append((
                self.package_widget,
                "package",
                _("Generate Package"),
                "package-x-generic-symbolic",
            ))
        if self.aur_widget:
            pages.append((
                self.aur_widget,
                "aur",
                _("AUR Package"),
                "system-software-install-symbolic",
            ))
        pages.extend([
            (
                self.branch_widget,
                "branches",
                _("Branches"),
                "media-playlist-consecutive-symbolic",
            ),
            (
                self.advanced_widget,
                "advanced",
                _("Advanced"),
                "preferences-system-symbolic",
            ),
        ])

        for _widget, page_id, title, icon_name in pages:
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

        # Re-select current page if still available, otherwise fall back to overview
        if current_page and current_page in self.nav_rows:
            self.nav_list.select_row(self.nav_rows[current_page])
        else:
            self.nav_list.select_row(self.nav_rows.get("overview"))
            self.content_stack.set_visible_child_name("overview")

        GLib.idle_add(self.update_nav_badges)

    def refresh_all_widgets(self):
        """Refresh all widgets with current status"""
        if hasattr(self, 'overview_widget'):
            self.overview_widget.refresh_overview()
        if hasattr(self, 'commit_widget'):
            self.commit_widget.refresh_status()
        if hasattr(self, 'package_widget'):
            self.package_widget.refresh_status()
        if hasattr(self, 'branch_widget'):
            self.branch_widget.refresh_branches()
        if hasattr(self, 'advanced_widget'):
            self.advanced_widget.refresh_commits()
        
        # Update navigation badges
        self.update_nav_badges()
    
    def update_nav_badges(self):
        """Update badges in navigation sidebar"""
        if not hasattr(self, 'nav_rows') or not self.build_package:
            return False

        try:
            if "commit" in self.nav_rows:
                if self.build_package.is_git_repo and GitUtils.has_changes():
                    changes = GitUtils.count_changed_files()
                    row = self.nav_rows["commit"]
                    if changes > 0:
                        row.badge.set_text(str(changes))
                        row.badge.set_visible(True)
                        row.badge.add_css_class("warning")
                        row.update_property(
                            [Gtk.AccessibleProperty.LABEL],
                            [_("Commit ({0} pending changes)").format(changes)],
                        )
                    else:
                        row.badge.set_visible(False)
                        row.update_property(
                            [Gtk.AccessibleProperty.LABEL],
                            [_("Commit")],
                        )
                else:
                    self.nav_rows["commit"].badge.set_visible(False)

        except Exception as e:
            print(_("Error updating nav badges: {0}").format(e))
        
        return False  # Don't repeat idle callback
    
    def send_system_notification(self, title, body, icon="package-x-generic"):
        """Send a system notification (desktop notification)"""
        try:
            # Use GNotification for libadwaita apps
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            notification.set_icon(Gio.ThemedIcon.new(icon))
            notification.set_priority(Gio.NotificationPriority.NORMAL)
            
            # Send via application
            if self.application:
                self.application.send_notification(None, notification)
        except Exception as e:
            print(f"Could not send notification: {e}")
    
    def on_back_button_clicked(self, button):
        """Handle back button in mobile view"""
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(True)