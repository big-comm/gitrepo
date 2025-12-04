#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_window.py - Main window for GTK4 interface
#

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio
from core.build_package import BuildPackage
from core.git_utils import GitUtils
from core.translation_utils import _
from core.settings import Settings
from .gtk_logger import GTKLogger
from .gtk_menu import GTKMenu
from .gtk_adapters import GTKMenuSystem, GTKConflictResolver
from .dialogs.settings_dialog import SettingsDialog
from .widgets.overview_widget import OverviewWidget
from .widgets.commit_widget import CommitWidget
from .widgets.package_widget import PackageWidget
from .widgets.aur_widget import AURWidget
from .widgets.branch_widget import BranchWidget
from .widgets.advanced_widget import AdvancedWidget
from .dialogs.progress_dialog import OperationRunner

class MainWindow(Adw.ApplicationWindow):
    """Main application window using GTK4 + Libadwaita"""
    
    __gtype_name__ = 'MainWindow'
    
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
    
    def create_ui(self):
        """Create the main UI programmatically"""
        
        # Main layout - Toast overlay first
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        
        # Leaflet for responsive design
        self.leaflet = Adw.Leaflet()
        self.leaflet.set_can_unfold(True)
        self.leaflet.set_fold_threshold_policy(Adw.FoldThresholdPolicy.MINIMUM)
        self.toast_overlay.set_child(self.leaflet)
        
        # Sidebar
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(280, -1)
        
        # Header bar for sidebar
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Gtk.Label(label=_("Build Package")))
        sidebar_header.set_show_start_title_buttons(False)  # Hide window controls
        sidebar_header.set_show_end_title_buttons(False)    # Hide window controls
        sidebar_box.append(sidebar_header)
        
        # Navigation list
        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        self.nav_list.connect('row-selected', self.on_nav_row_selected)
        
        sidebar_box.append(self.nav_list)
        self.leaflet.append(sidebar_box)
        
        # Content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Header bar for content
        self.header_bar = Adw.HeaderBar()
        
        # Create a Title widget to hold title and subtitle
        self.window_title = Adw.WindowTitle(title=_("Build Package"))
        self.header_bar.set_title_widget(self.window_title)
        
        # Show title buttons only on main header (right side)
        self.header_bar.set_show_start_title_buttons(False)  # Hide start buttons
        self.header_bar.set_show_end_title_buttons(True)     # Show end buttons (close, etc)
        
        # Back button for mobile
        back_button = Gtk.Button()
        back_button.set_icon_name("go-previous-symbolic")
        back_button.connect('clicked', self.on_back_button_clicked)
        self.header_bar.pack_start(back_button)
        
        content_box.append(self.header_bar)
        
        # Content stack with scroll wrapper
        scrolled_content = Gtk.ScrolledWindow()
        scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_content.set_vexpand(True)
        scrolled_content.set_hexpand(True)
        # scrolled_content.set_propagate_natural_height(True)

        self.content_stack = Adw.ViewStack()
        scrolled_content.set_child(self.content_stack)
        content_box.append(scrolled_content)
        
        self.leaflet.append(content_box)
    
    def init_build_package(self):
        """Initialize BuildPackage with GUI logger and menu"""
        try:
            self.build_package = BuildPackage(
                logger=self.logger,
                menu_system=self.menu_system  # Use new GTK menu system
            )

            # Initialize conflict resolver with GTK support
            self.build_package.conflict_resolver = GTKConflictResolver(
                logger=self.logger,
                menu_system=self.menu_system,
                parent_window=self,
                strategy=self.settings.get("conflict_strategy", "interactive")
            )

            # Set settings in build_package
            self.build_package.settings = self.settings

            # Create navigation and pages after build_package is ready
            self.create_navigation_and_pages()

        except Exception as e:
            self.show_error_toast(_("Failed to initialize: {0}").format(str(e)))
    
    def create_navigation_and_pages(self):
        """Create navigation items and corresponding pages"""
        
        # Create widgets for each page
        self.overview_widget = OverviewWidget(self.build_package)
        self.commit_widget = CommitWidget(self.build_package) 
        self.package_widget = PackageWidget(self.build_package)
        self.aur_widget = AURWidget(self.build_package)
        self.branch_widget = BranchWidget(self.build_package)
        self.advanced_widget = AdvancedWidget(self.build_package)
        
        # Connect widget signals
        self.connect_widget_signals()
        
        # Add pages to stack
        pages = [
            (self.overview_widget, "overview", _("Overview"), "view-list-symbolic"),
            (self.commit_widget, "commit", _("Commit & Push"), "document-save-symbolic"),
            (self.package_widget, "package", _("Generate Package"), "package-x-generic-symbolic"),
            (self.aur_widget, "aur", _("AUR Package"), "system-software-install-symbolic"),
            (self.branch_widget, "branches", _("Branches"), "git-branch-symbolic"),
            (self.advanced_widget, "advanced", _("Advanced"), "preferences-system-symbolic")
        ]
        
        for widget, page_id, title, icon_name in pages:
            self.content_stack.add_titled_with_icon(widget, page_id, title, icon_name)
            
            # Create navigation row
            nav_row = Adw.ActionRow()
            nav_row.set_title(title)
            nav_row.set_activatable(True)
            nav_row.page_id = page_id
            
            # Add icon
            icon = Gtk.Image.new_from_icon_name(icon_name)
            nav_row.add_prefix(icon)
            
            self.nav_list.append(nav_row)
        
        # Select first page
        self.nav_list.select_row(self.nav_list.get_row_at_index(0))
        self.content_stack.set_visible_child_name("overview")
    
    def connect_widget_signals(self):
        """Connect signals from all widgets"""
        
        # Overview widget signals
        self.overview_widget.connect('quick-action', self.on_quick_action)
        self.overview_widget.connect('refresh-requested', self.on_overview_refresh)
        
        # Commit widget signals
        self.commit_widget.connect('commit-requested', self.on_commit_requested)
        self.commit_widget.connect('push-requested', self.on_pull_requested)
        
        # Package widget signals
        self.package_widget.connect('package-build-requested', self.on_package_build_requested)
        self.package_widget.connect('commit-and-build-requested', self.on_commit_and_build_requested)
        
        # AUR widget signals
        self.aur_widget.connect('aur-build-requested', self.on_aur_build_requested)
        
        # Branch widget signals
        self.branch_widget.connect('branch-selected', self.on_branch_selected)
        self.branch_widget.connect('merge-requested', self.on_merge_requested)
        self.branch_widget.connect('cleanup-requested', self.on_branch_cleanup_requested)
        
        # Advanced widget signals
        self.advanced_widget.connect('cleanup-branches-requested', self.on_cleanup_branches_requested)
        self.advanced_widget.connect('cleanup-actions-requested', self.on_cleanup_actions_requested)
        self.advanced_widget.connect('cleanup-tags-requested', self.on_cleanup_tags_requested)
        self.advanced_widget.connect('revert-commit-requested', self.on_revert_commit_requested)
    
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
    
    def refresh_status(self):
        """Refresh repository status display"""
        if not self.build_package:
            return
            
        # Repository status
        if self.build_package.is_git_repo:
            repo_name = GitUtils.get_repo_name()
            self.repo_status_label.set_text(repo_name if repo_name else _("Git Repository"))
            self.repo_status_label.add_css_class("success")
        else:
            self.repo_status_label.set_text(_("Not a Git repository"))
            self.repo_status_label.add_css_class("warning")
        
        # Current branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            self.branch_status_label.set_text(current_branch)
        else:
            self.branch_status_label.set_text(_("Unknown"))
        
        # Changes status
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
        """Handle commit request from commit widget"""
        def commit_operation():
            # Import V2 operation
            from core.commit_operations import commit_and_push_v2

            # Set commit message in args
            self.build_package.args.commit = commit_message

            # Use V2 operation with intelligent conflict handling
            return commit_and_push_v2(self.build_package)

        self.operation_runner.run_with_progress(
            commit_operation,
            _("Committing Changes"),
            _("Committing and pushing changes to repository...")
        )
    
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
            _("Pulling latest changes from remote repository...")
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
                tmate_option=tmate
            )

        self.operation_runner.run_with_progress(
            build_operation,
            _("Building Package"),
            _("Building {0} package...").format(package_type)
        )
    
    def on_commit_and_build_requested(self, widget, package_type, commit_message, tmate):
        """Handle commit and build request"""
        def commit_and_build_operation():
            # Import V2 operation
            from core.package_operations import commit_and_generate_package_v2

            # Use V2 operation
            return commit_and_generate_package_v2(
                self.build_package,
                branch_type=package_type,
                commit_message=commit_message,
                tmate_option=tmate
            )

        self.operation_runner.run_with_progress(
            commit_and_build_operation,
            _("Commit and Build"),
            _("Committing changes and building {0} package...").format(package_type)
        )
    
    def on_aur_build_requested(self, widget, package_name, tmate):
        """Handle AUR build request"""
        def aur_build_operation():
            self.build_package.args.aur = package_name
            self.build_package.args.tmate = tmate
            return self.build_package.build_aur_package()
        
        self.operation_runner.run_with_progress(
            aur_build_operation,
            _("Building AUR Package"),
            _("Building AUR package: {0}").format(package_name)
        )
    
    def on_branch_selected(self, widget, branch_name):
        """Handle branch selection"""
        self.show_info_toast(_("Selected branch: {0}").format(branch_name))
    
    def on_merge_requested(self, widget, source_branch, target_branch):
        """Handle merge request"""
        def merge_operation():
            return self.build_package.github_api.create_pull_request(
                source_branch, target_branch, True, self.build_package.logger
            )
        
        self.operation_runner.run_with_progress(
            merge_operation,
            _("Creating Merge Request"),
            _("Creating merge request: {0} → {1}").format(source_branch, target_branch)
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
        """Handle commit revert request"""
        def revert_operation():
            # This would need to be implemented in BuildPackage
            # For now, just show a placeholder
            return True
        
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
        """Run an operation asynchronously with progress feedback"""
        # This would implement async operation with threading
        # For now, run synchronously
        try:
            result = func(*args)
            if result:
                if success_message:
                    self.show_toast(success_message)
                self.refresh_status()
            else:
                if error_message:
                    self.show_error_toast(error_message)
        except Exception as e:
            self.show_error_toast(_("Operation failed: {0}").format(str(e)))
    
    def show_toast(self, message):
        """Show success toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)
    
    def show_error_toast(self, message):
        """Show error toast message"""
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        # toast.add_css_class("error")
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
        
        # Update leaflet for mobile view
        if self.leaflet.get_folded():
            # Use get_child_by_name or navigate properly
            pass  # Remove this line for now, mobile view will work without it
    
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
    
    def on_back_button_clicked(self, button):
        """Handle back button in mobile view"""
        if self.leaflet.get_folded():
            self.leaflet.set_visible_child(self.leaflet.get_child_at_index(0))  # sidebar