# intentional-log: unresolved markers and resolution failures require operator action.
#
# gui/dialogs/conflict_dialog.py - Visual conflict resolution dialog
#

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk, Pango
from gitrepo.common.desktop_launch import open_path
from gitrepo.common.translation import _
from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git


def _core_resolver(repo_root):
    """Borrow the core resolver for its safe companion-file writer.

    The dialog owns the interaction; creating the files stays with the one
    implementation that refuses to overwrite or follow an existing name.
    """
    from gitrepo.build_package.core.conflict_resolver import ConflictResolver

    resolver = ConflictResolver(logger=None, menu_system=None)
    resolver.repo_root = repo_root
    return resolver


class ConflictFileRow(Adw.ActionRow):
    """Row for a single conflicted file with toggle selection"""

    __gtype_name__ = "ConflictFileRow"

    def __init__(self, filepath: str, local_side: str = "ours"):
        super().__init__()

        self.filepath = filepath
        self.local_side = local_side
        self.remote_side = "theirs" if local_side == "ours" else "ours"
        self._action_classes = {
            self.local_side: "conflict-local",
            self.remote_side: "conflict-remote",
            "both": "conflict-both",
        }
        self._action_semantics = {
            self.local_side: "local",
            self.remote_side: "remote",
            "both": "both",
        }
        self.current_action: str | None = None
        self.set_title(filepath)

        # Status icon
        self.status_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self.add_prefix(self.status_icon)

        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.ours_button = Gtk.Button(label=_("Keep Local"))
        self.ours_button.set_tooltip_text(_("Keep local version"))
        self.ours_button.add_css_class("flat")
        self.ours_button.connect("clicked", self._on_action_clicked, self.local_side)
        button_box.append(self.ours_button)

        self.theirs_button = Gtk.Button(label=_("Accept Remote"))
        self.theirs_button.set_tooltip_text(_("Accept remote version"))
        self.theirs_button.add_css_class("flat")
        self.theirs_button.connect("clicked", self._on_action_clicked, self.remote_side)
        button_box.append(self.theirs_button)

        self.both_button = Gtk.Button(label=_("Keep Both"))
        self.both_button.set_tooltip_text(_("Keep both versions"))
        self.both_button.add_css_class("flat")
        self.both_button.connect("clicked", self._on_action_clicked, "both")
        button_box.append(self.both_button)

        # Diff button
        diff_button = Gtk.Button()
        diff_button.set_icon_name("view-dual-symbolic")
        diff_button.set_tooltip_text(_("Compare versions side-by-side"))
        diff_button.add_css_class("flat")
        diff_button.connect("clicked", lambda b: self.emit("show-diff"))
        button_box.append(diff_button)

        # Edit button
        edit_button = Gtk.Button()
        edit_button.set_icon_name("document-edit-symbolic")
        edit_button.set_tooltip_text(_("Edit file manually"))
        edit_button.add_css_class("flat")
        edit_button.connect("clicked", lambda b: self.emit("edit-file"))
        button_box.append(edit_button)

        self.add_suffix(button_box)

        # Map action -> button for styling
        self._action_buttons = {
            self.local_side: self.ours_button,
            self.remote_side: self.theirs_button,
            "both": self.both_button,
        }

    def set_side_labels(self, keep_local: str, keep_remote: str) -> None:
        """Name each side after the branch it comes from (see set_branch_info)."""
        self.ours_button.set_label(keep_local)
        self.ours_button.set_tooltip_text(keep_local)
        self.theirs_button.set_label(keep_remote)
        self.theirs_button.set_tooltip_text(keep_remote)

    def _on_action_clicked(self, _button: Gtk.Button, action: str) -> None:
        """Toggle action selection: click to select, click again to deselect"""
        if self.current_action == action:
            # Deselect
            self._clear_visual()
            self.current_action = None
            self.emit("action-deselected", action)
        else:
            # Select (possibly replacing previous choice)
            self._clear_visual()
            self.current_action = action
            self._apply_visual(action)
            self.emit("action-selected", action)

    def _clear_visual(self) -> None:
        """Remove all action styling"""
        for cls in self._action_classes.values():
            self.remove_css_class(cls)
        for btn in self._action_buttons.values():
            btn.remove_css_class("conflict-btn-active-local")
            btn.remove_css_class("conflict-btn-active-remote")
            btn.remove_css_class("conflict-btn-active-both")
        self.remove_css_class("success")
        self.status_icon.set_from_icon_name("dialog-warning-symbolic")

    def _apply_visual(self, action: str) -> None:
        """Apply visual style for the selected action"""
        row_cls = self._action_classes.get(action)
        if row_cls:
            self.add_css_class(row_cls)

        btn = self._action_buttons.get(action)
        if btn:
            btn.add_css_class(f"conflict-btn-active-{self._action_semantics[action]}")

        self.status_icon.set_from_icon_name("emblem-ok-symbolic")

    def set_action(self, action: str) -> None:
        """Programmatically set the action (used by bulk operations and diff dialog)"""
        self._clear_visual()
        self.current_action = action
        if action in self._action_classes:
            self._apply_visual(action)
        else:
            # Generic resolved state (e.g. 'manual')
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")

    # Signals
    __gsignals__ = {
        "action-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "action-deselected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "show-diff": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "edit-file": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }


