#
# gui/widgets/commit_widget.py - Commit widget for GUI interface
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GObject, Pango
from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.common.translation import _

from gitrepo.common.help_popover import help_button
from gitrepo.common.page_layout import page_body
from gitrepo.common.page_hero import BuildPackagePageHero as PageHero, git_command_description


# Short, readable equivalents of the coloured state icons.
STATE_PILL_LABELS = {
    None: _("Checking"),
    "status-ok": _("OK"),
    "status-warning": _("Attention"),
    "status-error": _("Unavailable"),
}

# What an action's state means for the user about to press it.
ACTION_STATE_LABELS = {
    None: _("Checking"),
    "status-ok": _("Ready"),
    "status-warning": _("Pending changes"),
    "status-error": _("Unavailable"),
}


class StatusCard(Gtk.Box):
    """Accessible repository fact rendered as a compact premium card."""

    def __init__(self, title: str, icon_name: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._title = title
        self.add_css_class("build-package-status-card")
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)

        context_icon = Gtk.Image.new_from_icon_name(icon_name)
        context_icon.set_pixel_size(26)
        context_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.append(context_icon)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        copy.set_hexpand(True)
        copy.set_valign(Gtk.Align.CENTER)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        title_label.set_max_width_chars(24)
        copy.append(title_label)

        self.value_label = Gtk.Label(label=_("Checking…"), xalign=0)
        self.value_label.add_css_class("dim-label")
        self.value_label.add_css_class("caption")
        self.value_label.set_wrap(True)
        self.value_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.value_label.set_width_chars(1)
        self.value_label.set_yalign(0)
        self.value_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
        copy.append(self.value_label)
        self.append(copy)

        self.state_icon = Gtk.Image.new_from_icon_name("gitrepo-status-checking-symbolic")
        self.state_icon.set_pixel_size(18)
        self.state_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.append(self.state_icon)

        # Colour alone is not a state, so the card repeats it as readable text.
        self.state_pill = Gtk.Label(label=STATE_PILL_LABELS[None])
        self.state_pill.add_css_class("state-pill")
        self.state_pill.set_valign(Gtk.Align.CENTER)
        self.append(self.state_pill)

    def update_value(self, value: str) -> None:
        text = str(value)
        self.value_label.set_text(text)
        self.value_label.update_property([Gtk.AccessibleProperty.LABEL], [f"{self._title}: {text}"])

    def set_state(self, icon_name: str, css_class: str | None = None, tooltip: str | None = None) -> None:
        for candidate in ("status-ok", "status-warning", "status-error"):
            self.state_icon.remove_css_class(candidate)
            self.state_pill.remove_css_class(candidate)
        self.state_icon.set_from_icon_name(icon_name)
        self.state_pill.set_text(STATE_PILL_LABELS[css_class])
        if css_class:
            self.state_icon.add_css_class(css_class)
            self.state_pill.add_css_class(css_class)
        self.state_icon.set_tooltip_text(tooltip)
        self.state_pill.set_tooltip_text(tooltip)


