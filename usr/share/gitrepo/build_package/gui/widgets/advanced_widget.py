#
# gui/widgets/advanced_widget.py - Advanced operations widget for GUI interface
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GObject
from gitrepo.common.translation import _

from gitrepo.common.page_layout import page_body
from gitrepo.common.page_hero import (
    BuildPackagePageHero as PageHero,
    git_command_description,
    github_action_description,
)


class OperationRow(Adw.ActionRow):
    """Custom row for advanced operations"""

    __gtype_name__ = "OperationRow"

    def __init__(self, operation_id, title, description, icon_name, is_destructive=False):
        super().__init__()

        self.operation_id = operation_id
        self.is_destructive = is_destructive

        self.set_title(title)
        self.set_subtitle(description)
        self.set_activatable(True)

        # Add icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(24)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        if is_destructive:
            icon.add_css_class("error")
        self.add_prefix(icon)

        # Add styling for destructive actions
        if is_destructive:
            self.add_css_class("destructive-action")


class CommitRow(Adw.ActionRow):
    """Custom row for commit display"""

    __gtype_name__ = "CommitRow"

    def __init__(self, commit_hash, author, date, message):
        super().__init__()

        self.commit_hash = commit_hash

        self.set_title(f"{commit_hash[:7]} - {message[:60]}")
        self.set_subtitle(f"{author} • {date}")
        self.set_activatable(True)
        icon = Gtk.Image.new_from_icon_name("build-package-revert")
        icon.set_pixel_size(22)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.add_prefix(icon)


