#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/overview_widget.py - Overview dashboard widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.git_utils import GitUtils
from core.config import APP_NAME, APP_VERSION, APP_DESC

class StatusCard(Gtk.Box):
    """Custom status card widget"""
    
    def __init__(self, title, value, icon_name, status_type="info"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        self.set_size_request(160, 80)
        self.add_css_class("card")
        self.set_margin_top(3)
        self.set_margin_bottom(3)
        self.set_margin_start(3)
        self.set_margin_end(3)
        
        # Icon - store reference
        self.icon = Gtk.Image.new_from_icon_name(icon_name)
        self.icon.set_pixel_size(32)
        if status_type == "warning":
            self.icon.add_css_class("warning")
        elif status_type == "error":
            self.icon.add_css_class("error")
        elif status_type == "success":
            self.icon.add_css_class("success")

        self.append(self.icon)
        
        # Value (store reference)
        self.value_label = Gtk.Label()
        self.value_label.set_text(str(value))
        self.value_label.add_css_class("title-3")
        self.append(self.value_label)
        
        # Title
        title_label = Gtk.Label()
        title_label.set_text(title)
        title_label.add_css_class("subtitle")
        title_label.set_wrap(True)
        title_label.set_justify(Gtk.Justification.CENTER)
        self.append(title_label)

class QuickActionCard(Adw.ActionRow):
    """Quick action card for common operations"""
    
    def __init__(self, title, description, icon_name, action_id):
        super().__init__()
        
        self.action_id = action_id
        
        self.set_title(title)
        self.set_subtitle(description)
        self.set_activatable(True)
        
        # Add icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        self.add_prefix(icon)
        
        # Add arrow
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        self.add_suffix(arrow)

class OverviewWidget(Gtk.Box):
    """Overview dashboard widget"""
    
    __gsignals__ = {
        'quick-action': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'refresh-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.build_package = build_package

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        
        self.create_ui()
        self.refresh_overview()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Repository status banner
        self.status_banner = Adw.Banner()
        self.append(self.status_banner)
        
        # Status cards grid
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Repository Status"))
        
        # Cards container
        cards_flow = Gtk.FlowBox()
        cards_flow.set_max_children_per_line(4)
        cards_flow.set_min_children_per_line(2)
        cards_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        cards_flow.set_homogeneous(True)
        
        # Create status cards with standard GNOME icons
        self.repo_card = StatusCard(_("Repository"), "—", "folder-symbolic")
        self.branch_card = StatusCard(_("Current Branch"), "—", "media-playlist-consecutive-symbolic")
        self.changes_card = StatusCard(_("Changes"), "—", "document-edit-symbolic")
        self.commits_card = StatusCard(_("Commits"), "—", "view-list-symbolic")
        
        cards_flow.append(self.repo_card)
        cards_flow.append(self.branch_card)
        cards_flow.append(self.changes_card)
        cards_flow.append(self.commits_card)
        
        status_group.add(cards_flow)
        self.append(status_group)
        
        # Quick actions
        actions_group = Adw.PreferencesGroup()
        actions_group.set_title(_("Quick Actions"))
        
        self.quick_actions_list = Gtk.ListBox()
        self.quick_actions_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.quick_actions_list.add_css_class("boxed-list")
        self.quick_actions_list.connect('row-activated', self.on_quick_action_activated)
        
        # Define quick actions (order matches CLI menu)
        quick_actions = [
            ("pull", _("Pull Latest"), _("Pull latest changes from remote repository"), 
             "go-down-symbolic"),
            ("commit", _("Commit and Push"), _("Stage changes and push to development branch"), 
             "document-save-symbolic"),
            ("package_testing", _("Build Testing Package"), _("Build and deploy to testing repository"), 
             "package-x-generic-symbolic"),
            ("package_stable", _("Build Stable Package"), _("Build and deploy to stable repository"), 
             "emblem-ok-symbolic"),
            ("aur", _("Build AUR Package"), _("Build package from Arch User Repository"), 
             "system-software-install-symbolic"),
        ]
        
        for action_id, title, desc, icon in quick_actions:
            card = QuickActionCard(title, desc, icon, action_id)
            self.quick_actions_list.append(card)
        
        actions_group.add(self.quick_actions_list)
        self.append(actions_group)
        
        # Recent activity
        activity_group = Adw.PreferencesGroup()
        activity_group.set_title(_("Recent Activity"))
        
        self.activity_row = Adw.ActionRow()
        self.activity_row.set_title(_("No recent activity"))
        self.activity_row.set_subtitle(_("Activity will appear here after operations"))
        activity_group.add(self.activity_row)
        
        self.append(activity_group)
        
        # Actions bar at bottom
        actions_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_bar.set_halign(Gtk.Align.END)
        actions_bar.set_margin_top(12)
        
        # Show welcome button
        welcome_button = Gtk.Button()
        welcome_button.set_icon_name("help-about-symbolic")
        welcome_button.set_tooltip_text(_("Show welcome screen"))
        welcome_button.connect('clicked', self.on_welcome_clicked)
        actions_bar.append(welcome_button)
        
        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_label(_("Refresh Status"))
        refresh_button.set_tooltip_text(_("Refresh repository status and information"))
        refresh_button.connect('clicked', self.on_refresh_clicked)
        actions_bar.append(refresh_button)
        
        self.append(actions_bar)
    
    def refresh_overview(self):
        """Refresh overview information"""
        try:
            # Update repository status banner
            if self.build_package.is_git_repo:
                repo_name = GitUtils.get_repo_name()
                if repo_name:
                    self.status_banner.set_title(_("Connected to repository: {0}").format(repo_name))
                    self.status_banner.set_revealed(True)
                else:
                    self.status_banner.set_title(_("Git repository detected"))
                    self.status_banner.set_revealed(True)
            else:
                self.status_banner.set_title(_("Not in a Git repository - some features will be limited"))
                self.status_banner.set_revealed(True)
            
            # Update status cards
            self.update_status_cards()
            
            # Update recent activity
            self.update_recent_activity()
            
        except Exception as e:
            print(f"Error refreshing overview: {e}")
    
    def update_status_cards(self):
        """Update status cards with current information"""
        if not self.build_package.is_git_repo:
            self.repo_card.value_label.set_text(_("Not a Git repo"))
            return
        
        try:
            # Repository card
            repo_name = GitUtils.get_repo_name()
            if repo_name:
                repo_display = repo_name.split('/')[-1]  # Show only repo name, not org/repo
                self.repo_card.value_label.set_text(repo_display)
            else:
                self.repo_card.value_label.set_text(_("Local repo"))
            
            # Branch card
            current_branch = GitUtils.get_current_branch()
            if current_branch:
                self.branch_card.value_label.set_text(current_branch)
            else:
                self.branch_card.value_label.set_text(_("Unknown"))
            
            # Changes card - clear previous CSS classes first
            self.changes_card.icon.remove_css_class("warning")
            self.changes_card.icon.remove_css_class("success")
            
            if GitUtils.has_changes():
                self.changes_card.value_label.set_text(_("Modified"))
                self.changes_card.icon.add_css_class("warning")
            else:
                # TRANSLATORS: Status when working directory has no modifications
                self.changes_card.value_label.set_text(_("No changes"))
                self.changes_card.icon.add_css_class("success")
            
            # Commits card
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True
                )
                commit_count = result.stdout.strip()
                self.commits_card.value_label.set_text(commit_count)
            except subprocess.SubprocessError:
                self.commits_card.value_label.set_text("—")
                
        except Exception as e:
            print(f"Error updating status cards: {e}")
    
    def update_recent_activity(self):
        """Update recent activity information"""
        # Placeholder - could show last commit, last build, etc.
        try:
            if self.build_package.is_git_repo:
                import subprocess
                result = subprocess.run(
                    ["git", "log", "-1", "--pretty=format:%s (%ar)"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True
                )
                
                if result.stdout.strip():
                    self.activity_row.set_title(_("Last commit"))
                    self.activity_row.set_subtitle(result.stdout.strip())
                
        except subprocess.SubprocessError:
            pass
    
    def on_quick_action_activated(self, list_box, row):
        """Handle quick action selection"""
        if hasattr(row, 'action_id'):
            self.emit('quick-action', row.action_id)
    
    def on_welcome_clicked(self, button):
        """Handle welcome button click"""
        # Get the main window and trigger welcome action
        window = self.get_root()
        if window and hasattr(window, 'show_welcome_dialog'):
            window.show_welcome_dialog()
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.emit('refresh-requested')
        self.refresh_overview()