#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/commit_widget.py - Commit widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.git_utils import GitUtils

class CommitTypeRow(Adw.ActionRow):
    """Custom row for commit type selection"""
    
    __gtype_name__ = 'CommitTypeRow'
    
    def __init__(self, emoji, commit_type, description):
        super().__init__()
        
        self.emoji = emoji
        self.commit_type = commit_type
        
        self.set_title(f"{emoji} {commit_type}")
        self.set_subtitle(description)
        self.set_activatable(True)
        
        # Add emoji as prefix
        emoji_label = Gtk.Label()
        emoji_label.set_text(emoji)
        emoji_label.set_margin_end(8)
        self.add_prefix(emoji_label)

class CommitWidget(Gtk.Box):
    """Widget for commit and push operations"""
    
    __gsignals__ = {
        'commit-requested': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'push-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'undo-commit-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.build_package = build_package
        self.selected_commit_type = None
        self.selected_emoji = None

        # Remover vexpand para evitar espaço vazio
        self.set_valign(Gtk.Align.START)

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        
        self.create_ui()
        self.refresh_status()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Commit and Push"))
        title_label.add_css_class("title-4")
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_text(_("Stage changes and push to your development branch"))
        subtitle_label.add_css_class("subtitle")
        header_box.append(subtitle_label)
        
        self.append(header_box)
        
        # Status group
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Repository Status"))
        
        self.changes_row = Adw.ActionRow()
        self.changes_row.set_title(_("Working Directory"))
        status_group.add(self.changes_row)
        
        self.branch_row = Adw.ActionRow()
        self.branch_row.set_title(_("Current Branch"))
        status_group.add(self.branch_row)
        
        # Last commit row (for undo functionality)
        self.last_commit_row = Adw.ActionRow()
        self.last_commit_row.set_title(_("Last Commit"))
        self.last_commit_row.set_subtitle(_("No commit info"))
        
        # Undo button as suffix
        self.undo_button = Gtk.Button()
        self.undo_button.set_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text(_("Undo last commit (keep changes)"))
        self.undo_button.set_valign(Gtk.Align.CENTER)
        self.undo_button.add_css_class("flat")
        self.undo_button.connect('clicked', self.on_undo_clicked)
        self.undo_button.set_visible(False)  # Hidden by default
        self.last_commit_row.add_suffix(self.undo_button)
        
        status_group.add(self.last_commit_row)
        
        self.append(status_group)
        
        # Commit type selection using ExpanderRow (opens below, larger)
        commit_type_group = Adw.PreferencesGroup()
        commit_type_group.set_title(_("Commit"))
        
        # Get commit types
        self.commit_types = self.build_package.get_commit_types()
        
        # Create expander row for commit types
        self.commit_type_expander = Adw.ExpanderRow()
        self.commit_type_expander.set_title(_("Commit Type"))
        self.commit_type_expander.set_subtitle(_("Select the type of change"))
        
        # Add commit type rows inside expander
        for idx, (emoji, commit_type, description) in enumerate(self.commit_types):
            type_row = Adw.ActionRow()
            type_row.set_title(f"{emoji} {commit_type}")
            type_row.set_subtitle(description)
            type_row.set_activatable(True)
            type_row.commit_type = commit_type
            type_row.emoji = emoji
            type_row.idx = idx
            
            # Add checkmark for selected
            check_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            check_icon.set_visible(False)
            type_row.check_icon = check_icon
            type_row.add_suffix(check_icon)
            
            type_row.connect('activated', self.on_commit_type_row_activated)
            self.commit_type_expander.add_row(type_row)
        
        commit_type_group.add(self.commit_type_expander)
        self.append(commit_type_group)

        # Commit message entry
        message_group = Adw.PreferencesGroup()
        message_group.set_title(_("Commit Message"))
        
        self.message_entry = Adw.EntryRow()
        self.message_entry.set_title(_("Description"))
        self.message_entry.connect('changed', self.on_message_changed)
        self.message_entry.connect('activate', self.on_commit_clicked)
        message_group.add(self.message_entry)
        
        self.append(message_group)
        
        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(6)
        
        # Pull button
        self.pull_button = Gtk.Button()
        self.pull_button.set_label(_("Pull Latest"))
        self.pull_button.set_tooltip_text(_("Pull latest changes from remote"))
        self.pull_button.connect('clicked', self.on_pull_clicked)
        actions_box.append(self.pull_button)
        
        # Commit button
        self.commit_button = Gtk.Button()
        self.commit_button.set_label(_("Commit and Push"))
        self.commit_button.add_css_class("suggested-action")
        self.commit_button.connect('clicked', self.on_commit_clicked)
        self.commit_button.set_sensitive(False)
        actions_box.append(self.commit_button)
        
        self.append(actions_box)
        
        # Select first commit type by default
        if len(self.commit_types) > 0:
            # Find and select first row in expander
            first_row = None
            child = self.commit_type_expander.get_first_child()
            while child:
                if hasattr(child, 'commit_type'):
                    first_row = child
                    break
                child = child.get_next_sibling()
            
            if first_row:
                self._select_commit_type_row(first_row)
    
    def refresh_status(self):
        """Refresh repository status"""
        import subprocess
        
        # Clear previous state from changes_row
        self.changes_row.remove_css_class("warning")
        self.changes_row.remove_css_class("success")
        
        # Remove previous suffix icon if exists
        if hasattr(self, '_status_suffix_icon') and self._status_suffix_icon:
            self.changes_row.remove(self._status_suffix_icon)
            self._status_suffix_icon = None
        
        # Check for changes
        if GitUtils.has_changes():
            self.changes_row.set_subtitle(_("Uncommitted changes present"))
            self._status_suffix_icon = Gtk.Image.new_from_icon_name("emblem-important-symbolic")
            self._status_suffix_icon.set_tooltip_text(_("You have uncommitted changes that need to be committed"))
            self.changes_row.add_suffix(self._status_suffix_icon)
            self.changes_row.add_css_class("warning")
        else:
            self.changes_row.set_subtitle(_("Working directory clean"))
            self._status_suffix_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            self._status_suffix_icon.set_tooltip_text(_("No pending changes - working directory is clean"))
            self.changes_row.add_suffix(self._status_suffix_icon)
            self.changes_row.add_css_class("success")
        
        # Current branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            self.branch_row.set_subtitle(current_branch)
        else:
            self.branch_row.set_subtitle(_("Unknown"))
        
        # Last commit info
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%h|%s"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split("|", 1)
                if len(parts) == 2:
                    commit_hash, commit_msg = parts
                    # Truncate long messages
                    display_msg = commit_msg[:50] + "..." if len(commit_msg) > 50 else commit_msg
                    self.last_commit_row.set_subtitle(f"{commit_hash}: {display_msg}")
                    
                    # Check if we're ahead of remote (commit can be undone)
                    can_undo = self._check_can_undo_commit(current_branch)
                    self.undo_button.set_visible(can_undo)
                else:
                    self.last_commit_row.set_subtitle(_("No commits"))
                    self.undo_button.set_visible(False)
            else:
                self.last_commit_row.set_subtitle(_("No commits"))
                self.undo_button.set_visible(False)
        except Exception:
            self.last_commit_row.set_subtitle(_("Unknown"))
            self.undo_button.set_visible(False)
        
        # Update commit button state
        self.update_commit_button_state()
    
    def _check_can_undo_commit(self, branch):
        """Check if the last commit can be undone (not pushed yet)"""
        import subprocess
        try:
            # Check if local is ahead of remote
            result = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                ahead_count = int(result.stdout.strip())
                return ahead_count > 0
            return False
        except Exception:
            return False
    
    def _select_commit_type_row(self, row):
        """Select a commit type row and update visuals"""
        # Hide all checkmarks first
        child = self.commit_type_expander.get_first_child()
        while child:
            if hasattr(child, 'check_icon'):
                child.check_icon.set_visible(False)
            child = child.get_next_sibling()
        
        # Show checkmark on selected
        if hasattr(row, 'check_icon'):
            row.check_icon.set_visible(True)
        
        # Update selected values
        self.selected_commit_type = row.commit_type
        self.selected_emoji = row.emoji
        
        # Update expander subtitle to show selection
        self.commit_type_expander.set_subtitle(f"{row.emoji} {row.commit_type}")
        
        # Collapse expander after selection
        self.commit_type_expander.set_expanded(False)
        
        # Update message entry title
        if hasattr(self, 'message_entry') and self.message_entry is not None:
            if row.commit_type == "custom":
                self.message_entry.set_title(_("Custom message"))
            else:
                self.message_entry.set_title(_("Description for {0}").format(row.commit_type))
        
        self.update_commit_button_state()
    
    def on_commit_type_row_activated(self, row):
        """Handle commit type row activation"""
        self._select_commit_type_row(row)
    
    def on_message_changed(self, entry):
        """Handle message entry changes"""
        self.update_commit_button_state()
    
    def update_commit_button_state(self):
        """Update commit button sensitivity"""
        # Check if we have all necessary components
        if not hasattr(self, 'message_entry') or not hasattr(self, 'commit_button'):
            return
            
        has_changes = GitUtils.has_changes()
        has_message = bool(self.message_entry.get_text().strip()) if self.message_entry else False
        has_type = self.selected_commit_type is not None
        
        self.commit_button.set_sensitive(has_changes and has_message and has_type)
    
    def on_pull_clicked(self, button):
        """Handle pull button click"""
        self.emit('push-requested')  # Reuse signal for pull
        self.refresh_status()
    
    def on_commit_clicked(self, widget):
        """Handle commit button click"""
        message = self.message_entry.get_text().strip()
        if not message:
            return
        
        # Format message based on commit type
        if self.selected_commit_type == "custom":
            formatted_message = message
        else:
            formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {message}"
        
        self.emit('commit-requested', formatted_message)
        
        # Clear form after commit
        self.message_entry.set_text("")
        self.refresh_status()
    
    def on_undo_clicked(self, button):
        """Handle undo last commit button click with confirmation"""
        # Show confirmation dialog
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Undo Last Commit?"),
            _("This will undo your last commit but keep all changes in your working directory.\n\nYou can then modify files and commit again.")
        )
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("undo", _("Undo Commit"))
        dialog.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "undo":
                self.emit('undo-commit-requested')
                self.refresh_status()
            dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()