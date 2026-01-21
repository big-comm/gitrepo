#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/branch_widget.py - Branch management widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.git_utils import GitUtils

class BranchRow(Adw.ActionRow):
    """Custom row for branch display"""
    
    __gtype_name__ = 'BranchRow'
    
    def __init__(self, branch_name, is_current=False, is_remote=False):
        super().__init__()
        
        self.branch_name = branch_name
        self.is_current = is_current
        self.is_remote = is_remote
        
        self.set_title(branch_name)
        self.set_activatable(True)
        
        # Add indicators
        if is_current:
            self.set_subtitle(_("Current branch"))
            current_icon = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
            self.add_prefix(current_icon)
            self.add_css_class("accent")
        
        if is_remote:
            remote_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
            self.add_suffix(remote_icon)

class BranchWidget(Gtk.Box):
    """Widget for branch management operations"""
    
    __gsignals__ = {
        'branch-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'merge-requested': (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        'cleanup-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        self.build_package = build_package
        self.current_branch = None
        self.branches = []
        self._block_selection_signal = False  # Flag to prevent signal loops

        # Remover vexpand para evitar espaço vazio
        self.set_valign(Gtk.Align.START)

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        
        self.create_ui()
        self.refresh_branches()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Branch Management"))
        title_label.add_css_class("title-4")
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_text(_("Manage Git branches and merge operations"))
        subtitle_label.add_css_class("subtitle")
        header_box.append(subtitle_label)
        
        self.append(header_box)
        
        # Current status
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Current Status"))
        
        self.current_branch_row = Adw.ActionRow()
        self.current_branch_row.set_title(_("Active Branch"))
        status_group.add(self.current_branch_row)
        
        self.most_recent_row = Adw.ActionRow()
        self.most_recent_row.set_title(_("Most Recent Branch"))
        self.most_recent_row.set_subtitle(_("Branch with latest commits"))
        status_group.add(self.most_recent_row)
        
        self.append(status_group)
        
        # Branch list
        branches_group = Adw.PreferencesGroup()
        branches_group.set_title(_("Available Branches"))
        
        # Scrolled window for branch list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.branches_list = Gtk.ListBox()
        self.branches_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.branches_list.add_css_class("boxed-list")
        self.branches_list.connect('row-selected', self.on_branch_selected)
        
        scrolled.set_child(self.branches_list)
        branches_group.add(scrolled)
        
        self.append(branches_group)
        
        # Merge operations
        merge_group = Adw.PreferencesGroup()
        merge_group.set_title(_("Merge Operations"))
        
        # Source branch selection
        self.source_branch_row = Adw.ComboRow()
        self.source_branch_row.set_title(_("Source Branch"))
        self.source_branch_row.set_subtitle(_("Branch to merge from"))
        merge_group.add(self.source_branch_row)
        
        # Target branch selection
        self.target_branch_row = Adw.ComboRow()
        self.target_branch_row.set_title(_("Target Branch"))
        self.target_branch_row.set_subtitle(_("Branch to merge into"))
        merge_group.add(self.target_branch_row)
        
        # Auto-merge option
        self.auto_merge_row = Adw.SwitchRow()
        self.auto_merge_row.set_title(_("Auto-merge"))
        self.auto_merge_row.set_subtitle(_("Automatically merge if no conflicts"))
        merge_group.add(self.auto_merge_row)
        
        self.append(merge_group)
        
        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)
        
        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_label(_("Refresh"))
        refresh_button.set_tooltip_text(_("Refresh branch list"))
        refresh_button.connect('clicked', self.on_refresh_clicked)
        actions_box.append(refresh_button)
        
        # Cleanup button
        cleanup_button = Gtk.Button()
        cleanup_button.set_label(_("Cleanup Branches"))
        cleanup_button.set_tooltip_text(_("Remove old development branches"))
        cleanup_button.add_css_class("destructive-action")
        cleanup_button.connect('clicked', self.on_cleanup_clicked)
        actions_box.append(cleanup_button)
        
        # Merge button
        self.merge_button = Gtk.Button()
        self.merge_button.set_label(_("Create Merge Request"))
        self.merge_button.add_css_class("suggested-action")
        self.merge_button.connect('clicked', self.on_merge_clicked)
        self.merge_button.set_sensitive(False)
        actions_box.append(self.merge_button)
        
        self.append(actions_box)
        
        # Connect combo box changes
        self.source_branch_row.connect('notify::selected', self.on_merge_selection_changed)
        self.target_branch_row.connect('notify::selected', self.on_merge_selection_changed)
    
    def refresh_branches(self):
        """Refresh branch information"""
        if not self.build_package.is_git_repo:
            return
        
        # Block selection signal during refresh to prevent loops
        self._block_selection_signal = True
        
        # Get current branch
        self.current_branch = GitUtils.get_current_branch()
        if self.current_branch:
            self.current_branch_row.set_subtitle(self.current_branch)
        
        # Get most recent branch
        most_recent = GitUtils.get_most_recent_branch(self.build_package.logger)
        self.most_recent_row.set_subtitle(most_recent)
        
        # Get all branches
        try:
            import subprocess
            
            # Get local branches
            local_result = subprocess.run(
                ["git", "branch"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            local_branches = [
                b.strip('* ').strip() for b in local_result.stdout.strip().split('\n') 
                if b.strip()
            ]
            
            # Get remote branches
            remote_result = subprocess.run(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            remote_branches = [
                b.strip().replace('origin/', '') for b in remote_result.stdout.strip().split('\n')
                if b.strip() and 'HEAD' not in b
            ]
            
            # Combine and deduplicate
            all_branches = list(set(local_branches + remote_branches))
            all_branches.sort()
            
            # Clear existing branches
            while True:
                row = self.branches_list.get_row_at_index(0)
                if row:
                    self.branches_list.remove(row)
                else:
                    break
            
            # Add branches to list
            for branch in all_branches:
                is_current = (branch == self.current_branch)
                is_remote = (branch in remote_branches and branch not in local_branches)
                
                row = BranchRow(branch, is_current, is_remote)
                self.branches_list.append(row)
            
            # Update combo boxes
            self.update_combo_boxes(all_branches)
            
        except Exception as e:
            print(f"Error refreshing branches: {e}")
        finally:
            # Always unblock signal after refresh
            self._block_selection_signal = False
    
    def update_combo_boxes(self, branches):
        """Update merge combo boxes with branch list"""
        # Create string list for branches
        branch_list = Gtk.StringList()
        for branch in branches:
            branch_list.append(branch)
        
        # Update combo boxes
        self.source_branch_row.set_model(branch_list)
        self.target_branch_row.set_model(branch_list)
        
        # Set default selections
        if "main" in branches:
            main_index = branches.index("main")
            self.target_branch_row.set_selected(main_index)
        
        if self.current_branch and self.current_branch in branches:
            current_index = branches.index(self.current_branch)
            self.source_branch_row.set_selected(current_index)
    
    def on_branch_selected(self, list_box, row):
        """Handle branch selection"""
        # Ignore if signal is blocked (during refresh) or no row selected
        if self._block_selection_signal or not row:
            return
        branch_name = row.branch_name
        self.emit('branch-selected', branch_name)
    
    def on_merge_selection_changed(self, combo_row, param):
        """Handle merge combo box changes"""
        source_selected = self.source_branch_row.get_selected() != Gtk.INVALID_LIST_POSITION
        target_selected = self.target_branch_row.get_selected() != Gtk.INVALID_LIST_POSITION
        
        self.merge_button.set_sensitive(source_selected and target_selected)
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.refresh_branches()
    
    def on_cleanup_clicked(self, button):
        """Handle cleanup button click"""
        self.emit('cleanup-requested')
    
    def on_merge_clicked(self, button):
        """Handle merge button click"""
        source_index = self.source_branch_row.get_selected()
        target_index = self.target_branch_row.get_selected()
        
        if source_index == Gtk.INVALID_LIST_POSITION or target_index == Gtk.INVALID_LIST_POSITION:
            return
        
        source_model = self.source_branch_row.get_model()
        target_model = self.target_branch_row.get_model()
        
        source_branch = source_model.get_string(source_index)
        target_branch = target_model.get_string(target_index)
        
        if source_branch == target_branch:
            # Show error - cannot merge branch into itself
            return
        
        self.emit('merge-requested', source_branch, target_branch)