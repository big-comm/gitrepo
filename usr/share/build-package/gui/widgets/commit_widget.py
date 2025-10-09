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
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        self.build_package = build_package
        self.selected_commit_type = None
        self.selected_emoji = None
        
        self.set_vexpand(True)
        self.set_valign(Gtk.Align.FILL)
        
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        self.create_ui()
        self.refresh_status()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Commit and Push"))
        title_label.add_css_class("title-2")
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
        
        self.append(status_group)
        
        # Commit type selection
        commit_type_group = Adw.PreferencesGroup()
        commit_type_group.set_title(_("Commit Type"))
        commit_type_group.set_description(_("Select the type of changes you are committing"))
        
        # Create list box for commit types
        self.commit_types_list = Gtk.ListBox()
        self.commit_types_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.commit_types_list.add_css_class("boxed-list")
        self.commit_types_list.connect('row-selected', self.on_commit_type_selected)
        
        # Add commit types
        commit_types = self.build_package.get_commit_types()
        for emoji, commit_type, description in commit_types:
            row = CommitTypeRow(emoji, commit_type, description)
            self.commit_types_list.append(row)

        commit_type_group.add(self.commit_types_list)
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
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)
        
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
        
        # Select first commit type by default (after all widgets are created)
        if self.commit_types_list.get_row_at_index(0):
            self.commit_types_list.select_row(self.commit_types_list.get_row_at_index(0))
    
    def refresh_status(self):
        """Refresh repository status"""
        # Check for changes
        if GitUtils.has_changes():
            self.changes_row.set_subtitle(_("Uncommitted changes present"))
            self.changes_row.add_suffix(Gtk.Image.new_from_icon_name("emblem-important-symbolic"))
            self.changes_row.add_css_class("warning")
        else:
            self.changes_row.set_subtitle(_("Working directory clean"))
            self.changes_row.add_suffix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
            self.changes_row.add_css_class("success")
        
        # Current branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            self.branch_row.set_subtitle(current_branch)
        else:
            self.branch_row.set_subtitle(_("Unknown"))
        
        # Update commit button state
        self.update_commit_button_state()
    
    def on_commit_type_selected(self, list_box, row):
        """Handle commit type selection"""
        if row:
            self.selected_commit_type = row.commit_type
            self.selected_emoji = row.emoji
            
            # Update placeholder text (only if message_entry exists)
            if hasattr(self, 'message_entry') and self.message_entry is not None:
                if self.selected_commit_type == "custom":
                    self.message_entry.set_text("")
                    self.message_entry.set_title(_("Custom message"))
                else:
                    self.message_entry.set_text("")
                    self.message_entry.set_title(_("Description for {0}").format(self.selected_commit_type))
            
            self.update_commit_button_state()
    
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