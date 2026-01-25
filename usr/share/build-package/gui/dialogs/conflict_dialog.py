#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/conflict_dialog.py - Visual conflict resolution dialog
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
import subprocess

class ConflictFileRow(Adw.ActionRow):
    """Row for a single conflicted file"""

    __gtype_name__ = 'ConflictFileRow'

    def __init__(self, filepath):
        super().__init__()

        self.filepath = filepath
        self.set_title(filepath)

        # Status icon
        self.status_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self.add_prefix(self.status_icon)

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Keep ours button
        ours_button = Gtk.Button()
        ours_button.set_label(_("Keep Local"))
        ours_button.set_tooltip_text(_("Keep local version"))
        ours_button.add_css_class("flat")
        ours_button.connect('clicked', lambda b: self.emit('action-selected', 'ours'))
        button_box.append(ours_button)

        # Keep theirs button
        theirs_button = Gtk.Button()
        theirs_button.set_label(_("Accept Remote"))
        theirs_button.set_tooltip_text(_("Accept remote version"))
        theirs_button.add_css_class("flat")
        theirs_button.connect('clicked', lambda b: self.emit('action-selected', 'theirs'))
        button_box.append(theirs_button)

        # Keep both button
        both_button = Gtk.Button()
        both_button.set_label(_("Keep Both"))
        both_button.set_tooltip_text(_("Keep both versions"))
        both_button.add_css_class("flat")
        both_button.connect('clicked', lambda b: self.emit('action-selected', 'both'))
        button_box.append(both_button)

        # Show diff button
        diff_button = Gtk.Button()
        diff_button.set_icon_name("document-properties-symbolic")
        diff_button.set_tooltip_text(_("Show differences"))
        diff_button.add_css_class("flat")
        diff_button.connect('clicked', lambda b: self.emit('show-diff'))
        button_box.append(diff_button)

        self.add_suffix(button_box)

    def mark_resolved(self):
        """Mark file as resolved"""
        self.status_icon.set_from_icon_name("emblem-ok-symbolic")
        self.add_css_class("success")

    # Signals
    __gsignals__ = {
        'action-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'show-diff': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }


class ConflictDialog(Adw.Window):
    """Visual dialog for resolving conflicts"""

    __gsignals__ = {
        'conflicts-resolved': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # success
    }

    def __init__(self, parent, conflict_files):
        super().__init__(
            transient_for=parent,
            modal=True
        )

        self.conflict_files = conflict_files
        self.resolutions = {}  # filepath -> action
        self.resolved_count = 0

        self.set_title(_("Resolve Conflicts"))
        self.set_default_size(800, 600)

        self.create_ui()

    def create_ui(self):
        """Create conflict resolution UI"""

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)

        # Toolbar view
        toolbar_view = Adw.ToolbarView()
        toolbar_view.set_vexpand(True)
        main_box.append(toolbar_view)

        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        toolbar_view.set_content(content_box)

        # Status banner
        self.status_banner = Adw.Banner()
        self.status_banner.set_title(
            _("Found {0} conflicted files").format(len(self.conflict_files))
        )
        self.status_banner.set_revealed(True)
        content_box.append(self.status_banner)

        # Strategy buttons group
        strategy_group = Adw.PreferencesGroup()
        strategy_group.set_title(_("Quick Actions"))
        strategy_group.set_description(_("Apply to all remaining conflicts"))

        strategy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        strategy_box.set_halign(Gtk.Align.CENTER)
        strategy_box.set_margin_top(6)
        strategy_box.set_margin_bottom(6)

        # Auto-ours button
        auto_ours_button = Gtk.Button()
        auto_ours_button.set_label(_("Keep All Local"))
        auto_ours_button.connect('clicked', self.on_auto_ours_clicked)
        strategy_box.append(auto_ours_button)

        # Auto-theirs button
        auto_theirs_button = Gtk.Button()
        auto_theirs_button.set_label(_("Accept All Remote"))
        auto_theirs_button.connect('clicked', self.on_auto_theirs_clicked)
        strategy_box.append(auto_theirs_button)

        strategy_group.add(strategy_box)
        content_box.append(strategy_group)

        # Conflicts list
        conflicts_group = Adw.PreferencesGroup()
        conflicts_group.set_title(_("Conflicted Files"))

        # Scrolled window for conflicts
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_size_request(-1, 300)

        # List box
        self.conflicts_list = Gtk.ListBox()
        self.conflicts_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.conflicts_list.add_css_class("boxed-list")
        scrolled.set_child(self.conflicts_list)

        # Add conflict rows
        for filepath in self.conflict_files:
            row = ConflictFileRow(filepath)
            row.connect('action-selected', self.on_file_action_selected)
            row.connect('show-diff', self.on_show_diff)
            self.conflicts_list.append(row)

        conflicts_group.add(scrolled)
        content_box.append(conflicts_group)

        # Bottom bar with actions
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom_bar.set_halign(Gtk.Align.END)
        toolbar_view.add_bottom_bar(bottom_bar)

        # Cancel button
        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Cancel"))
        cancel_button.connect('clicked', self.on_cancel_clicked)
        bottom_bar.append(cancel_button)

        # Apply button
        self.apply_button = Gtk.Button()
        self.apply_button.set_label(_("Apply Resolutions"))
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_sensitive(False)
        self.apply_button.connect('clicked', self.on_apply_clicked)
        bottom_bar.append(self.apply_button)

    def on_file_action_selected(self, row, action):
        """Handle action selection for a file"""
        self.resolutions[row.filepath] = action
        row.mark_resolved()

        # Update button state
        self.resolved_count = len(self.resolutions)
        self.apply_button.set_sensitive(self.resolved_count == len(self.conflict_files))

        # Update status
        self.status_banner.set_title(
            _("Resolved {0} of {1} conflicts").format(
                self.resolved_count, len(self.conflict_files)
            )
        )

    def on_show_diff(self, row):
        """Show diff for a file"""
        self.show_diff_dialog(row.filepath)

    def show_diff_dialog(self, filepath):
        """Show diff in a dialog"""
        # Get diff
        try:
            result = subprocess.run(
                ["git", "diff", "--", filepath],
                capture_output=True,
                text=True,
                check=False
            )
            diff_output = result.stdout

            if not diff_output:
                diff_output = _("No diff available")

        except Exception as e:
            diff_output = _("Error getting diff: {0}").format(str(e))

        # Create diff dialog
        dialog = Adw.Window(
            transient_for=self,
            modal=True,
            title=_("Diff: {0}").format(filepath)
        )
        dialog.set_default_size(700, 500)

        # Content
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(box)

        # Header
        header = Adw.HeaderBar()
        box.append(header)

        # Scrolled window with text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        text_view.get_buffer().set_text(diff_output)

        # Add some padding
        text_view.set_left_margin(12)
        text_view.set_right_margin(12)
        text_view.set_top_margin(12)
        text_view.set_bottom_margin(12)

        scrolled.set_child(text_view)
        box.append(scrolled)

        dialog.present()

    def on_auto_ours_clicked(self, button):
        """Apply 'ours' to all unresolved conflicts"""
        for child in list(self.conflicts_list):
            if isinstance(child, ConflictFileRow):
                if child.filepath not in self.resolutions:
                    self.resolutions[child.filepath] = 'ours'
                    child.mark_resolved()

        self.resolved_count = len(self.resolutions)
        self.apply_button.set_sensitive(True)
        self.status_banner.set_title(_("All conflicts resolved (kept local versions)"))

    def on_auto_theirs_clicked(self, button):
        """Apply 'theirs' to all unresolved conflicts"""
        for child in list(self.conflicts_list):
            if isinstance(child, ConflictFileRow):
                if child.filepath not in self.resolutions:
                    self.resolutions[child.filepath] = 'theirs'
                    child.mark_resolved()

        self.resolved_count = len(self.resolutions)
        self.apply_button.set_sensitive(True)
        self.status_banner.set_title(_("All conflicts resolved (accepted remote versions)"))

    def on_cancel_clicked(self, button):
        """Handle cancel"""
        self.emit('conflicts-resolved', False)
        self.close()

    def on_apply_clicked(self, button):
        """Apply all resolutions"""
        # Apply each resolution
        success = True
        for filepath, action in self.resolutions.items():
            if not self.apply_resolution(filepath, action):
                success = False
                break

        if success:
            # Mark all as resolved in git
            for filepath in self.resolutions.keys():
                try:
                    subprocess.run(
                        ["git", "add", filepath],
                        check=True,
                        capture_output=True
                    )
                except:
                    success = False

        self.emit('conflicts-resolved', success)
        self.close()

    def apply_resolution(self, filepath, action):
        """Apply resolution for a file"""
        try:
            if action == 'ours':
                # Keep local version
                subprocess.run(
                    ["git", "checkout", "--ours", filepath],
                    check=True,
                    capture_output=True
                )
            elif action == 'theirs':
                # Accept remote version
                subprocess.run(
                    ["git", "checkout", "--theirs", filepath],
                    check=True,
                    capture_output=True
                )
            elif action == 'both':
                # Keep both versions by creating .ours and .theirs files
                ours_file = f"{filepath}.ours"
                theirs_file = f"{filepath}.theirs"

                # Copy current conflicted file as base
                import shutil
                shutil.copy(filepath, ours_file)
                shutil.copy(filepath, theirs_file)

                # Checkout each version to respective file
                subprocess.run(
                    ["git", "checkout", "--ours", ours_file],
                    check=False,
                    capture_output=True
                )
                subprocess.run(
                    ["git", "checkout", "--theirs", theirs_file],
                    check=False,
                    capture_output=True
                )

                # Keep ours for the original file
                subprocess.run(
                    ["git", "checkout", "--ours", filepath],
                    check=True,
                    capture_output=True
                )

            return True

        except Exception as e:
            print(f"Error resolving {filepath}: {e}")
            return False