class AdvancedWidget(Gtk.Box):
    """Widget for advanced operations"""

    __gsignals__ = {
        "cleanup-branches-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "cleanup-actions-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),  # status type
        "cleanup-tags-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "revert-commit-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),  # commit_hash, method
    }

    def __init__(self, build_package, show_hero: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.build_package = build_package
        self._show_hero = show_hero
        self.recent_commits = []
        self.create_ui()

    def create_ui(self):
        """Create the widget UI"""

        if self._show_hero:
            self.append(
                PageHero(
                    "build-package-advanced",
                    _("Maintain and restore the repository"),
                    _(
                        "Remove obsolete references or return files and history to an earlier point. Every destructive command requires confirmation."
                    ),
                )
            )

        clamp, page_content = page_body(spacing=18)
        self.append(clamp)

        # Warning banner
        warning_banner = Adw.Banner()
        warning_banner.set_title(_("Warning: These operations can be destructive"))
        warning_banner.add_css_class("error")
        warning_banner.add_css_class("build-package-warning-banner")
        warning_banner.set_revealed(True)
        page_content.append(warning_banner)

        # Cleanup operations
        cleanup_group = Adw.PreferencesGroup()
        cleanup_group.set_title(_("Cleanup Operations"))
        cleanup_group.set_description(_("Remove obsolete GitHub Actions runs and remote tags"))

        cleanup_operations = [
            (
                "failed_actions",
                _("Remove failed workflow runs"),
                github_action_description(_("delete failed GitHub Actions runs; no Git command is used")),
                "gitrepo-status-error-symbolic",
                True,
            ),
            (
                "success_actions",
                _("Remove successful workflow runs"),
                github_action_description(_("delete successful GitHub Actions runs; no Git command is used")),
                "build-package-stable",
                False,
            ),
            (
                "tags",
                _("Remove all remote tags"),
                github_action_description(_("delete refs/tags through the GitHub API; local tags are unchanged")),
                "build-package-cleanup",
                True,
            ),
        ]

        self.cleanup_list = Gtk.ListBox()
        self.cleanup_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.cleanup_list.add_css_class("boxed-list")
        self.cleanup_list.connect("row-activated", self.on_cleanup_operation_activated)

        for op_id, title, desc, icon, destructive in cleanup_operations:
            row = OperationRow(op_id, title, desc, icon, destructive)
            self.cleanup_list.append(row)

        cleanup_group.add(self.cleanup_list)
        page_content.append(cleanup_group)

        # Commit revert operations
        revert_group = Adw.PreferencesGroup()
        self.history_group = revert_group
        revert_group.set_title(_("Commit History"))
        revert_group.set_description(_("View and revert recent commits"))

        # Commit list - show at least 5 commits
        scrolled_commits = Gtk.ScrolledWindow()
        scrolled_commits.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_commits.set_min_content_height(220)
        scrolled_commits.set_max_content_height(320)
        scrolled_commits.set_propagate_natural_height(True)

        self.commits_list = Gtk.ListBox()
        self.commits_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.commits_list.add_css_class("boxed-list")
        self.commits_list.connect("row-selected", self.on_commit_selected)

        scrolled_commits.set_child(self.commits_list)
        revert_group.add(scrolled_commits)

        # Revert options
        self.revert_method_row = Adw.ComboRow()
        self.revert_method_row.set_title(_("How to return to the selected commit"))
        self.revert_method_row.set_use_subtitle(True)

        methods = Gtk.StringList()
        # Shorter text that fits in popup - tooltip can explain more
        methods.append(_("Restore files with a new commit"))
        methods.append(_("Move history back and delete newer commits"))
        self.revert_method_row.set_model(methods)
        self.revert_method_row.set_selected(0)  # Default to revert
        self.revert_method_row.connect("notify::selected", self.on_revert_method_changed)
        self.on_revert_method_changed(self.revert_method_row, None)

        page_content.append(revert_group)

        # Keep the method control on its own surface. Mixing this ComboRow with
        # the independently scrolling commit list caused their rounded cards to
        # overlap visually.
        revert_method_group = Adw.PreferencesGroup()
        revert_method_group.add(self.revert_method_row)
        page_content.append(revert_method_group)

        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)

        # Refresh button
        refresh_content = Adw.ButtonContent(label=_("Refresh"), icon_name="view-refresh-symbolic")
        refresh_button = Gtk.Button(child=refresh_content)
        refresh_button.connect("clicked", self.on_refresh_clicked)
        actions_box.append(refresh_button)

        # Revert button
        revert_content = Adw.ButtonContent(label=_("Return to selected commit"), icon_name="build-package-revert")
        self.revert_button = Gtk.Button(child=revert_content)
        self.revert_button.add_css_class("destructive-action")
        self.revert_button.connect("clicked", self.on_revert_clicked)
        self.revert_button.set_sensitive(False)
        actions_box.append(self.revert_button)

        page_content.append(actions_box)

    def refresh_commits(self):
        """Ask the owning window to refresh the shared snapshot."""
        window = self.get_root()
        if window and hasattr(window, "refresh_all_widgets"):
            window.refresh_all_widgets()

    def apply_snapshot(self, snapshot):
        """Render history and statistics captured outside the GTK main loop."""
        while (row := self.commits_list.get_row_at_index(0)) is not None:
            self.commits_list.remove(row)
        self.recent_commits = []
        for commit_hash, author, date, message in snapshot.recent_commits:
            self.recent_commits.append({"hash": commit_hash, "author": author, "date": date, "message": message})
            self.commits_list.append(CommitRow(commit_hash, author, date, message))
        if not snapshot.recent_commits:
            # Not activatable: an activatable placeholder could be selected, which
            # enabled the destructive revert button and offered to reset the
            # repository to commit "--------".
            placeholder = CommitRow("--------", _("No commits yet"), "", _("Create your first commit to see history"))
            placeholder.set_activatable(False)
            placeholder.set_selectable(False)
            self.commits_list.append(placeholder)
        branches = set(snapshot.local_branches + snapshot.remote_branches)
        commits = _("unknown") if snapshot.commit_count is None else str(snapshot.commit_count)
        self.history_group.set_description(
            _("{0} branch(es) and {1} commit(s) in the current branch.").format(len(branches), commits)
        )

    def on_cleanup_operation_activated(self, _list_box, row):
        """Handle cleanup operation selection"""
        # The owner first inventories the exact remote/local objects and then
        # presents the one authoritative destructive confirmation.
        self.execute_cleanup_operation(row.operation_id)

    def execute_cleanup_operation(self, operation_id):
        """Execute cleanup operation"""
        if operation_id == "branches":
            self.emit("cleanup-branches-requested")
        elif operation_id == "failed_actions":
            self.emit("cleanup-actions-requested", "failure")
        elif operation_id == "success_actions":
            self.emit("cleanup-actions-requested", "success")
        elif operation_id == "tags":
            self.emit("cleanup-tags-requested")

    def on_commit_selected(self, _list_box, row):
        """Handle commit selection"""
        self.revert_button.set_sensitive(row is not None)

    def on_revert_method_changed(self, _row, _param):
        """Explain the exact commands used by the selected recovery method."""
        if self.revert_method_row.get_selected() == 0:
            description = git_command_description(
                "git read-tree -u --reset COMMIT",
                'git commit -m "MESSAGE"',
                "git push origin BRANCH",
            )
        else:
            description = git_command_description(
                "git reset --hard COMMIT",
                "git push origin BRANCH --force-with-lease (if remote)",
            )
        self.revert_method_row.set_subtitle(description)

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
        method_text = _("restore") if method == "revert" else _("reset")
        commands = (
            git_command_description(
                "git read-tree -u --reset COMMIT",
                'git commit -m "MESSAGE"',
                "git push origin BRANCH",
            )
            if method == "revert"
            else git_command_description(
                "git reset --hard COMMIT",
                "git push origin BRANCH --force-with-lease (if remote)",
            )
        )

        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Confirm Commit {0}").format(method_text.title()),
            _("Are you sure you want to {0} this commit?\n\n{1}\n\nCommit: {2}\n\n{3}").format(
                method_text, commit_title, commit_hash[:7], commands
            ),
        )

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", method_text.title())
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dialog, response):
            if response == "confirm":
                self.emit("revert-commit-requested", commit_hash, method)
                self.refresh_commits()  # Refresh after revert
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()
