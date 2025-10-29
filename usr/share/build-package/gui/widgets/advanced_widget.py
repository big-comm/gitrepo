#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/advanced_widget.py - Advanced operations widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.git_utils import GitUtils

class OperationRow(Adw.ActionRow):
    """Custom row for advanced operations"""
    
    __gtype_name__ = 'OperationRow'
    
    def __init__(self, operation_id, title, description, icon_name, is_destructive=False):
        super().__init__()
        
        self.operation_id = operation_id
        self.is_destructive = is_destructive
        
        self.set_title(title)
        self.set_subtitle(description)
        self.set_activatable(True)
        
        # Add icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        if is_destructive:
            icon.add_css_class("error")
        self.add_prefix(icon)
        
        # Add styling for destructive actions
        if is_destructive:
            self.add_css_class("destructive-action")

class CommitRow(Adw.ActionRow):
    """Custom row for commit display"""
    
    __gtype_name__ = 'CommitRow'
    
    def __init__(self, commit_hash, author, date, message):
        super().__init__()
        
        self.commit_hash = commit_hash
        
        self.set_title(f"{commit_hash[:7]} - {message[:60]}")
        self.set_subtitle(f"{author} • {date}")
        self.set_activatable(True)

class AdvancedWidget(Gtk.Box):
    """Widget for advanced operations"""
    
    __gsignals__ = {
        'cleanup-branches-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'cleanup-actions-requested': (GObject.SignalFlags.RUN_FIRST, None, (str,)),  # status type
        'cleanup-tags-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'revert-commit-requested': (GObject.SignalFlags.RUN_FIRST, None, (str, str)),  # commit_hash, method
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_vexpand(False)  # Prevent vertical expansion
        self.set_valign(Gtk.Align.START)  # Align to top
        
        self.build_package = build_package
        self.recent_commits = []
        
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        self.create_ui()
        self.refresh_commits()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Advanced Operations"))
        title_label.add_css_class("title-2")
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_text(_("Advanced Git operations and maintenance"))
        subtitle_label.add_css_class("subtitle")
        header_box.append(subtitle_label)
        
        self.append(header_box)
        
        # Warning banner
        warning_banner = Adw.Banner()
        warning_banner.set_title(_("Warning: These operations can be destructive"))
        warning_banner.add_css_class("error")
        self.append(warning_banner)
        
        # Cleanup operations
        cleanup_group = Adw.PreferencesGroup()
        cleanup_group.set_title(_("Cleanup Operations"))
        cleanup_group.set_description(_("Remove old branches, actions, and tags"))
        
        cleanup_operations = [
            ("branches", _("Delete Old Branches"), _("Remove development branches except main and latest"), 
             "edit-delete-symbolic", True),
            ("failed_actions", _("Delete Failed Actions"), _("Remove failed GitHub Action jobs"), 
             "process-stop-symbolic", True),
            ("success_actions", _("Delete Successful Actions"), _("Remove successful GitHub Action jobs"), 
             "emblem-ok-symbolic", False),
            ("tags", _("Delete All Tags"), _("Remove all repository tags"), 
             "bookmark-remove-symbolic", True),
        ]
        
        self.cleanup_list = Gtk.ListBox()
        self.cleanup_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.cleanup_list.add_css_class("boxed-list")
        self.cleanup_list.connect('row-activated', self.on_cleanup_operation_activated)
        
        for op_id, title, desc, icon, destructive in cleanup_operations:
            row = OperationRow(op_id, title, desc, icon, destructive)
            self.cleanup_list.append(row)
        
        cleanup_group.add(self.cleanup_list)
        self.append(cleanup_group)
        
        # Commit revert operations
        revert_group = Adw.PreferencesGroup()
        revert_group.set_title(_("Commit History"))
        revert_group.set_description(_("View and revert recent commits"))
        
        # Commit list
        scrolled_commits = Gtk.ScrolledWindow()
        scrolled_commits.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.commits_list = Gtk.ListBox()
        self.commits_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.commits_list.add_css_class("boxed-list")
        self.commits_list.connect('row-selected', self.on_commit_selected)
        
        scrolled_commits.set_child(self.commits_list)
        revert_group.add(scrolled_commits)
        
        # Revert options
        self.revert_method_row = Adw.ComboRow()
        self.revert_method_row.set_title(_("Revert Method"))
        self.revert_method_row.set_subtitle(_("Choose how to undo the commit"))
        
        methods = Gtk.StringList()
        methods.append(_("Revert (keep history)"))
        methods.append(_("Reset (remove from history)"))
        self.revert_method_row.set_model(methods)
        self.revert_method_row.set_selected(0)  # Default to revert
        
        revert_group.add(self.revert_method_row)
        
        self.append(revert_group)
        
        # Repository statistics
        stats_group = Adw.PreferencesGroup()
        stats_group.set_title(_("Repository Statistics"))
        
        self.branch_count_row = Adw.ActionRow()
        self.branch_count_row.set_title(_("Total Branches"))
        stats_group.add(self.branch_count_row)
        
        self.commit_count_row = Adw.ActionRow()
        self.commit_count_row.set_title(_("Commits in Current Branch"))
        stats_group.add(self.commit_count_row)
        
        self.repo_size_row = Adw.ActionRow()
        self.repo_size_row.set_title(_("Repository Size"))
        stats_group.add(self.repo_size_row)
        
        self.append(stats_group)
        
        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)
        
        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_label(_("Refresh"))
        refresh_button.connect('clicked', self.on_refresh_clicked)
        actions_box.append(refresh_button)
        
        # Revert button
        self.revert_button = Gtk.Button()
        self.revert_button.set_label(_("Revert Selected"))
        self.revert_button.add_css_class("destructive-action")
        self.revert_button.connect('clicked', self.on_revert_clicked)
        self.revert_button.set_sensitive(False)
        actions_box.append(self.revert_button)
        
        self.append(actions_box)
    
    def refresh_commits(self):
        """Refresh commit list"""
        if not self.build_package.is_git_repo:
            return
        
        try:
            import subprocess
            
            # Get recent commits
            result = subprocess.run(
                ["git", "log", "-10", "--pretty=format:%H|%an|%ad|%s", "--date=short"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            
            # Clear existing commits
            while True:
                row = self.commits_list.get_row_at_index(0)
                if row:
                    self.commits_list.remove(row)
                else:
                    break
            
            # Parse and add commits
            self.recent_commits = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|', 3)
                    if len(parts) == 4:
                        commit = {
                            'hash': parts[0],
                            'author': parts[1],
                            'date': parts[2],
                            'message': parts[3]
                        }
                        self.recent_commits.append(commit)
                        
                        row = CommitRow(
                            commit['hash'],
                            commit['author'],
                            commit['date'],
                            commit['message']
                        )
                        self.commits_list.append(row)
            
            self.refresh_stats()
            
        except Exception as e:
            print(f"Error refreshing commits: {e}")
    
    def refresh_stats(self):
        """Refresh repository statistics"""
        try:
            import subprocess
            import os
            
            # Branch count
            try:
                result = subprocess.run(
                    ["git", "branch", "-a"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True
                )
                branch_count = len([b for b in result.stdout.split('\n') if b.strip()])
                self.branch_count_row.set_subtitle(str(branch_count))
            except:
                self.branch_count_row.set_subtitle(_("Unknown"))
            
            # Commit count
            try:
                result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True
                )
                commit_count = result.stdout.strip()
                self.commit_count_row.set_subtitle(commit_count)
            except:
                self.commit_count_row.set_subtitle(_("Unknown"))
            
            # Repository size
            try:
                repo_path = GitUtils.get_repo_root_path()
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(repo_path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        try:
                            total_size += os.path.getsize(filepath)
                        except:
                            pass
                
                # Convert to human readable
                if total_size > 1024*1024*1024:
                    size_text = f"{total_size/(1024*1024*1024):.1f} GB"
                elif total_size > 1024*1024:
                    size_text = f"{total_size/(1024*1024):.1f} MB"
                elif total_size > 1024:
                    size_text = f"{total_size/1024:.1f} KB"
                else:
                    size_text = f"{total_size} bytes"
                
                self.repo_size_row.set_subtitle(size_text)
            except:
                self.repo_size_row.set_subtitle(_("Unknown"))
                
        except Exception as e:
            print(f"Error refreshing stats: {e}")
    
    def on_cleanup_operation_activated(self, list_box, row):
        """Handle cleanup operation selection"""
        operation_id = row.operation_id
        
        # Show confirmation dialog
        self.show_cleanup_confirmation(operation_id, row.get_title(), row.is_destructive)
    
    def show_cleanup_confirmation(self, operation_id, operation_name, is_destructive):
        """Show cleanup confirmation dialog"""
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Confirm Cleanup Operation"),
            _("Are you sure you want to perform '{0}'?\n\nThis operation cannot be undone.").format(operation_name)
        )
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", _("Confirm"))
        
        if is_destructive:
            dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "confirm":
                self.execute_cleanup_operation(operation_id)
            dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()
    
    def execute_cleanup_operation(self, operation_id):
        """Execute cleanup operation"""
        if operation_id == "branches":
            self.emit('cleanup-branches-requested')
        elif operation_id == "failed_actions":
            self.emit('cleanup-actions-requested', "failure")
        elif operation_id == "success_actions":
            self.emit('cleanup-actions-requested', "success")
        elif operation_id == "tags":
            self.emit('cleanup-tags-requested')
    
    def on_commit_selected(self, list_box, row):
        """Handle commit selection"""
        self.revert_button.set_sensitive(row is not None)
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.refresh_commits()
    
    def on_revert_clicked(self, button):
        """Handle revert button click"""
        selected_row = self.commits_list.get_selected_row()
        if not selected_row:
            return
        
        commit_hash = selected_row.commit_hash
        method_index = self.revert_method_row.get_selected()
        method = "revert" if method_index == 0 else "reset"
        
        # Show revert confirmation
        self.show_revert_confirmation(commit_hash, method, selected_row.get_title())
    
    def show_revert_confirmation(self, commit_hash, method, commit_title):
        """Show revert confirmation dialog"""
        method_text = _("revert") if method == "revert" else _("reset")
        
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Confirm Commit {0}").format(method_text.title()),
            _("Are you sure you want to {0} this commit?\n\n{1}\n\nCommit: {2}").format(
                method_text, commit_title, commit_hash[:7]
            )
        )
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", method_text.title())
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "confirm":
                self.emit('revert-commit-requested', commit_hash, method)
                self.refresh_commits()  # Refresh after revert
            dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()