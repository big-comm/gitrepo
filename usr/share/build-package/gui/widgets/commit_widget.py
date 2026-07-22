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

from .ui_helpers import action_bar, action_button, git_status_icon, icon_tile, page_header

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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        self.build_package = build_package
        self.selected_commit_type = None
        self.selected_emoji = None

        self.set_valign(Gtk.Align.START)
        self.add_css_class("content-page")
        
        self.create_ui()
        self.refresh_status()
    
    def create_ui(self):
        """Create the widget UI"""
        
        self.append(page_header(
            _("Commit and Push"),
            _("Stage changes and push to your development branch"),
        ))
        
        # Status group
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Repository Status"))
        
        self.changes_row = Adw.ActionRow()
        self.changes_row.set_title(_("Working Directory"))
        self.changes_row.add_css_class("rich-row")
        self.changes_row.add_prefix(icon_tile("folder-symbolic", tone="success", size=20))
        status_group.add(self.changes_row)
        
        self.branch_row = Adw.ActionRow()
        self.branch_row.set_title(_("Current Branch"))
        self.branch_row.add_css_class("rich-row")
        self.branch_row.add_prefix(icon_tile("media-playlist-consecutive-symbolic", tone="accent", size=20))
        status_group.add(self.branch_row)
        
        # Last commit row (for undo functionality)
        self.last_commit_row = Adw.ActionRow()
        self.last_commit_row.set_title(_("Last Commit"))
        self.last_commit_row.set_subtitle(_("No commit info"))
        self.last_commit_row.add_css_class("rich-row")
        self.last_commit_row.add_prefix(icon_tile("document-open-recent-symbolic", tone="purple", size=20))
        
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

        # Changed files expander
        self.changed_files_expander = Adw.ExpanderRow()
        self.changed_files_expander.set_title(_("Changed Files"))
        self.changed_files_expander.set_subtitle(_("Click to view files"))
        self.changed_files_expander.set_visible(False)
        status_group.add(self.changed_files_expander)
        
        self.append(status_group)
        
        # Commit type selection
        commit_type_group = Adw.PreferencesGroup()
        commit_type_group.set_title(_("Commit Type"))
        
        # Get commit types
        self.commit_types = self.build_package.get_commit_types()

        self.commit_type_cards = []
        self.commit_type_flow = Gtk.FlowBox()
        self.commit_type_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.commit_type_flow.set_max_children_per_line(6)
        self.commit_type_flow.set_min_children_per_line(2)
        self.commit_type_flow.set_homogeneous(True)
        self.commit_type_flow.set_column_spacing(8)
        self.commit_type_flow.set_row_spacing(8)
        self.commit_type_flow.add_css_class("choice-grid")
        self.commit_type_flow.connect("selected-children-changed", self.on_commit_type_selected)

        for idx, (emoji, commit_type, description) in enumerate(self.commit_types):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class("choice-card")
            card.commit_type = commit_type
            card.emoji = emoji
            card.idx = idx

            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title_row.set_halign(Gtk.Align.FILL)

            check_icon = Gtk.Image.new_from_icon_name("media-record-symbolic")
            check_icon.set_pixel_size(14)
            check_icon.add_css_class("choice-dot")
            card.check_icon = check_icon
            title_row.append(check_icon)

            title_label = Gtk.Label(label=f"{emoji} {commit_type}")
            title_label.set_halign(Gtk.Align.START)
            title_label.set_xalign(0)
            title_label.add_css_class("heading")
            title_row.append(title_label)
            card.append(title_row)

            desc_label = Gtk.Label(label=description)
            desc_label.set_halign(Gtk.Align.START)
            desc_label.set_xalign(0)
            desc_label.set_wrap(True)
            desc_label.add_css_class("dim-label")
            card.append(desc_label)

            self.commit_type_cards.append(card)
            self.commit_type_flow.append(card)

        commit_type_group.add(self.commit_type_flow)
        self.append(commit_type_group)

        # Commit message entry - multiline support
        message_group = Adw.PreferencesGroup()
        message_group.set_title(_("Commit Message"))
        
        # Label for description
        message_label = Gtk.Label()
        message_label.set_text(_("Description (supports multiple lines)"))
        message_label.set_halign(Gtk.Align.START)
        message_label.add_css_class("dim-label")
        message_label.set_margin_start(6)
        message_label.set_margin_bottom(4)
        self.message_label = message_label
        
        # Frame for better visual separation
        message_frame = Gtk.Frame()
        message_frame.set_margin_start(6)
        message_frame.set_margin_end(6)
        message_frame.add_css_class("message-frame")
        
        # ScrolledWindow for multiline text
        message_scroll = Gtk.ScrolledWindow()
        message_scroll.set_min_content_height(150)
        message_scroll.set_max_content_height(220)
        message_scroll.set_vexpand(False)
        message_scroll.set_hexpand(True)
        
        # TextView for multiline commit message
        self.message_textview = Gtk.TextView()
        self.message_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.message_textview.set_left_margin(8)
        self.message_textview.set_right_margin(8)
        self.message_textview.set_top_margin(8)
        self.message_textview.set_bottom_margin(8)
        self.message_textview.get_buffer().connect('changed', self.on_message_changed)
        message_scroll.set_child(self.message_textview)
        
        message_frame.set_child(message_scroll)
        
        # Add to group using a vertical box
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        message_box.append(message_label)
        message_box.append(message_frame)
        message_box.set_margin_top(6)
        message_box.set_margin_bottom(6)
        
        self.append(message_box)
        
        # Actions
        actions_box = action_bar()
        
        # Pull button
        self.pull_button = action_button(_("Pull Latest"), "go-down-symbolic")
        self.pull_button.set_tooltip_text(_("Pull latest changes from remote"))
        self.pull_button.connect('clicked', self.on_pull_clicked)
        actions_box.append(self.pull_button)
        
        # Commit button
        self.commit_button = action_button(_("Commit and Push"), "go-up-symbolic", "suggested-action")
        self.commit_button.add_css_class("suggested-action")
        self.commit_button.connect('clicked', self.on_commit_clicked)
        self.commit_button.set_sensitive(False)
        actions_box.append(self.commit_button)
        
        self.append(actions_box)
        
        # Do NOT auto-select first type — user must choose actively
        # The expander starts with "error" CSS class as visual alert
    
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

            # Populate changed files list
            self._update_changed_files_list()
        else:
            self.changes_row.set_subtitle(_("Working directory clean"))
            self._status_suffix_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            self._status_suffix_icon.set_tooltip_text(_("No pending changes - working directory is clean"))
            self.changes_row.add_suffix(self._status_suffix_icon)
            self.changes_row.add_css_class("success")
            self.changed_files_expander.set_visible(False)
        
        # Current branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            self.branch_row.set_subtitle(current_branch)
        else:
            self.branch_row.set_subtitle(_("Unknown"))
        
        # Last commit info - check for empty repo first
        if not GitUtils.has_commits():
            self.last_commit_row.set_subtitle(_("No commits yet (this will be your first!)"))
            self.undo_button.set_visible(False)
        else:
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
        for card in self.commit_type_cards:
            card.remove_css_class("selected")
        
        row.add_css_class("selected")
        
        # Update selected values
        self.selected_commit_type = row.commit_type
        self.selected_emoji = row.emoji
        
        # Update message label title
        if hasattr(self, 'message_label') and self.message_label is not None:
            if row.commit_type == "custom":
                self.message_label.set_text(_("Custom message (supports multiple lines)"))
            else:
                self.message_label.set_text(_("Description for {0} (supports multiple lines)").format(row.commit_type))
        
        self.update_commit_button_state()
    
    def on_commit_type_row_activated(self, row):
        """Handle commit type row activation"""
        self._select_commit_type_row(row)

    def on_commit_type_selected(self, flow_box):
        """Handle commit type card selection."""
        selected = flow_box.get_selected_children()
        if not selected:
            return

        child = selected[0].get_child()
        if child and hasattr(child, "commit_type"):
            self._select_commit_type_row(child)
    
    def on_message_changed(self, entry):
        """Handle message entry changes"""
        self.update_commit_button_state()
    
    def update_commit_button_state(self):
        """Update commit button sensitivity"""
        # Check if we have all necessary components
        if not hasattr(self, 'message_textview') or not hasattr(self, 'commit_button'):
            return
            
        has_changes = GitUtils.has_changes()
        # Get text from TextView buffer
        buffer = self.message_textview.get_buffer()
        start, end = buffer.get_bounds()
        text = buffer.get_text(start, end, False)
        has_message = bool(text.strip())
        has_type = self.selected_commit_type is not None
        
        self.commit_button.set_sensitive(has_changes and has_message and has_type)
    
    def on_pull_clicked(self, button):
        """Handle pull button click"""
        self.emit('push-requested')  # Reuse signal for pull
        self.refresh_status()
    
    def on_commit_clicked(self, widget):
        """Handle commit button click"""
        # Get text from TextView buffer
        buffer = self.message_textview.get_buffer()
        start, end = buffer.get_bounds()
        message = buffer.get_text(start, end, False).strip()
        if not message:
            return
        
        # Format message based on commit type
        if self.selected_commit_type == "custom":
            formatted_message = message
        else:
            # For multiline messages, put type on first line
            if '\n' in message:
                lines = message.split('\n', 1)
                formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {lines[0]}\n\n{lines[1]}"
            else:
                formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {message}"
        
        self.emit('commit-requested', formatted_message)
        
        # Clear form after commit
        buffer.set_text("")
        self.refresh_status()
    
    def _update_changed_files_list(self):
        """Populate the changed files expander with current git status"""
        if not hasattr(self, "_changed_file_rows"):
            self._changed_file_rows = []
        for row in self._changed_file_rows:
            self.changed_files_expander.remove(row)
        self._changed_file_rows = []

        changed_files = GitUtils.get_changed_files()

        status_labels = {
            "M": _("Modified"),
            "A": _("Added"),
            "D": _("Deleted"),
            "R": _("Renamed"),
            "C": _("Copied"),
            "??": _("Untracked"),
            "AM": _("Added+Modified"),
            "MM": _("Modified (staged+unstaged)"),
        }

        for status, filepath in changed_files:
            row = Adw.ActionRow()
            row.set_title(filepath)
            label = status_labels.get(status, status)
            row.set_subtitle(label)
            row.set_activatable(True)
            row.connect("activated", self._show_file_diff, filepath)

            icon_name, tone = git_status_icon(status)
            row.add_prefix(icon_tile(icon_name, tone=tone, size=24))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.changed_files_expander.add_row(row)
            self._changed_file_rows.append(row)

        count = len(changed_files)
        self.changed_files_expander.set_title(
            _("{0} changed file(s)").format(count)
        )
        self.changed_files_expander.set_visible(count > 0)

    def _show_file_diff(self, _row, filepath):
        """Show all pending files and select the activated file."""
        from gui.dialogs.diff_viewer_dialog import DiffViewerDialog

        repo_path = self.build_package.repo_path
        dialog = DiffViewerDialog(
            self.get_root(),
            _("Pending Changes"),
            GitUtils.get_changed_files(repo_path),
            lambda path: GitUtils.get_worktree_file_diff(path, repo_path),
            initial_path=filepath,
        )
        dialog.present()

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
