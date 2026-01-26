#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/main_window.py - Main window for GTK4 interface
#

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, GLib
from core.build_package import BuildPackage
from core.git_utils import GitUtils
from core.translation_utils import _
from core.settings import Settings
from core.config import APP_VERSION
from .gtk_logger import GTKLogger
from .gtk_menu import GTKMenu
from .gtk_adapters import GTKMenuSystem, GTKConflictResolver
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.welcome_dialog import WelcomeDialog, should_show_welcome
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
        
        # Show welcome dialog on first run (after window is shown)
        GLib.idle_add(self._check_show_welcome)
    
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
        self.window_title = Adw.WindowTitle(title=_("GitRepo"))
        self.header_bar.set_title_widget(self.window_title)
        
        # Show title buttons only on main header (right side)
        self.header_bar.set_show_start_title_buttons(False)  # Hide start buttons
        self.header_bar.set_show_end_title_buttons(True)     # Show end buttons (close, etc)
        
        # Add hamburger menu button
        self._create_hamburger_menu()
        
        content_box.append(self.header_bar)
        
        # Content stack with scroll wrapper
        scrolled_content = Gtk.ScrolledWindow()
        scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_content.set_vexpand(True)
        scrolled_content.set_hexpand(True)
        scrolled_content.set_propagate_natural_height(True)

        self.content_stack = Adw.ViewStack()
        self.content_stack.set_vhomogeneous(False)  # Don't force all pages to same height
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
        
        # Store nav rows for badge updates
        self.nav_rows = {}
        
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
        self.overview_widget.connect('quick-action', self.on_quick_action)
        self.overview_widget.connect('refresh-requested', self.on_overview_refresh)
        
        # Commit widget signals
        self.commit_widget.connect('commit-requested', self.on_commit_requested)
        self.commit_widget.connect('push-requested', self.on_pull_requested)
        self.commit_widget.connect('undo-commit-requested', self.on_undo_commit_requested)
        
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
    
    def _create_hamburger_menu(self):
        """Create hamburger menu button with About option"""
        # Create menu model
        menu = Gio.Menu()
        
        # Add menu items
        menu.append(_("About"), "win.about")
        
        # Create menu button with hamburger icon
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text(_("Main Menu"))
        
        # Add to header bar (pack_end places it on the right, before window controls)
        self.header_bar.pack_end(menu_button)
    
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
            developers=[
                "BigCommunity Team"
            ],
            comments=_("Git repository manager for building and deploying packages")
        )
        about.present()
    
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
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True
        )
        
        if is_protected:
            dialog.set_heading(_("⚠️ Commit to Protected Branch?"))
            dialog.set_body(
                _("You are about to commit directly to '{0}'.\n\n"
                  "This is usually protected. Consider using your development branch instead.").format(current_branch)
            )
        else:
            dialog.set_heading(_("Confirm Commit Branch"))
            dialog.set_body(
                _("Choose where to commit your changes:")
            )
        
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
            branch_label.set_markup(_("<b>Current:</b> <span foreground='#FF6B6B'>{0}</span>").format(current_branch))
        else:
            branch_label.set_markup(_("<b>Current:</b> <span foreground='#00CED1'>{0}</span>").format(current_branch))
        current_box.append(branch_label)
        
        content_box.append(current_box)
        
        # Dev branch suggestion
        if current_branch != dev_branch:
            suggestion_label = Gtk.Label()
            suggestion_label.set_markup(_("<span foreground='#888888'>Your dev branch:</span> <span foreground='#32CD32'>{0}</span>").format(dev_branch))
            suggestion_label.set_margin_top(8)
            content_box.append(suggestion_label)
        
        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)
        
        # Responses
        dialog.add_response("cancel", _("Cancel"))
        
        if current_branch != dev_branch:
            dialog.add_response("dev", _("Use {0}").format(dev_branch))
            dialog.set_response_appearance("dev", Adw.ResponseAppearance.SUGGESTED)
        
        if is_protected:
            dialog.add_response("current", _("Commit to {0} anyway").format(current_branch))
            dialog.set_response_appearance("current", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dialog.add_response("current", _("Commit to {0}").format(current_branch))
            if current_branch == dev_branch:
                dialog.set_response_appearance("current", Adw.ResponseAppearance.SUGGESTED)
        
        dialog.set_default_response("dev" if current_branch != dev_branch else "current")
        dialog.set_close_response("cancel")
        
        dialog.connect("response", self._on_commit_branch_response, current_branch, dev_branch)
        dialog.present()
    
    def _on_commit_branch_response(self, dialog, response, current_branch, dev_branch):
        """Handle commit branch dialog response"""
        if response == "cancel":
            self._pending_commit_message = None
            return
        
        target_branch = dev_branch if response == "dev" else current_branch
        
        # If we need to switch branches first
        if target_branch != current_branch:
            self._switch_then_commit(target_branch, self._pending_commit_message)
        else:
            self._do_commit(self._pending_commit_message, target_branch)
        
        self._pending_commit_message = None
    
    def _switch_then_commit(self, target_branch, commit_message):
        """Switch to target branch then commit with logging"""
        import subprocess
        
        # Check for changes to stash
        has_changes = GitUtils.has_changes()
        logger = self.build_package.logger if hasattr(self.build_package, 'logger') else None
        
        def log(style, msg):
            if logger:
                logger.log(style, msg)
            else:
                print(f"[{style}] {msg}")
        
        def switch_and_commit():
            stashed = False
            current_branch = GitUtils.get_current_branch()
            
            try:
                log("cyan", _("Preparing branch switch..."))
                log("dim", f"    From: {current_branch} → To: {target_branch}")
                
                # Stash if needed
                if has_changes:
                    log("cyan", _("Stashing local changes..."))
                    stash_result = subprocess.run(
                        ["git", "stash", "push", "-u", "-m", f"auto-stash-commit-to-{target_branch}"],
                        capture_output=True, text=True, check=False
                    )
                    if stash_result.returncode == 0:
                        stashed = True
                        log("green", _("✓ Changes stashed"))
                    else:
                        log("yellow", _("⚠ Could not stash (continuing anyway)"))
                
                # Switch branch
                log("cyan", _("Switching to branch {0}...").format(target_branch))
                checkout_result = subprocess.run(
                    ["git", "checkout", target_branch], 
                    capture_output=True, text=True, check=False
                )
                
                if checkout_result.returncode != 0:
                    error_msg = checkout_result.stderr.strip() or checkout_result.stdout.strip()
                    log("red", _("✗ Failed to switch branch: {0}").format(error_msg))
                    if stashed:
                        subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
                        log("yellow", _("Restored stashed changes"))
                    raise Exception(_("Failed to switch to branch {0}").format(target_branch))
                
                log("green", _("✓ Switched to {0}").format(target_branch))
                
                # Restore stash
                if stashed:
                    log("cyan", _("Restoring stashed changes..."))
                    pop_result = subprocess.run(
                        ["git", "stash", "pop"], 
                        capture_output=True, text=True, check=False
                    )
                    if pop_result.returncode == 0:
                        log("green", _("✓ Stash restored"))
                    else:
                        log("yellow", _("⚠ Conflicts while restoring stash - please resolve manually"))
                
                # Now do the commit
                return self._execute_commit(commit_message)
                
            except subprocess.CalledProcessError as e:
                log("red", _("Error: {0}").format(str(e)))
                if stashed:
                    subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
                    log("yellow", _("Restored stashed changes"))
                raise e
        
        self.operation_runner.run_with_progress(
            switch_and_commit,
            _("Switching & Committing"),
            _("Switching to {0} and committing...").format(target_branch)
        )
    
    def _do_commit(self, commit_message, target_branch):
        """Execute commit on current branch"""
        def commit_operation():
            return self._execute_commit(commit_message)
        
        self.operation_runner.run_with_progress(
            commit_operation,
            _("Committing Changes"),
            _("Committing to {0}...").format(target_branch)
        )
    
    def _execute_commit(self, commit_message):
        """Execute the actual git commit and push with intelligent error handling"""
        import subprocess
        
        logger = self.build_package.logger if hasattr(self.build_package, 'logger') else None
        
        def log(style, msg):
            if logger:
                logger.log(style, msg)
            else:
                print(f"[{style}] {msg}")
        
        current_branch = GitUtils.get_current_branch()
        
        # Step 1: Stage all changes
        log("cyan", _("Staging all changes..."))
        try:
            result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
                log("red", _("Failed to stage changes: {0}").format(error_msg))
                raise Exception(_("Failed to stage changes: {0}").format(error_msg))
            log("green", _("✓ Changes staged"))
        except Exception as e:
            log("red", str(e))
            raise
        
        # Step 2: Commit
        log("cyan", _("Creating commit..."))
        log("dim", f"    git commit -m \"{commit_message[:50]}...\"" if len(commit_message) > 50 else f"    git commit -m \"{commit_message}\"")
        try:
            result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
                # Check for common issues
                if "nothing to commit" in error_msg.lower():
                    log("yellow", _("⚠ No changes to commit"))
                    return True  # Not really an error
                log("red", _("Failed to commit: {0}").format(error_msg))
                raise Exception(_("Failed to commit: {0}").format(error_msg))
            log("green", _("✓ Commit created successfully"))
        except Exception as e:
            if "No changes to commit" not in str(e):
                log("red", str(e))
                raise
        
        # Step 3: Check for divergence and sync before push
        log("cyan", _("Checking remote status..."))
        divergence = GitUtils.check_branch_divergence(current_branch)
        
        if divergence.get('error'):
            log("yellow", _("⚠ Could not check remote status: {0}").format(divergence['error']))
            log("dim", _("    Proceeding with push anyway..."))
        elif divergence.get('diverged') or divergence.get('behind', 0) > 0:
            # Need to sync with remote first
            behind_count = divergence.get('behind', 0)
            ahead_count = divergence.get('ahead', 0)
            
            if divergence.get('diverged'):
                log("yellow", _("⚠ Branch has diverged from remote"))
                log("dim", _("    Local: {0} commit(s) ahead").format(ahead_count))
                log("dim", _("    Remote: {0} commit(s) to sync").format(behind_count))
            else:
                log("cyan", _("Remote has {0} new commit(s) - syncing...").format(behind_count))
            
            log("cyan", _("Pulling with rebase to sync..."))
            log("dim", _("    git pull --rebase origin {0}").format(current_branch))
            
            # Try to auto-resolve with rebase
            if GitUtils.resolve_divergence(current_branch, 'rebase', logger):
                log("green", _("✓ Synced with remote successfully"))
            else:
                # Rebase failed, try merge
                log("yellow", _("⚠ Rebase had conflicts, trying merge..."))
                if GitUtils.resolve_divergence(current_branch, 'merge', logger):
                    log("green", _("✓ Merged with remote successfully"))
                else:
                    log("red", _("✗ Could not sync with remote automatically"))
                    log("white", _("Please resolve conflicts manually and try again"))
                    raise Exception(_("Failed to sync with remote - conflicts need manual resolution"))
        else:
            log("green", _("✓ Already in sync with remote"))
        
        # Step 4: Push
        log("cyan", _("Pushing to remote..."))
        log("dim", f"    git push -u origin {current_branch}")
        try:
            result = subprocess.run(
                ["git", "push", "-u", "origin", current_branch],
                capture_output=True, text=True, check=False
            )
            
            if result.returncode != 0:
                error_output = result.stderr.strip() or result.stdout.strip() or ""
                
                # Detect specific error types and provide helpful messages
                error_info = self._analyze_push_error(error_output, current_branch)
                
                log("red", _("✗ Push failed!"))
                log("red", _("Error: {0}").format(error_output))
                log("yellow", "")
                log("yellow", _("═══ Diagnosis ═══"))
                log("orange", error_info["diagnosis"])
                log("yellow", "")
                log("yellow", _("═══ Suggested Solutions ═══"))
                for solution in error_info["solutions"]:
                    log("white", f"  • {solution}")
                
                raise Exception(error_info["diagnosis"])
            
            log("green", _("✓ Pushed to origin/{0}").format(current_branch))
        except Exception as e:
            # Re-raise to show in UI
            raise
        
        log("green", "")
        log("green", _("═══ Commit Complete ═══"))
        log("white", _("Branch: {0}").format(current_branch))
        log("white", _("Message: {0}").format(commit_message[:60] + "..." if len(commit_message) > 60 else commit_message))
        
        return True
    
    def _analyze_push_error(self, error_output, branch):
        """Analyze push error and provide helpful diagnosis and solutions"""
        error_lower = error_output.lower()
        
        # Authentication errors
        if any(x in error_lower for x in ["authentication", "permission denied", "403", "401", "could not read username"]):
            return {
                "diagnosis": _("Authentication failed - credentials may be expired or invalid"),
                "solutions": [
                    _("Run 'gh auth login' to authenticate with GitHub CLI"),
                    _("Check if your SSH key is added: ssh -T git@github.com"),
                    _("For HTTPS, run: git credential reject"),
                    _("Generate a new Personal Access Token on GitHub")
                ]
            }
        
        # Remote branch ahead (need to pull)
        if any(x in error_lower for x in ["non-fast-forward", "updates were rejected", "fetch first"]):
            return {
                "diagnosis": _("Remote branch has changes you don't have locally"),
                "solutions": [
                    _("Use 'Pull Latest' button first to get remote changes"),
                    _("Or run: git pull --rebase origin {0}").format(branch),
                    _("Then try pushing again")
                ]
            }
        
        # Protected branch
        if any(x in error_lower for x in ["protected branch", "required status", "review required"]):
            return {
                "diagnosis": _("This branch has protection rules - direct push is not allowed"),
                "solutions": [
                    _("Push to a development branch instead (e.g., dev-yourname)"),
                    _("Create a Pull Request to merge your changes"),
                    _("Ask a maintainer to temporarily disable branch protection")
                ]
            }
        
        # Network errors
        if any(x in error_lower for x in ["could not resolve", "network", "connection refused", "timed out"]):
            return {
                "diagnosis": _("Network error - cannot reach remote server"),
                "solutions": [
                    _("Check your internet connection"),
                    _("Try again in a few moments"),
                    _("Check if GitHub/remote is accessible")
                ]
            }
        
        # Repository access
        if any(x in error_lower for x in ["repository not found", "does not exist"]):
            return {
                "diagnosis": _("Remote repository not found or you don't have access"),
                "solutions": [
                    _("Verify the remote URL: git remote -v"),
                    _("Check if you have write access to the repository"),
                    _("Request access from the repository owner")
                ]
            }
        
        # Branch doesn't exist on remote
        if "src refspec" in error_lower and "does not match any" in error_lower:
            return {
                "diagnosis": _("Local branch configuration issue"),
                "solutions": [
                    _("Try: git push --set-upstream origin {0}").format(branch),
                    _("Or verify you have commits on this branch")
                ]
            }
        
        # Default / unknown error
        return {
            "diagnosis": _("Push failed with error: {0}").format(error_output[:200]),
            "solutions": [
                _("Check the error message above for details"),
                _("Try running 'git push' in terminal to see full output"),
                _("Check GitHub status: https://githubstatus.com")
            ]
        }
    
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
    
    def on_undo_commit_requested(self, widget):
        """Handle undo last commit request - executes git reset HEAD~1"""
        import subprocess
        
        logger = self.build_package.logger if hasattr(self.build_package, 'logger') else None
        
        def log(style, msg):
            if logger:
                logger.log(style, msg)
            else:
                print(f"[{style}] {msg}")
        
        def undo_operation():
            log("cyan", _("Undoing last commit..."))
            log("dim", "    git reset HEAD~1")
            
            result = subprocess.run(
                ["git", "reset", "HEAD~1"],
                capture_output=True, text=True, check=False
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                log("red", _("✗ Failed to undo commit: {0}").format(error_msg))
                raise Exception(_("Failed to undo commit: {0}").format(error_msg))
            
            log("green", _("✓ Last commit undone successfully"))
            log("white", _("Your changes are now in the working directory"))
            log("yellow", _("You can modify files and commit again"))
            
            return True
        
        self.operation_runner.run_with_progress(
            undo_operation,
            _("Undoing Commit"),
            _("Undoing last commit (keeping changes)...")
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
        dialog.add_response("discard", _("Discard & Switch"))
        dialog.add_response("stash", _("Stash & Switch"))
        
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
        """Perform the actual branch switch with optional stash/discard"""
        import subprocess
        
        stashed = False
        
        try:
            # Step 1: Handle local changes if needed
            if discard_first:
                subprocess.run(["git", "checkout", "--", "."], check=True, capture_output=True)
                subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True)
            elif stash_first:
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-u", "-m", f"auto-stash-before-switch-to-{target_branch}"],
                    capture_output=True, text=True, check=False
                )
                if stash_result.returncode != 0:
                    self.show_error_toast(_("Failed to stash changes"))
                    return
                stashed = True
            
            # Step 2: Switch branch
            checkout_result = subprocess.run(
                ["git", "checkout", target_branch],
                capture_output=True, text=True, check=False
            )
            
            if checkout_result.returncode != 0:
                error_msg = checkout_result.stderr.strip()
                self.show_error_toast(_("Failed to switch: {0}").format(error_msg))
                # Restore stash if we stashed
                if stashed:
                    subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
                return
            
            # Step 3: Restore stash if we stashed
            if stashed:
                pop_result = subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True, text=True, check=False
                )
                if pop_result.returncode != 0:
                    if "CONFLICT" in pop_result.stdout or "CONFLICT" in pop_result.stderr:
                        self.show_info_toast(_("Switched to {0}. Conflicts detected - resolve manually.").format(target_branch))
                    else:
                        self.show_info_toast(_("Switched to {0}. Check 'git stash list' for your changes.").format(target_branch))
                else:
                    self.show_toast(_("Switched to {0} with your changes restored.").format(target_branch))
            else:
                self.show_toast(_("Switched to branch: {0}").format(target_branch))
            
            # Step 4: Refresh UI
            if hasattr(self, 'branch_widget'):
                self.branch_widget.refresh_branches()
            self.refresh_all_widgets()
            
        except subprocess.CalledProcessError as e:
            self.show_error_toast(_("Error switching branch: {0}").format(str(e)))
    
    def on_merge_requested(self, widget, source_branch, target_branch, auto_merge):
        """Handle merge request - create PR with optional auto-merge"""
        # Show confirmation dialog first
        self._show_merge_confirmation(source_branch, target_branch, auto_merge)
    
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
        
        # Navigate to content area in mobile/folded view
        if self.leaflet.get_folded():
            # Get the content box (second child of leaflet)
            content_box = self.leaflet.get_child_at_index(1)
            if content_box:
                self.leaflet.set_visible_child(content_box)
    
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
            # Commit badge - show number of uncommitted changes
            if "commit" in self.nav_rows:
                if self.build_package.is_git_repo and GitUtils.has_changes():
                    # Count changed files
                    import subprocess
                    result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True
                    )
                    if result.returncode == 0:
                        changes = len([l for l in result.stdout.strip().split('\n') if l.strip()])
                        if changes > 0:
                            self.nav_rows["commit"].badge.set_text(str(changes))
                            self.nav_rows["commit"].badge.set_visible(True)
                            self.nav_rows["commit"].badge.add_css_class("warning")
                        else:
                            self.nav_rows["commit"].badge.set_visible(False)
                    else:
                        self.nav_rows["commit"].badge.set_visible(False)
                else:
                    self.nav_rows["commit"].badge.set_visible(False)
            
            # Branches badge - could show number of branches or active merges
            # Package badge - could show build status
            # AUR badge - could show available updates
            # These remain hidden for now but infrastructure is ready
            
        except Exception as e:
            print(f"Error updating nav badges: {e}")
        
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
        if self.leaflet.get_folded():
            self.leaflet.set_visible_child(self.leaflet.get_child_at_index(0))  # sidebar