class ConflictDialog(Adw.Window):
    """Visual dialog for resolving conflicts"""

    __gsignals__ = {
        "conflicts-resolved": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # success
    }

    def __init__(self, parent, conflict_files, repo_root=None, local_side="ours"):
        super().__init__(transient_for=parent, modal=True)

        self.conflict_files = conflict_files
        self.resolutions = {}  # filepath -> action
        self.resolved_count = 0
        self.repo_root = repo_root  # Git repo root for subprocess cwd
        self.local_side = local_side
        self.remote_side = "theirs" if local_side == "ours" else "ours"

        self.set_title(_("Resolve Conflicts"))
        self.set_default_size(800, 600)

        self._setup_conflict_css()
        self.create_ui()

    def set_branch_info(self, local_branch: str, remote_branch: str) -> None:
        """Name both sides after the branches they come from.

        "Local" and "Remote" describe a fetch, and this dialog also resolves a
        stash transfer between two local branches, where neither side is remote
        and the version being called local is the work Git holds in stage three.
        Naming the branches removes the guesswork: one side is the work the user
        just wrote, the other is what the branch it is going to already had.
        """
        if not local_branch or not remote_branch:
            return
        self._local_branch = local_branch
        self._remote_branch = remote_branch

        keep_local = _("Use your work from {0}").format(local_branch)
        keep_remote = _("Keep {0} version").format(remote_branch)
        for button, label in (
            (getattr(self, "_auto_ours_button", None), _("Use all from {0}").format(local_branch)),
            (getattr(self, "_auto_theirs_button", None), _("Keep all from {0}").format(remote_branch)),
        ):
            if button is not None:
                button.set_label(label)

        for row in getattr(self, "_conflict_rows", []):
            if hasattr(row, "set_side_labels"):
                row.set_side_labels(keep_local, keep_remote)

    def _setup_conflict_css(self):
        """Register CSS for conflict row states"""
        from gi.repository import Gdk

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            /* Row backgrounds */
            row.conflict-local {
                background-color: alpha(@accent_bg_color, 0.15);
            }
            row.conflict-remote {
                background-color: alpha(@success_bg_color, 0.15);
            }
            row.conflict-both {
                background-color: alpha(@warning_bg_color, 0.15);
            }

            /* Active button highlights */
            .conflict-btn-active-local {
                background-color: @accent_bg_color;
                color: @accent_fg_color;
            }
            .conflict-btn-active-remote {
                background-color: @success_bg_color;
                color: @success_fg_color;
            }
            .conflict-btn-active-both {
                background-color: @warning_bg_color;
                color: @warning_fg_color;
            }
        """)

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def create_ui(self):
        """Create conflict resolution UI"""

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Custom header bar (flat - blends with background)
        header_bar = Adw.HeaderBar()
        header_bar.set_show_start_title_buttons(False)
        header_bar.set_show_end_title_buttons(False)
        header_bar.add_css_class("flat")

        # Title
        title_label = Gtk.Label(label=_("Resolve Conflicts"))
        title_label.add_css_class("heading")
        header_bar.set_title_widget(title_label)

        # Close button (rightmost - pack_end adds from right)
        close_button = Gtk.Button()
        close_button.set_icon_name("window-close-symbolic")
        close_button.set_tooltip_text(_("Close"))
        close_button.add_css_class("flat")
        close_button.connect("clicked", lambda b: self.close())
        header_bar.pack_end(close_button)

        # Maximize button (left of close)
        maximize_button = Gtk.Button()
        maximize_button.set_icon_name("view-fullscreen-symbolic")
        maximize_button.set_tooltip_text(_("Maximize"))
        maximize_button.add_css_class("flat")
        maximize_button.connect("clicked", self._on_maximize_clicked)
        header_bar.pack_end(maximize_button)
        self._maximize_button = maximize_button

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

        # Status label (subtle, centered)
        self.status_label = Gtk.Label()
        self.status_label.set_text(_("Found {0} conflicted files").format(len(self.conflict_files)))
        self.status_label.add_css_class("dim-label")
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.set_margin_top(4)
        self.status_label.set_margin_bottom(8)
        content_box.append(self.status_label)

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
        auto_ours_button.connect("clicked", self.on_auto_ours_clicked)
        strategy_box.append(auto_ours_button)
        self._auto_ours_button = auto_ours_button

        # Auto-theirs button
        auto_theirs_button = Gtk.Button()
        auto_theirs_button.set_label(_("Accept All Remote"))
        auto_theirs_button.connect("clicked", self.on_auto_theirs_clicked)
        strategy_box.append(auto_theirs_button)
        self._auto_theirs_button = auto_theirs_button

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
        self._conflict_rows = []
        for filepath in self.conflict_files:
            row = ConflictFileRow(filepath, self.local_side)
            row.connect("action-selected", self.on_file_action_selected)
            row.connect("action-deselected", self.on_file_action_deselected)
            row.connect("show-diff", self.on_show_diff)
            row.connect("edit-file", self.on_edit_file)
            self.conflicts_list.append(row)
            self._conflict_rows.append(row)

        conflicts_group.add(scrolled)
        content_box.append(conflicts_group)

        # Bottom bar with actions
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom_bar.set_halign(Gtk.Align.END)
        toolbar_view.add_bottom_bar(bottom_bar)

        # Cancel button
        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Cancel"))
        cancel_button.connect("clicked", self.on_cancel_clicked)
        bottom_bar.append(cancel_button)

        # Apply button
        self.apply_button = Gtk.Button()
        self.apply_button.set_label(_("Apply Resolutions"))
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_sensitive(False)
        self.apply_button.connect("clicked", self.on_apply_clicked)
        bottom_bar.append(self.apply_button)

    def _on_maximize_clicked(self, _button: Gtk.Button) -> None:
        """Toggle maximize state"""
        if self.is_maximized():
            self.unmaximize()
            self._maximize_button.set_icon_name("view-fullscreen-symbolic")
        else:
            self.maximize()
            self._maximize_button.set_icon_name("view-restore-symbolic")

    def on_file_action_selected(self, row, action):
        """Handle action selection for a file"""
        self.resolutions[row.filepath] = action
        self._update_status()

    def on_file_action_deselected(self, row, action):
        """Handle action deselection for a file"""
        self.resolutions.pop(row.filepath, None)
        self._update_status()

    def _update_status(self):
        """Recalculate resolved count and update UI"""
        self.resolved_count = len(self.resolutions)
        self.apply_button.set_sensitive(self.resolved_count == len(self.conflict_files))
        if self.resolved_count == 0:
            text = _("Found {0} conflicted files").format(len(self.conflict_files))
        else:
            text = _("Resolved {0} of {1} conflicts").format(self.resolved_count, len(self.conflict_files))
        self.status_label.set_text(text)

    def on_show_diff(self, row):
        """Show diff for a file"""
        self.show_diff_dialog(row.filepath)

    def _absolute_path(self, filepath: str) -> str:
        """Resolve a repository-relative path for the desktop to open."""
        if os.path.isabs(filepath) or not self.repo_root:
            return filepath
        return os.path.join(self.repo_root, filepath)

    def on_edit_file(self, row):
        """Open the conflicted file in the editor the desktop already chose.

        Guessing through a hardcoded list of editors overrides the user's own
        default and still fails silently when none of the guesses is installed.
        """
        open_path(self, self._absolute_path(row.filepath))

        # The row is marked so the choice is visible and Apply becomes usable,
        # but this is a claim, not a verified resolution: the file has not been
        # edited yet at this point. apply_resolution() re-reads it and refuses
        # while conflict markers remain, which is what keeps them out of the
        # commit. Say so on the row itself -- the toast this used to build was
        # posted to a self.toast_overlay that is never created, so it was never
        # shown, and the 'Mark as Edited' control it named does not exist.
        row.set_subtitle(_("Edited by hand — checked for conflict markers when you apply"))
        self.resolutions[row.filepath] = "manual"
        row.set_action("manual")
        self._update_status()

    def show_diff_dialog(self, filepath):
        """Show a theme-adaptive side-by-side diff dialog."""
        # Get both versions from git
        try:
            local_stage = "2" if self.local_side == "ours" else "3"
            remote_stage = "3" if self.local_side == "ours" else "2"
            local_result = subprocess.run_git(
                ["git", "show", f":{local_stage}:{filepath}"],
                capture_output=True,
                check=False,
                cwd=self.repo_root,
                intent="ordinary",
            )
            remote_result = subprocess.run_git(
                ["git", "show", f":{remote_stage}:{filepath}"],
                capture_output=True,
                check=False,
                cwd=self.repo_root,
                intent="ordinary",
            )

            # Try to decode as UTF-8, fallback to latin-1
            try:
                local_content = local_result.stdout.decode("utf-8") if local_result.stdout else ""
            except UnicodeDecodeError:
                local_content = local_result.stdout.decode("latin-1", errors="replace") if local_result.stdout else ""

            try:
                remote_content = remote_result.stdout.decode("utf-8") if remote_result.stdout else ""
            except UnicodeDecodeError:
                remote_content = (
                    remote_result.stdout.decode("latin-1", errors="replace") if remote_result.stdout else ""
                )

        except Exception as e:
            local_content = _("Error reading local version: {0}").format(str(e))
            remote_content = _("Error reading remote version: {0}").format(str(e))

        # Create diff dialog - larger and maximizable
        dialog = Adw.Window(transient_for=self, modal=True, title=_("Compare: {0}").format(filepath))
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
        maximize_button.connect(
            "clicked", lambda b: dialog.maximize() if not dialog.is_maximized() else dialog.unmaximize()
        )
        header.pack_end(maximize_button)

        main_box.append(header)

        # Info bar
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        info_box.set_halign(Gtk.Align.CENTER)
        info_box.set_margin_top(8)
        info_box.set_margin_bottom(8)

        local_label = Gtk.Label()
        local_label.set_text(_("◀ LOCAL (Your Version)"))
        local_label.add_css_class("heading")
        local_label.add_css_class("accent")
        info_box.append(local_label)

        vs_label = Gtk.Label()
        vs_label.set_text("VS")
        vs_label.add_css_class("heading")
        info_box.append(vs_label)

        remote_label = Gtk.Label()
        remote_label.set_text(_("REMOTE (Server) ▶"))
        remote_label.add_css_class("heading")
        remote_label.add_css_class("success")
        info_box.append(remote_label)

        main_box.append(info_box)

        # Side-by-side paned container
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_wide_handle(True)

        # Left side - the version presented as the user's local work
        left_frame = Gtk.Frame()
        left_frame.add_css_class("view")

        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        left_header = Gtk.Label()
        left_header.set_text(_("📁 LOCAL VERSION"))
        left_header.add_css_class("heading")
        left_header.add_css_class("accent")
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

        # Apply theme-independent syntax emphasis.
        self._apply_diff_highlighting(left_text, local_content, is_local=True)

        left_scrolled.set_child(left_text)
        left_box.append(left_scrolled)
        left_frame.set_child(left_box)

        # Right side - the other side of the conflict
        right_frame = Gtk.Frame()
        right_frame.add_css_class("view")

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        right_header = Gtk.Label()
        right_header.set_text(_("☁️ REMOTE VERSION"))
        right_header.add_css_class("heading")
        right_header.add_css_class("success")
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

        # Apply theme-independent syntax emphasis.
        self._apply_diff_highlighting(right_text, remote_content, is_local=False)

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

        left_vadj.connect("value-changed", sync_scroll_left)
        right_vadj.connect("value-changed", sync_scroll_right)

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
            self._apply_choice_from_diff(filepath, self.local_side)
            dialog.close()

        use_local_btn.connect("clicked", on_use_local)
        action_bar.append(use_local_btn)

        # Close without choosing
        close_btn = Gtk.Button()
        close_btn.set_label(_("Close"))
        close_btn.connect("clicked", lambda b: dialog.close())
        action_bar.append(close_btn)

        # Use Remote button
        use_remote_btn = Gtk.Button()
        use_remote_btn.set_label(_("✓ Use REMOTE Version"))
        use_remote_btn.add_css_class("accent")
        use_remote_btn.set_tooltip_text(_("Accept the remote server version"))

        def on_use_remote(btn):
            self._apply_choice_from_diff(filepath, self.remote_side)
            dialog.close()

        use_remote_btn.connect("clicked", on_use_remote)
        action_bar.append(use_remote_btn)

        main_box.append(action_bar)

        dialog.present()

    def _apply_diff_highlighting(self, text_view, content, is_local=True):
        """Apply theme-independent syntax emphasis to a diff pane."""
        text_view.add_css_class("local-diff" if is_local else "remote-diff")
        buffer = text_view.get_buffer()

        # Create tags for highlighting
        tag_table = buffer.get_tag_table()

        comment_tag = Gtk.TextTag.new("comment")
        comment_tag.set_property("style", Pango.Style.ITALIC)
        tag_table.add(comment_tag)

        keyword_tag = Gtk.TextTag.new("keyword")
        keyword_tag.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(keyword_tag)

        string_tag = Gtk.TextTag.new("string")
        string_tag.set_property("underline", Pango.Underline.SINGLE)
        tag_table.add(string_tag)

        number_tag = Gtk.TextTag.new("number")
        number_tag.set_property("weight", Pango.Weight.SEMIBOLD)
        tag_table.add(number_tag)

        # Set the text
        buffer.set_text(content)

        # Apply simple syntax highlighting
        lines = content.split("\n")
        offset = 0

        for line in lines:
            line_start = buffer.get_iter_at_offset(offset)
            line_end = buffer.get_iter_at_offset(offset + len(line))

            # Comments (# or //)
            if line.strip().startswith("#") or line.strip().startswith("//"):
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
                child.set_action(action)
                self._update_status()
                break

    def on_auto_ours_clicked(self, button):
        """Keep the semantic local side in all unresolved conflicts."""
        for child in self._iter_conflict_rows():
            if child.filepath not in self.resolutions:
                self.resolutions[child.filepath] = self.local_side
                child.set_action(self.local_side)

        self._update_status()
        self.status_label.set_text(_("All conflicts resolved (kept local versions)"))

    def on_auto_theirs_clicked(self, button):
        """Keep the semantic remote side in all unresolved conflicts."""
        for child in self._iter_conflict_rows():
            if child.filepath not in self.resolutions:
                self.resolutions[child.filepath] = self.remote_side
                child.set_action(self.remote_side)

        self._update_status()
        self.status_label.set_text(_("All conflicts resolved (accepted remote versions)"))

    def on_cancel_clicked(self, button):
        """Handle cancel"""
        self.emit("conflicts-resolved", False)
        self.close()

    def on_apply_clicked(self, button):
        """Apply all resolutions"""
        deletions = []
        for filepath, action in self.resolutions.items():
            conflict_info = self._get_conflict_type(filepath)
            if (action == "ours" and not conflict_info["ours_exists"]) or (
                action == "theirs" and not conflict_info["theirs_exists"]
            ):
                deletions.append(filepath)

        if deletions:
            dialog = Adw.AlertDialog.new(
                _("Delete files to resolve conflicts?"),
                _("The selected versions delete these files:\n{0}").format(
                    "\n".join(f"• {filepath}" for filepath in deletions)
                ),
            )
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("delete", _("Delete and Apply"))
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", self._on_deletion_confirmation)
            dialog.present(self)
            return

        self._apply_resolutions()

    def _on_deletion_confirmation(self, dialog, response):
        """Continue only after the explicit file-deletion response."""
        if response == "delete":
            self._apply_resolutions()

    def _apply_resolutions(self):
        """Apply the already reviewed conflict choices.

        A failure stops the loop, and the files handled before it have already
        been rewritten in the working tree. Closing on a bare "did not
        complete" left the user with no way to know which those were, so the
        offending row keeps the reason and the dialog stays open.
        """
        success = True
        applied: list[str] = []
        for filepath, action in self.resolutions.items():
            if self.apply_resolution(filepath, action):
                applied.append(filepath)
                continue
            success = False
            for row in self._iter_conflict_rows():
                if getattr(row, "filepath", None) == filepath:
                    row.set_subtitle(_("Could not apply this choice — see the log"))
                    break
            if applied:
                print(_("Already applied before the failure: {0}").format(", ".join(applied)))
            print(_("Stopped at {0}; the dialog stays open so you can retry.").format(filepath))
            break

        if not success:
            # Keep the window: closing would hide both the reason and the
            # half-resolved state it left behind.
            return

        if success:
            # Mark all as resolved in git
            for filepath in self.resolutions.keys():
                try:
                    # Check if file exists - files resolved with 'git rm' are already staged
                    abs_filepath = os.path.join(self.repo_root, filepath) if self.repo_root else filepath
                    if not os.path.exists(abs_filepath):
                        continue
                    subprocess.run_git(
                        ["git", "add", "--", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root,
                        intent="ordinary",
                    )
                except Exception:
                    success = False

        self.emit("conflicts-resolved", success)
        self.close()

    def _get_conflict_type(self, filepath):
        """
        Detect the type of conflict for a file.

        Returns a dict with:
            'ours_exists': bool - whether 'ours' (stage 2) version exists
            'theirs_exists': bool - whether 'theirs' (stage 3) version exists
        """
        try:
            result = subprocess.run_git(
                ["git", "ls-files", "-u", "--", filepath],
                capture_output=True,
                text=True,
                check=False,
                cwd=self.repo_root,
                intent="ordinary",
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            stages = set()
            for line in lines:
                parts = line.split("\t")[0].split()  # mode hash stage
                if len(parts) >= 3:
                    stages.add(int(parts[2]))

            return {"ours_exists": 2 in stages, "theirs_exists": 3 in stages}
        except Exception:
            return {"ours_exists": True, "theirs_exists": True}

    def apply_resolution(self, filepath, action):
        """Apply resolution for a file"""
        try:
            if action == "ours":
                conflict_info = self._get_conflict_type(filepath)
                if not conflict_info["ours_exists"]:
                    # Our side deleted the file - remove it
                    with authorize_destructive_git():
                        subprocess.run_git(
                            ["git", "rm", "-f", "--", filepath],
                            check=True,
                            capture_output=True,
                            cwd=self.repo_root,
                            intent="destructive",
                        )
                else:
                    # Keep local version
                    with authorize_destructive_git():
                        subprocess.run_git(
                            ["git", "checkout", "--ours", "--", filepath],
                            check=True,
                            capture_output=True,
                            cwd=self.repo_root,
                            intent="destructive",
                        )
            elif action == "theirs":
                conflict_info = self._get_conflict_type(filepath)
                if not conflict_info["theirs_exists"]:
                    # Remote side deleted the file - remove it
                    with authorize_destructive_git():
                        subprocess.run_git(
                            ["git", "rm", "-f", "--", filepath],
                            check=True,
                            capture_output=True,
                            cwd=self.repo_root,
                            intent="destructive",
                        )
                else:
                    # Accept remote version
                    with authorize_destructive_git():
                        subprocess.run_git(
                            ["git", "checkout", "--theirs", "--", filepath],
                            check=True,
                            capture_output=True,
                            cwd=self.repo_root,
                            intent="destructive",
                        )
            elif action == "manual":
                # The file has to be read again: "manual" only records that the
                # user opened it. Reporting success here staged the markers with
                # `git add` and published them, which a printed warning on
                # stdout does nothing to prevent.
                abs_path = os.path.join(self.repo_root, filepath) if self.repo_root else filepath
                try:
                    with open(abs_path, "r", errors="replace") as handle:
                        content = handle.read()
                except OSError as error:
                    print(_("Could not read {0}: {1}").format(filepath, error))
                    return False
                if any(marker in content for marker in ("<<<<<<<", "=======", ">>>>>>>")):
                    print(_("{0} still contains conflict markers; edit it and apply again.").format(filepath))
                    return False
                return True
            elif action == "both":
                # Write both sides straight out of the index, through the core
                # resolver. Checking each side out and copying it, as this
                # dialog used to, overwrote an untracked file.ours the user
                # already owned and followed it when it was a symlink; the core
                # reserves the companion with O_CREAT|O_EXCL|O_NOFOLLOW and
                # falls back to a numbered name instead.
                resolver = _core_resolver(self.repo_root)
                ours_file = resolver._write_index_stage(filepath, "2", "ours")
                theirs_file = resolver._write_index_stage(filepath, "3", "theirs")
                print(_("Saved both versions: {0}, {1}").format(ours_file, theirs_file))

                with authorize_destructive_git():
                    subprocess.run_git(
                        ["git", "checkout", f"--{getattr(self, 'local_side', 'ours')}", "--", filepath],
                        check=True,
                        capture_output=True,
                        cwd=self.repo_root,
                        intent="destructive",
                    )

            return True

        except Exception as e:
            print(_("Error resolving {0}: {1}").format(filepath, e))
            return False
