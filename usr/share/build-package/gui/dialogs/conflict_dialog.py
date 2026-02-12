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
import os

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

        # Show diff button (compare side-by-side)
        diff_button = Gtk.Button()
        diff_button.set_icon_name("view-dual-symbolic")
        diff_button.set_tooltip_text(_("Compare versions side-by-side"))
        diff_button.add_css_class("flat")
        diff_button.connect('clicked', lambda b: self.emit('show-diff'))
        button_box.append(diff_button)

        # Edit manually button
        edit_button = Gtk.Button()
        edit_button.set_icon_name("document-edit-symbolic")
        edit_button.set_tooltip_text(_("Edit file manually"))
        edit_button.add_css_class("flat")
        edit_button.connect('clicked', lambda b: self.emit('edit-file'))
        button_box.append(edit_button)

        self.add_suffix(button_box)

    def mark_resolved(self):
        """Mark file as resolved"""
        self.status_icon.set_from_icon_name("emblem-ok-symbolic")
        self.add_css_class("success")

    # Signals
    __gsignals__ = {
        'action-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'show-diff': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'edit-file': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }


class ConflictDialog(Adw.Window):
    """Visual dialog for resolving conflicts"""

    __gsignals__ = {
        'conflicts-resolved': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # success
    }

    def __init__(self, parent, conflict_files, repo_root=None):
        super().__init__(
            transient_for=parent,
            modal=True
        )

        self.conflict_files = conflict_files
        self.resolutions = {}  # filepath -> action
        self.resolved_count = 0
        self.repo_root = repo_root  # Git repo root for subprocess cwd

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
            row.connect('edit-file', self.on_edit_file)
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

    def on_edit_file(self, row):
        """Open file in external editor for manual editing"""
        import os
        filepath = row.filepath
        
        # Try different editors in order of preference
        editors = [
            # GUI editors
            'code',      # VS Code
            'codium',    # VSCodium  
            'kate',      # KDE Kate
            'gedit',     # GNOME Gedit
            'xed',       # Linux Mint Xed
            'pluma',     # MATE Pluma
            'mousepad',  # Xfce Mousepad
            'leafpad',   # Lightweight
            # Fallback to xdg-open (system default)
            'xdg-open',
        ]
        
        editor_found = False
        for editor in editors:
            try:
                # Check if editor exists
                result = subprocess.run(
                    ['which', editor],
                    capture_output=True,
                    check=False,
                    cwd=self.repo_root
                )
                if result.returncode == 0:
                    # Editor found, open file
                    subprocess.Popen(
                        [editor, filepath],
                        start_new_session=True
                    )
                    editor_found = True
                    
                    # Show toast informing user
                    toast = Adw.Toast.new(
                        _("File opened in {0}. After editing, click 'Mark as Edited' to continue.").format(editor)
                    )
                    toast.set_timeout(5)
                    if hasattr(self, 'toast_overlay'):
                        self.toast_overlay.add_toast(toast)
                    
                    # Mark as "manual" resolution
                    self.resolutions[row.filepath] = 'manual'
                    row.mark_resolved()
                    
                    # Update button state
                    self.resolved_count = len(self.resolutions)
                    self.apply_button.set_sensitive(self.resolved_count == len(self.conflict_files))
                    
                    # Update status
                    self.status_banner.set_title(
                        _("Resolved {0} of {1} conflicts (editing manually)").format(
                            self.resolved_count, len(self.conflict_files)
                        )
                    )
                    break
                    
            except Exception:
                continue
        
        if not editor_found:
            # Fallback - show message
            dialog = Adw.MessageDialog.new(
                self,
                _("No Editor Found"),
                _("Could not find a text editor. Please edit the file manually:\n\n{0}").format(filepath)
            )
            dialog.add_response("ok", _("OK"))
            dialog.present()

    def show_diff_dialog(self, filepath):
        """Show side-by-side diff dialog with colors (MELD-style)"""
        # Get both versions from git
        try:
            # Get "ours" version (local/current branch)
            ours_result = subprocess.run(
                ["git", "show", f":2:{filepath}"],
                capture_output=True,
                check=False,
                cwd=self.repo_root
            )
            
            # Get "theirs" version (remote/incoming)
            theirs_result = subprocess.run(
                ["git", "show", f":3:{filepath}"],
                capture_output=True,
                check=False,
                cwd=self.repo_root
            )
            
            # Try to decode as UTF-8, fallback to latin-1
            try:
                ours_content = ours_result.stdout.decode('utf-8') if ours_result.stdout else ""
            except UnicodeDecodeError:
                ours_content = ours_result.stdout.decode('latin-1', errors='replace') if ours_result.stdout else ""
            
            try:
                theirs_content = theirs_result.stdout.decode('utf-8') if theirs_result.stdout else ""
            except UnicodeDecodeError:
                theirs_content = theirs_result.stdout.decode('latin-1', errors='replace') if theirs_result.stdout else ""
            
        except Exception as e:
            ours_content = _("Error reading local version: {0}").format(str(e))
            theirs_content = _("Error reading remote version: {0}").format(str(e))
        
        # Create diff dialog - larger and maximizable
        dialog = Adw.Window(
            transient_for=self,
            modal=True,
            title=_("Compare: {0}").format(filepath)
        )
        dialog.set_default_size(1200, 700)
        
        # Make it resizable
        dialog.set_resizable(True)
        
        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)
        
        # Header bar with maximize button
        header = Adw.HeaderBar()
        
        # Maximize button
        maximize_button = Gtk.Button()
        maximize_button.set_icon_name("view-fullscreen-symbolic")
        maximize_button.set_tooltip_text(_("Maximize"))
        maximize_button.connect('clicked', lambda b: dialog.maximize() if not dialog.is_maximized() else dialog.unmaximize())
        header.pack_end(maximize_button)
        
        main_box.append(header)
        
        # Info bar
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        info_box.set_halign(Gtk.Align.CENTER)
        info_box.set_margin_top(8)
        info_box.set_margin_bottom(8)
        
        local_label = Gtk.Label()
        local_label.set_markup(_("<span foreground='#3584e4' weight='bold'>◀ LOCAL (Your Version)</span>"))
        info_box.append(local_label)
        
        vs_label = Gtk.Label()
        vs_label.set_markup("<span weight='bold'>VS</span>")
        info_box.append(vs_label)
        
        remote_label = Gtk.Label()
        remote_label.set_markup(_("<span foreground='#2ec27e' weight='bold'>REMOTE (Server) ▶</span>"))
        info_box.append(remote_label)
        
        main_box.append(info_box)
        
        # Side-by-side paned container
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_wide_handle(True)
        
        # Left side - LOCAL version (ours)
        left_frame = Gtk.Frame()
        left_frame.add_css_class("view")
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        left_header = Gtk.Label()
        left_header.set_markup(_("<span foreground='#3584e4' weight='bold'>📁 LOCAL VERSION</span>"))
        left_header.set_margin_top(8)
        left_header.set_margin_bottom(4)
        left_box.append(left_header)
        
        left_scrolled = Gtk.ScrolledWindow()
        left_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scrolled.set_vexpand(True)
        
        left_text = Gtk.TextView()
        left_text.set_editable(False)
        left_text.set_monospace(True)
        left_text.set_wrap_mode(Gtk.WrapMode.NONE)
        left_text.set_left_margin(8)
        left_text.set_right_margin(8)
        left_text.set_top_margin(8)
        left_text.set_bottom_margin(8)
        
        # Apply syntax highlighting with colors
        self._apply_diff_highlighting(left_text, ours_content, is_local=True)
        
        left_scrolled.set_child(left_text)
        left_box.append(left_scrolled)
        left_frame.set_child(left_box)
        
        # Right side - REMOTE version (theirs)
        right_frame = Gtk.Frame()
        right_frame.add_css_class("view")
        
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        right_header = Gtk.Label()
        right_header.set_markup(_("<span foreground='#2ec27e' weight='bold'>☁️ REMOTE VERSION</span>"))
        right_header.set_margin_top(8)
        right_header.set_margin_bottom(4)
        right_box.append(right_header)
        
        right_scrolled = Gtk.ScrolledWindow()
        right_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        right_scrolled.set_vexpand(True)
        
        right_text = Gtk.TextView()
        right_text.set_editable(False)
        right_text.set_monospace(True)
        right_text.set_wrap_mode(Gtk.WrapMode.NONE)
        right_text.set_left_margin(8)
        right_text.set_right_margin(8)
        right_text.set_top_margin(8)
        right_text.set_bottom_margin(8)
        
        # Apply syntax highlighting with colors
        self._apply_diff_highlighting(right_text, theirs_content, is_local=False)
        
        right_scrolled.set_child(right_text)
        right_box.append(right_scrolled)
        right_frame.set_child(right_box)
        
        # Sync scrolling between both views
        left_vadj = left_scrolled.get_vadjustment()
        right_vadj = right_scrolled.get_vadjustment()
        
        def sync_scroll_left(adj):
            right_vadj.set_value(adj.get_value())
        
        def sync_scroll_right(adj):
            left_vadj.set_value(adj.get_value())
        
        left_vadj.connect('value-changed', sync_scroll_left)
        right_vadj.connect('value-changed', sync_scroll_right)
        
        paned.set_start_child(left_frame)
        paned.set_end_child(right_frame)
        paned.set_position(550)  # Start position
        
        main_box.append(paned)
        
        # Bottom action bar with choice buttons
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        action_bar.set_halign(Gtk.Align.CENTER)
        action_bar.set_margin_top(12)
        action_bar.set_margin_bottom(12)
        action_bar.set_margin_start(12)
        action_bar.set_margin_end(12)
        
        # Use Local button
        use_local_btn = Gtk.Button()
        use_local_btn.set_label(_("✓ Use LOCAL Version"))
        use_local_btn.add_css_class("suggested-action")
        use_local_btn.set_tooltip_text(_("Keep your local changes"))
        
        def on_use_local(btn):
            self._apply_choice_from_diff(filepath, 'ours')
            dialog.close()
        
        use_local_btn.connect('clicked', on_use_local)
        action_bar.append(use_local_btn)
        
        # Close without choosing
        close_btn = Gtk.Button()
        close_btn.set_label(_("Close"))
        close_btn.connect('clicked', lambda b: dialog.close())
        action_bar.append(close_btn)
        
        # Use Remote button
        use_remote_btn = Gtk.Button()
        use_remote_btn.set_label(_("✓ Use REMOTE Version"))
        use_remote_btn.add_css_class("accent")
        use_remote_btn.set_tooltip_text(_("Accept the remote server version"))
        
        def on_use_remote(btn):
            self._apply_choice_from_diff(filepath, 'theirs')
            dialog.close()
        
        use_remote_btn.connect('clicked', on_use_remote)
        action_bar.append(use_remote_btn)
        
        main_box.append(action_bar)
        
        dialog.present()
    
    def _apply_diff_highlighting(self, text_view, content, is_local=True):
        """Apply syntax highlighting with colors to text view"""
        buffer = text_view.get_buffer()
        
        # Create tags for highlighting
        tag_table = buffer.get_tag_table()
        
        # Create color tags if they don't exist
        comment_tag = Gtk.TextTag.new("comment")
        comment_tag.set_property("foreground", "#8b949e")  # Gray for comments
        tag_table.add(comment_tag)
        
        keyword_tag = Gtk.TextTag.new("keyword")
        keyword_tag.set_property("foreground", "#ff7b72")  # Red for keywords
        tag_table.add(keyword_tag)
        
        string_tag = Gtk.TextTag.new("string")
        string_tag.set_property("foreground", "#a5d6ff")  # Blue for strings
        tag_table.add(string_tag)
        
        number_tag = Gtk.TextTag.new("number")
        number_tag.set_property("foreground", "#79c0ff")  # Light blue for numbers
        tag_table.add(number_tag)
        
        # Background color based on side
        if is_local:
            bg_tag = Gtk.TextTag.new("bg")
            bg_tag.set_property("background", "#1a2332")  # Dark blue tint
        else:
            bg_tag = Gtk.TextTag.new("bg")
            bg_tag.set_property("background", "#1a3320")  # Dark green tint
        tag_table.add(bg_tag)
        
        # Set the text
        buffer.set_text(content)
        
        # Apply background to all text
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        buffer.apply_tag_by_name("bg", start, end)
        
        # Apply simple syntax highlighting
        lines = content.split('\n')
        offset = 0
        
        for line in lines:
            line_start = buffer.get_iter_at_offset(offset)
            line_end = buffer.get_iter_at_offset(offset + len(line))
            
            # Comments (# or //)
            if line.strip().startswith('#') or line.strip().startswith('//'):
                buffer.apply_tag_by_name("comment", line_start, line_end)
            
            offset += len(line) + 1  # +1 for newline
    
    def _iter_conflict_rows(self):
        """Iterate over ConflictFileRow children in the ListBox (GTK4 compatible)"""
        idx = 0
        while True:
            row = self.conflicts_list.get_row_at_index(idx)
            if row is None:
                break
            if isinstance(row, ConflictFileRow):
                yield row
            idx += 1

    def _apply_choice_from_diff(self, filepath, action):
        """Apply choice made from diff dialog"""
        for child in self._iter_conflict_rows():
            if child.filepath == filepath:
                self.resolutions[filepath] = action
                child.mark_resolved()

                # Update button state
                self.resolved_count = len(self.resolutions)
                self.apply_button.set_sensitive(self.resolved_count == len(self.conflict_files))

                # Update status
                self.status_banner.set_title(
                    _("Resolved {0} of {1} conflicts").format(
                        self.resolved_count, len(self.conflict_files)
                    )
                )
                break

    def on_auto_ours_clicked(self, button):
        """Apply 'ours' to all unresolved conflicts"""
        for child in self._iter_conflict_rows():
            if child.filepath not in self.resolutions:
                self.resolutions[child.filepath] = 'ours'
                child.mark_resolved()

        self.resolved_count = len(self.resolutions)
        self.apply_button.set_sensitive(True)
        self.status_banner.set_title(_("All conflicts resolved (kept local versions)"))

    def on_auto_theirs_clicked(self, button):
        """Apply 'theirs' to all unresolved conflicts"""
        for child in self._iter_conflict_rows():
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
                    # Check if file exists - files resolved with 'git rm' are already staged
                    abs_filepath = os.path.join(self.repo_root, filepath) if self.repo_root else filepath
                    if not os.path.exists(abs_filepath):
                        continue
                    subprocess.run(
                        ["git", "add", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root
                    )
                except Exception:
                    success = False

        self.emit('conflicts-resolved', success)
        self.close()

    def _get_conflict_type(self, filepath):
        """
        Detect the type of conflict for a file.

        Returns a dict with:
            'ours_exists': bool - whether 'ours' (stage 2) version exists
            'theirs_exists': bool - whether 'theirs' (stage 3) version exists
        """
        try:
            result = subprocess.run(
                ["git", "ls-files", "-u", "--", filepath],
                capture_output=True, text=True, check=False,
                cwd=self.repo_root
            )
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            stages = set()
            for line in lines:
                parts = line.split('\t')[0].split()  # mode hash stage
                if len(parts) >= 3:
                    stages.add(int(parts[2]))

            return {
                'ours_exists': 2 in stages,
                'theirs_exists': 3 in stages
            }
        except Exception:
            return {'ours_exists': True, 'theirs_exists': True}

    def apply_resolution(self, filepath, action):
        """Apply resolution for a file"""
        try:
            if action == 'ours':
                conflict_info = self._get_conflict_type(filepath)
                if not conflict_info['ours_exists']:
                    # Our side deleted the file - remove it
                    subprocess.run(
                        ["git", "rm", "-f", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root
                    )
                else:
                    # Keep local version
                    subprocess.run(
                        ["git", "checkout", "--ours", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root
                    )
            elif action == 'theirs':
                conflict_info = self._get_conflict_type(filepath)
                if not conflict_info['theirs_exists']:
                    # Remote side deleted the file - remove it
                    subprocess.run(
                        ["git", "rm", "-f", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root
                    )
                else:
                    # Accept remote version
                    subprocess.run(
                        ["git", "checkout", "--theirs", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root
                    )
            elif action == 'manual':
                # User edited the file manually
                # Just verify it doesn't have conflict markers
                try:
                    abs_path = os.path.join(self.repo_root, filepath) if self.repo_root else filepath
                    with open(abs_path, 'r', errors='replace') as f:
                        content = f.read()
                        if '<<<<<<<' in content or '=======' in content or '>>>>>>>' in content:
                            # Still has conflict markers - warn but continue
                            print(_("Warning: {0} may still have conflict markers").format(filepath))
                except Exception:
                    pass
                # File was edited, just return True
                return True
            elif action == 'both':
                # Keep both versions by creating .ours and .theirs files
                abs_path = os.path.join(self.repo_root, filepath) if self.repo_root else filepath
                ours_file = f"{abs_path}.ours"
                theirs_file = f"{abs_path}.theirs"

                # Copy current conflicted file as base
                import shutil
                shutil.copy(abs_path, ours_file)
                shutil.copy(abs_path, theirs_file)

                # Checkout each version to respective file
                subprocess.run(
                    ["git", "checkout", "--ours", ours_file],
                    check=False,
                    capture_output=True,
                    cwd=self.repo_root
                )
                subprocess.run(
                    ["git", "checkout", "--theirs", theirs_file],
                    check=False,
                    capture_output=True,
                    cwd=self.repo_root
                )

                # Keep ours for the original file
                subprocess.run(
                    ["git", "checkout", "--ours", filepath],
                    check=True,
                    capture_output=True,
                    cwd=self.repo_root
                )

            return True

        except Exception as e:
            print(_("Error resolving {0}: {1}").format(filepath, e))
            return False