class CommitWidget(Gtk.Box):
    """Widget for commit and push operations"""

    __gsignals__ = {
        "commit-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "pull-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "undo-commit-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "quick-action": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.build_package = build_package
        self._branch_name = ""
        self.selected_commit_type = None
        self.selected_emoji = None
        self._has_changes = False
        self._changed_file_rows = []

        self.create_ui()

    def create_ui(self):
        """Create the widget UI"""

        refresh_button = Gtk.Button(child=Adw.ButtonContent(label=_("Refresh"), icon_name="view-refresh-symbolic"))
        refresh_button.add_css_class("pill")
        refresh_button.set_tooltip_text(_("Refresh repository status"))
        refresh_button.connect("clicked", lambda _button: self.emit("refresh-requested"))

        hero = PageHero(
            "build-package-commit",
            _("Publish your work"),
            _("Review what changed, describe it, and send it to a remote branch."),
            refresh_button,
        )
        self.hero_subtitle = hero.description_label
        self.append(hero)

        clamp, page_content = page_body(spacing=18)
        self.append(clamp)

        page_content.append(self._create_status_cards())

        # Status group
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Pending files and history"))
        status_group.set_description(_("Review what will be recorded before writing the commit."))
        status_group.set_header_suffix(
            help_button(
                _("What publishing runs"),
                _("Download updates: {0}\n\nPublish changes: {1}").format(
                    git_command_description("git fetch origin BRANCH", "git merge --no-edit origin/BRANCH"),
                    git_command_description("git add -A", 'git commit -m "MESSAGE"', "git push -u origin BRANCH"),
                ),
            )
        )

        # Last commit row (for undo functionality)
        self.last_commit_row = Adw.ActionRow()
        self.last_commit_row.set_title(_("Last Commit"))
        self.last_commit_row.set_subtitle(_("No commit info"))
        commit_icon = Gtk.Image.new_from_icon_name("build-package-commit")
        commit_icon.set_pixel_size(24)
        commit_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.last_commit_row.add_prefix(commit_icon)

        # Undo button as suffix
        self.undo_button = Gtk.Button()
        self.undo_button.set_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text(_("Undo the last commit and keep its files changed — git reset HEAD~1"))
        self.undo_button.set_valign(Gtk.Align.CENTER)
        self.undo_button.add_css_class("flat")
        self.undo_button.connect("clicked", self.on_undo_clicked)
        self.undo_button.set_visible(False)  # Hidden by default
        self.last_commit_row.add_suffix(self.undo_button)

        status_group.add(self.last_commit_row)

        # Changed files expander
        self.changed_files_expander = Adw.ExpanderRow()
        self.changed_files_expander.set_title(_("Changed Files"))
        self.changed_files_expander.set_subtitle(_("Click to view files"))
        self.changed_files_expander.set_visible(False)
        status_group.add(self.changed_files_expander)

        page_content.append(status_group)

        # Commit type selection using ExpanderRow (opens below, larger)
        commit_type_group = Adw.PreferencesGroup()
        commit_type_group.set_title(_("Describe the commit"))
        commit_type_group.set_description(_("The type prefixes the message recorded by Git."))

        # Get commit types
        self.commit_types = self.build_package.get_commit_types()

        # Create expander row for commit types
        self.commit_type_expander = Adw.ExpanderRow()
        self.commit_type_expander.set_title(_("Commit Type"))
        # Amber text on the whole row lost contrast and read as an error. The
        # requirement is stated in words here and in the footer summary.
        self.commit_type_expander.set_subtitle(_("Required — select the type of change"))

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

            type_row.connect("activated", self.on_commit_type_row_activated)
            self.commit_type_expander.add_row(type_row)

        commit_type_group.add(self.commit_type_expander)

        # Commit message entry - multiline support

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

        # ScrolledWindow for multiline text
        message_scroll = Gtk.ScrolledWindow()
        message_scroll.set_min_content_height(80)
        message_scroll.set_max_content_height(120)
        message_scroll.set_vexpand(False)
        message_scroll.set_hexpand(True)

        # TextView for multiline commit message
        self.message_textview = Gtk.TextView()
        self.message_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.message_textview.set_left_margin(8)
        self.message_textview.set_right_margin(8)
        self.message_textview.set_top_margin(8)
        self.message_textview.set_bottom_margin(8)
        self.message_textview.get_buffer().connect("changed", self.on_message_changed)
        message_scroll.set_child(self.message_textview)

        message_frame.set_child(message_scroll)

        # Add to group using a vertical box
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        message_box.append(message_label)
        message_box.append(message_frame)
        message_box.set_margin_top(6)
        message_box.set_margin_bottom(6)

        message_row = Adw.PreferencesRow()
        message_row.set_activatable(False)
        message_row.set_child(message_box)
        commit_type_group.add(message_row)
        page_content.append(commit_type_group)

        # ── Footer: what will be published, plus the primary action ──
        # The form is longer than one screen, so the decision and its summary
        # stay pinned outside the scrolled area.
        self.page_footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.page_footer.add_css_class("page-footer-bar")

        summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        summary_box.set_hexpand(True)
        summary_box.set_valign(Gtk.Align.CENTER)
        self.summary_label = Gtk.Label(xalign=0)
        self.summary_label.add_css_class("build-summary-value")
        self.summary_label.set_wrap(True)
        self.summary_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.summary_label.set_width_chars(1)
        summary_box.append(self.summary_label)
        self.summary_detail = Gtk.Label(xalign=0)
        self.summary_detail.add_css_class("dim-label")
        self.summary_detail.add_css_class("caption")
        self.summary_detail.set_wrap(True)
        self.summary_detail.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.summary_detail.set_width_chars(1)
        summary_box.append(self.summary_detail)
        self.page_footer.append(summary_box)

        pull_content = Adw.ButtonContent(label=_("Download updates"), icon_name="build-package-pull")
        self.pull_button = Gtk.Button(child=pull_content)
        self.pull_button.set_valign(Gtk.Align.CENTER)
        self.pull_button.set_tooltip_text(
            git_command_description("git fetch origin BRANCH", "git merge --no-edit origin/BRANCH")
        )
        self.pull_button.connect("clicked", self.on_pull_clicked)
        self.page_footer.append(self.pull_button)

        commit_content = Adw.ButtonContent(label=_("Publish changes"), icon_name="build-package-commit")
        self.commit_button = Gtk.Button(child=commit_content)
        self.commit_button.add_css_class("suggested-action")
        self.commit_button.set_valign(Gtk.Align.CENTER)
        self.commit_button.connect("clicked", self.on_commit_clicked)
        self.commit_button.set_sensitive(False)
        self.page_footer.append(self.commit_button)

        # Do NOT auto-select first type — user must choose actively.
        # The expander starts marked as pending until the user picks a type.

    def apply_snapshot(self, snapshot):
        """Render commit state without running Git on the GTK main loop."""
        self._has_changes = snapshot.has_changes is True
        self._apply_status_cards(snapshot)
        self.hero_subtitle.set_text(self._workspace_summary(snapshot))
        self._branch_name = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        if snapshot.has_changes is None:
            self.changed_files_expander.set_visible(False)
        elif snapshot.has_changes:
            self._update_changed_files_list(snapshot.changed_files)
        else:
            self.changed_files_expander.set_visible(False)
        if snapshot.last_commit:
            commit_hash, message = snapshot.last_commit.split("|", 1)
            display_message = message[:50] + "..." if len(message) > 50 else message
            self.last_commit_row.set_subtitle(f"{commit_hash}: {display_message}")
        else:
            self.last_commit_row.set_subtitle(_("No commits yet (this will be your first!)"))
        self.undo_button.set_visible(snapshot.can_undo_last_commit)
        self.update_commit_button_state()

    def _select_commit_type_row(self, row):
        """Select a commit type row and update visuals"""
        # Hide all checkmarks first
        child = self.commit_type_expander.get_first_child()
        while child:
            if hasattr(child, "check_icon"):
                child.check_icon.set_visible(False)
            child = child.get_next_sibling()

        # Show checkmark on selected
        if hasattr(row, "check_icon"):
            row.check_icon.set_visible(True)

        # Update selected values
        self.selected_commit_type = row.commit_type
        self.selected_emoji = row.emoji

        # Update expander subtitle to show selection
        self.commit_type_expander.set_subtitle(f"{row.emoji} {row.commit_type}")

        # Collapse expander after selection
        self.commit_type_expander.set_expanded(False)

        # Update message label title
        if hasattr(self, "message_label") and self.message_label is not None:
            if row.commit_type == "custom":
                self.message_label.set_text(_("Custom message (supports multiple lines)"))
            else:
                self.message_label.set_text(_("Description for {0} (supports multiple lines)").format(row.commit_type))

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
        if not hasattr(self, "message_textview") or not hasattr(self, "commit_button"):
            return

        # Get text from TextView buffer
        buffer = self.message_textview.get_buffer()
        start, end = buffer.get_bounds()
        text = buffer.get_text(start, end, False)
        has_message = bool(text.strip())
        has_type = self.selected_commit_type is not None

        self.commit_button.set_sensitive(self._has_changes and has_message and has_type)
        self._update_summary(has_message, has_type)

    @staticmethod
    def _workspace_summary(snapshot) -> str:
        """One line naming the repository, its branch, and its pending work."""
        repository = (
            snapshot.repository_name.split("/")[-1]
            if snapshot.is_repository and snapshot.repository_name
            else (_("Local Git repository") if snapshot.is_repository else _("Not a Git repository"))
        )
        branch = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        if snapshot.has_changes is None:
            return _("{0} • branch {1} • status unavailable").format(repository, branch)
        if snapshot.has_changes:
            return _("{0} • branch {1} • {2} changed file(s)").format(repository, branch, len(snapshot.changed_files))
        return _("{0} • branch {1} • working tree clean").format(repository, branch)

    def _create_status_cards(self) -> Gtk.Widget:
        """Show branch, pending changes, and history depth at a glance."""
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_min_children_per_line(1)
        grid.set_max_children_per_line(3)
        grid.set_homogeneous(True)
        grid.set_column_spacing(12)
        grid.set_row_spacing(12)
        grid.add_css_class("build-package-status-grid")

        self.branch_status = StatusCard(_("Branch"), "build-package-branches")
        self.changes_status = StatusCard(_("Changes"), "build-package-repository")
        self.commits_status = StatusCard(_("Commits"), "build-package-commit")
        for card in (self.branch_status, self.changes_status, self.commits_status):
            grid.insert(card, -1)
        return grid

    def _apply_status_cards(self, snapshot) -> None:
        """Report the same snapshot the rest of the page is built from."""
        branch = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        self.branch_status.update_value(branch)
        self.commits_status.update_value("—" if snapshot.commit_count is None else str(snapshot.commit_count))

        if snapshot.has_changes is None:
            self.branch_status.set_state("gitrepo-status-warning-symbolic", "status-warning", _("Status unavailable"))
            self.changes_status.update_value(_("Unavailable"))
            self.changes_status.set_state(
                "gitrepo-status-error-symbolic", "status-error", _("Repository status unavailable")
            )
            self.commits_status.set_state(
                "gitrepo-status-warning-symbolic", "status-warning", _("Commit count may be stale")
            )
            return

        self.branch_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Active branch detected"))
        self.commits_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Commit history available"))
        if snapshot.has_changes:
            # Having work to publish is why this page exists; flagging it as a
            # warning makes the one state that matters look like a problem.
            self.changes_status.update_value(str(len(snapshot.changed_files)))
            self.changes_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Ready to publish"))
        else:
            self.changes_status.update_value(_("No changes"))
            self.changes_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Working tree clean"))

    def _update_summary(self, has_message: bool, has_type: bool) -> None:
        """Say, in one line, exactly what the primary action will publish."""
        if not hasattr(self, "summary_label"):
            return
        branch = getattr(self, "_branch_name", "") or _("unknown branch")
        if not self._has_changes:
            self.summary_label.set_text(_("Nothing to publish"))
            self.summary_detail.set_text(_("The working tree on {0} is clean.").format(branch))
            return

        commit_type = self.selected_commit_type or _("choose a type")
        files = len(self._changed_file_rows)
        self.summary_label.set_text(_("{0} • {1} file(s) • branch {2}").format(commit_type, files, branch))
        missing = []
        if not has_type:
            missing.append(_("commit type"))
        if not has_message:
            missing.append(_("description"))
        self.summary_detail.set_text(
            _("Still missing: {0}").format(", ".join(missing))
            if missing
            else _("git add -A → git commit → git push origin {0}").format(branch)
        )

    def on_pull_clicked(self, button):
        """Handle pull button click"""
        self.emit("pull-requested")

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
            if "\n" in message:
                lines = message.split("\n", 1)
                formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {lines[0]}\n\n{lines[1]}"
            else:
                formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {message}"

        self.emit("commit-requested", formatted_message)

        # Clear form after commit
        buffer.set_text("")

    def _update_changed_files_list(self, changed_files):
        """Populate the changed files expander from captured status."""
        for row in getattr(self, "_changed_file_rows", []):
            self.changed_files_expander.remove(row)
        self._changed_file_rows = []

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

            if status in ("D",):
                icon_name = "edit-delete-symbolic"
            elif status in ("A", "AM", "??"):
                icon_name = "list-add-symbolic"
            elif status in ("R", "C"):
                icon_name = "edit-copy-symbolic"
            else:
                icon_name = "document-edit-symbolic"

            icon = Gtk.Image.new_from_icon_name(icon_name)
            row.add_prefix(icon)
            # Reviewing the diff is part of writing an honest commit message.
            row.set_activatable(True)
            row.connect("activated", self._show_file_diff, filepath)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.changed_files_expander.add_row(row)
            self._changed_file_rows.append(row)

        count = len(changed_files)
        self.changed_files_expander.set_title(_("{0} changed file(s)").format(count))
        self.changed_files_expander.set_visible(count > 0)

    def _show_file_diff(self, _row, filepath):
        """Open the pending changes with the activated file selected."""
        from gitrepo.build_package.gui.dialogs.diff_viewer_dialog import present_diff_viewer

        present_diff_viewer(
            self.get_root(),
            _("Pending changes"),
            GitUtils.get_changed_files(),
            GitUtils.get_worktree_file_diff,
            initial_path=filepath,
        )

    def on_undo_clicked(self, button):
        """Handle undo last commit button click with confirmation"""
        # Show confirmation dialog
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Undo Last Commit?"),
            _(
                "This will undo your last commit but keep all changes in your working directory.\n\nYou can then modify files and commit again."
            ),
        )

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("undo", _("Undo Commit"))
        dialog.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dialog, response):
            if response == "undo":
                self.emit("undo-commit-requested")
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()
