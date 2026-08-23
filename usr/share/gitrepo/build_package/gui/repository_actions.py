"""Repository, commit, package, AUR, and token UI actions."""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.common.translation import _
from gi.repository import Adw, GLib, Gtk

from gitrepo.build_package.core.confirmation import ConfirmationBlock
from gitrepo.build_package.gui.confirmation_dialog import confirmation_details
from gitrepo.common.page_hero import git_command_description, github_action_description


_COMMIT_COMMANDS = (
    "git add -A",
    'git commit -m "MESSAGE"',
    "git push -u origin BRANCH",
)


def _commit_command_block(push: bool = True) -> ConfirmationBlock:
    commands = _COMMIT_COMMANDS if push else _COMMIT_COMMANDS[:-1]
    return ConfirmationBlock(
        "command",
        " → ".join(commands),
        git_command_description("").strip(),
    )


class RepositoryActionsMixin:
    """Own the repository-changing journeys initiated by the main window."""

    def on_quick_action(self, widget, action_id):
        """Open the destination that owns a follow-up action."""
        if action_id == "pull":
            self.on_pull_requested(widget)
            return
        tab = "aur" if action_id == "aur" else "repository"
        self.switch_to_page("packages")
        self.packages_page.show_tab(tab)

    def on_overview_refresh(self, widget):
        """Handle overview refresh request"""
        self.refresh_all_widgets()

    def on_commit_requested(self, widget, commit_message, commit_only=False):
        """Handle commit request from commit widget - show branch confirmation first"""
        current_branch = GitUtils.get_current_branch()
        dev_branch = GitUtils.get_personal_branch(
            self.build_package.github_user_name,
            getattr(self.build_package, "repo_path", None),
        )

        # Store commit message for later use
        self._pending_commit_message = commit_message
        self._pending_commit_only = bool(commit_only)

        # Check if on a protected branch
        is_protected = current_branch in ["main", "master"]

        # Show confirmation dialog
        self._show_commit_branch_dialog(current_branch, dev_branch, is_protected)

    def _show_commit_branch_dialog(self, current_branch, dev_branch, is_protected):
        """Show dialog to confirm target branch for commit"""
        push = not getattr(self, "_pending_commit_only", False)
        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        if is_protected:
            dialog.set_heading(_("⚠️ Commit to Protected Branch?"))
            dialog.set_body(
                _(
                    "You are about to commit directly to '{0}'.\n\n"
                    "This is usually protected. Consider using your development branch instead.\n\n{1}"
                )
                .format(
                    current_branch,
                    "",
                )
                .strip()
            )
        elif push:
            dialog.set_heading(_("Confirm Commit Branch"))
            dialog.set_body(_("Choose where to publish your changes. {0}").format("").strip())
        else:
            dialog.set_heading(_("Confirm Commit Branch"))
            dialog.set_body(_("Choose where to record the commit. Nothing will be pushed to origin."))
        dialog.set_extra_child(self._build_commit_branch_content(current_branch, dev_branch, is_protected, push))
        self._add_commit_branch_responses(dialog, current_branch, dev_branch, is_protected)
        dialog.connect("response", self._on_commit_branch_response, current_branch, dev_branch)
        dialog.present()

    @staticmethod
    def _build_commit_branch_content(current_branch, dev_branch, is_protected, push=True):
        """Build theme-safe branch context for the confirmation dialog."""
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(520, -1)

        commands = confirmation_details((_commit_command_block(push),))
        commands.set_margin_top(12)
        commands.set_margin_start(24)
        commands.set_margin_end(24)
        wrapper.append(commands)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        current_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        current_box.set_halign(Gtk.Align.CENTER)
        icon_name = "dialog-warning-symbolic" if is_protected else "emblem-ok-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        icon.add_css_class("warning" if is_protected else "success")
        current_box.append(icon)
        branch_label = Gtk.Label()
        branch_label.set_text(_("Current: {0}").format(current_branch))
        branch_label.add_css_class("heading")
        branch_label.add_css_class("warning" if is_protected else "success")
        branch_label.set_selectable(True)
        current_box.append(branch_label)
        content_box.append(current_box)
        if current_branch != dev_branch:
            suggestion_label = Gtk.Label()
            suggestion_label.set_text(_("Your dev branch: {0}").format(dev_branch))
            suggestion_label.set_margin_top(8)
            suggestion_label.add_css_class("accent")
            suggestion_label.set_selectable(True)
            content_box.append(suggestion_label)
        wrapper.append(content_box)
        return wrapper

    @staticmethod
    def _add_commit_branch_responses(dialog, current_branch, dev_branch, is_protected):
        """Add the valid target-branch choices and their semantic appearances."""
        dialog.add_response("cancel", _("Cancel"))
        if current_branch != dev_branch:
            dialog.add_response("dev", _("Use {0}").format(dev_branch))
            dialog.set_response_appearance("dev", Adw.ResponseAppearance.SUGGESTED)
        if current_branch not in ["main", "master"]:
            dialog.add_response("main", _("Send to main"))
        if is_protected:
            dialog.add_response("current", _("Commit to {0} anyway").format(current_branch))
            dialog.set_response_appearance("current", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dialog.add_response("current", _("Commit to {0}").format(current_branch))
            if current_branch == dev_branch:
                dialog.set_response_appearance("current", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("dev" if current_branch != dev_branch else "current")
        dialog.set_close_response("cancel")

    def _on_commit_branch_response(self, dialog, response, current_branch, dev_branch):
        """Handle commit branch dialog response"""
        if response == "cancel":
            self._pending_commit_message = None
            return

        # Determine target branch based on response
        if response == "main":
            target_branch = "main"
        elif response == "dev":
            target_branch = dev_branch
        else:
            target_branch = current_branch

        commit_only = getattr(self, "_pending_commit_only", False)

        # If we need to switch branches first
        if target_branch != current_branch:
            self._switch_then_commit(target_branch, self._pending_commit_message, commit_only)
        else:
            self._do_commit(self._pending_commit_message, target_branch, commit_only)

        self._pending_commit_message = None
        self._pending_commit_only = False

    def _switch_then_commit(self, target_branch, commit_message, commit_only=False):
        """Switch branch, sync remote, restore stash, commit — delegates to core/branch_handler.py."""
        from gitrepo.build_package.core.branch_handler import switch_and_commit

        title = _("Preparing the commit") if commit_only else _("Preparing and publishing changes")
        body = (
            _("Switching to {0}, then committing without pushing...")
            if commit_only
            else _("Switching to {0}, then running the publish command sequence...")
        )
        self.operation_runner.run_with_progress(
            lambda: switch_and_commit(self.build_package, target_branch, commit_message, push=not commit_only),
            title,
            body.format(target_branch),
        )

    def _do_commit(self, commit_message, target_branch, commit_only=False):
        """Execute commit on current branch"""

        def commit_operation():
            return self._execute_commit(commit_message, target_branch, commit_only)

        title = _("Committing locally") if commit_only else _("Publishing changes")
        body = (
            _("Running git add and git commit for {0}; origin is untouched...")
            if commit_only
            else _("Running git add, git commit, and git push for {0}...")
        )
        self.operation_runner.run_with_progress(commit_operation, title, body.format(target_branch))

    def _execute_commit(self, commit_message, target_branch=None, commit_only=False):
        """Stage, commit, and optionally push — delegates to core/commit_handler.py."""
        from gitrepo.build_package.core.commit_handler import execute_commit as _execute

        return _execute(self.build_package, commit_message, target_branch, push=not commit_only)

    def on_publish_pending_requested(self, widget):
        """Push a commit that was recorded locally, creating no new commit."""
        from gitrepo.build_package.core.commit_handler import publish_existing_commit

        branch = GitUtils.get_current_branch()
        if not branch:
            self.show_toast(_("Could not determine the current branch"))
            return

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Publish the existing local commit?"))
        dialog.set_body(_("No new commit will be created. The branch {0} will be pushed to origin.").format(branch))
        dialog.set_extra_child(
            confirmation_details(
                (
                    ConfirmationBlock(
                        "command",
                        f"git push -u origin {branch}",
                        git_command_description("").strip(),
                    ),
                )
            )
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("publish", _("Publish now"))
        dialog.set_response_appearance("publish", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("publish")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            _dialog.close()
            if response != "publish":
                return
            self.operation_runner.run_with_progress(
                lambda: publish_existing_commit(self.build_package, branch),
                _("Publishing the local commit"),
                _("Running git push for {0}...").format(branch),
            )

        dialog.connect("response", on_response)
        dialog.present()

    def on_pull_requested(self, widget):
        """Fetch remote updates and let the user review them before merging."""
        from gitrepo.build_package.core.pull_operations import prepare_pull

        self.operation_runner.run_with_progress(
            lambda: prepare_pull(self.build_package),
            _("Downloading updates"),
            _("Checking..."),
            completion_callback=self._show_pull_review,
        )

    def _show_pull_review(self, review):
        """List every fetched branch and mark the newest commit."""
        from gitrepo.build_package.core.pull_operations import PullReview

        if not isinstance(review, PullReview) or not review.branches:
            self.show_toast(_("Repository is already up to date"))
            return

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Available Branches"))
        dialog.set_body("")

        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(620, -1)
        wrapper.set_margin_top(12)
        wrapper.set_margin_bottom(12)
        wrapper.set_margin_start(18)
        wrapper.set_margin_end(18)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(240)
        scrolled.set_max_content_height(420)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        branch_list = Gtk.ListBox()
        branch_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        branch_list.add_css_class("boxed-list")
        first_row = None
        for index, candidate in enumerate(review.branches):
            row = Adw.ActionRow(
                title=f"origin/{candidate.name}",
                subtitle=f"{candidate.head[:12]} · {candidate.committed} · {candidate.subject}",
            )
            row.branch_name = candidate.name
            if index == 0:
                pill = Gtk.Label(label=_("Most Recent Branch"))
                pill.set_valign(Gtk.Align.CENTER)
                pill.add_css_class("state-pill")
                pill.add_css_class("status-ok")
                row.add_suffix(pill)
            if candidate.name == review.branch:
                pill = Gtk.Label(label=_("Current"))
                pill.set_valign(Gtk.Align.CENTER)
                pill.add_css_class("state-pill")
                pill.add_css_class("accent")
                row.add_suffix(pill)
            branch_list.append(row)
            first_row = first_row or row
        branch_list.select_row(first_row)
        scrolled.set_child(branch_list)
        wrapper.append(scrolled)
        dialog.set_extra_child(wrapper)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("review", _("Compare versions side-by-side"))
        dialog.set_response_appearance("review", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("review")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_pull_branch_response, review, branch_list)
        dialog.present()

    def _on_pull_branch_response(self, _dialog, response, review, branch_list):
        """Prepare the selected branch for the existing file review."""
        if response != "review":
            return
        row = branch_list.get_selected_row()
        if row is None:
            return
        from gitrepo.build_package.core.pull_operations import prepare_pull_preview

        self.operation_runner.run_with_progress(
            lambda: prepare_pull_preview(self.build_package, review, row.branch_name),
            _("Downloading updates"),
            _("Checking..."),
            completion_callback=self._show_pull_preview,
        )

    def _show_pull_preview(self, preview):
        """Show incoming file differences with the update action beside them."""
        from gitrepo.build_package.core.pull_operations import PullPreview
        from gitrepo.build_package.gui.dialogs.diff_viewer_dialog import present_diff_viewer

        if not isinstance(preview, PullPreview) or not preview.changes:
            self.show_toast(_("Repository is already up to date"))
            return
        present_diff_viewer(
            self,
            _("Changes received from the remote"),
            preview.changes,
            lambda filepath: GitUtils.get_revision_file_diff(preview.merge_base, preview.remote_head, filepath),
            action_label=_("Download updates"),
            action_callback=lambda: self._apply_pull_preview(preview),
            subtitle=f"origin/{preview.incoming_branch} → {preview.branch}",
        )

    def _apply_pull_preview(self, preview):
        """Apply the immutable remote update accepted in the diff viewer."""
        from gitrepo.build_package.core.pull_operations import apply_pull_preview

        self.operation_runner.run_with_progress(
            lambda: apply_pull_preview(self.build_package, preview),
            _("Downloading updates"),
            _("Running git fetch and git merge for the current branch..."),
        )

    def on_undo_commit_requested(self, widget):
        """Handle undo last commit request — delegates to core/branch_handler.py."""
        from gitrepo.build_package.core.branch_handler import undo_last_commit

        self.operation_runner.run_with_progress(
            lambda: undo_last_commit(self.build_package),
            _("Undoing the last commit"),
            _("Running git reset HEAD~1 and keeping the files changed..."),
        )

    def on_package_build_requested(self, _widget: Gtk.Widget, package_type: str, tmate: bool) -> None:
        """Handle package build request"""

        def build_operation():
            # Import V2 operation
            from gitrepo.build_package.core.package_operations import commit_and_generate_package

            # Use V2 operation
            return commit_and_generate_package(
                self.build_package,
                branch_type=package_type,
                commit_message=None,
                tmate_option=tmate,
            )

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            build_operation,
            _("Starting package workflow"),
            github_action_description(_("build and publish the {0} package").format(package_type)),
        )

    def on_commit_and_build_requested(self, widget, package_type, commit_message, tmate):
        """Handle commit and build request"""

        def commit_and_build_operation():
            # Import V2 operation
            from gitrepo.build_package.core.package_operations import commit_and_generate_package

            # Use V2 operation
            return commit_and_generate_package(
                self.build_package,
                branch_type=package_type,
                commit_message=commit_message,
                tmate_option=tmate,
            )

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            commit_and_build_operation,
            _("Publishing changes and starting package workflow"),
            _("Running the Git publish sequence, then asking GitHub Actions to build {0}...").format(package_type),
        )

    def on_aur_build_requested(self, widget, package_name, tmate):
        """Handle AUR build request"""

        def aur_build_operation():
            self.build_package.args.aur = package_name
            self.build_package.args.tmate = tmate
            return self.build_package.build_aur_package()

        # Check token before starting - if missing, show setup dialog
        self._ensure_token_and_run(
            aur_build_operation,
            _("Starting AUR workflow"),
            github_action_description(_("clone and build the AUR package {0}").format(package_name)),
        )

    def _ensure_token_and_run(self, operation, title, description):
        """Ensure a GitHub token is available before running an API operation.

        If token is missing, shows a GTK dialog to guide the user through setup.
        If token is available (or setup succeeds), runs the operation.
        """
        github_api = self.build_package.github_api

        # Check if token is already available
        if github_api.token:
            self.operation_runner.run_with_progress(operation, title, description)
            return

        def lookup_token():
            token = github_api.get_github_token_optional()
            GLib.idle_add(finish_lookup, token)

        def finish_lookup(token):
            if token:
                github_api.token = token
                github_api.headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "Authorization": f"token {token}",
                }
                self.operation_runner.run_with_progress(operation, title, description)
            else:
                self._show_token_setup_dialog(operation, title, description)
            return False

        threading.Thread(target=lookup_token, daemon=True).start()

    def _show_token_setup_dialog(self, pending_operation, pending_title, pending_description):
        """Show GTK dialog to set up GitHub token"""

        from gitrepo.build_package.core.token_store import TokenStore

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("GitHub Token Setup"))
        dialog.set_body(_("A GitHub Personal Access Token is required for this operation."))

        # Create content box with entry fields
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Username field
        username_label = Gtk.Label(label=_("GitHub Username:"), xalign=0)
        username_entry = Gtk.Entry()
        username_entry.set_placeholder_text(_("your-username"))
        content_box.append(username_label)
        content_box.append(username_entry)

        # Token field
        token_label = Gtk.Label(label=_("GitHub Token:"), xalign=0)
        token_entry = Gtk.PasswordEntry()
        token_entry.set_show_peek_icon(True)
        token_entry.set_placeholder_text("ghp_...")
        content_box.append(token_label)
        content_box.append(token_entry)

        # Link to GitHub settings
        link_label = Gtk.Label()
        link_label.set_markup(
            '<a href="https://github.com/settings/tokens">' + _("Open GitHub Token Settings") + "</a>"
        )
        link_label.set_margin_top(8)
        content_box.append(link_label)

        dialog.set_extra_child(content_box)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save and Continue"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")

        def on_response(dialog, response):
            if response == "save":
                username = username_entry.get_text().strip()
                token_text = token_entry.get_text().strip()

                if not username or not token_text:
                    self.show_error_toast(_("Username and token are required"))
                    dialog.close()
                    return

                dialog.set_response_enabled("save", False)
                organization = self.build_package.organization

                def store_token():
                    saved = TokenStore.upsert(organization, token_text)
                    verified = saved and TokenStore.get_token(organization) == token_text
                    GLib.idle_add(finish_store, verified)

                def finish_store(saved):
                    dialog.close()
                    if not saved:
                        self.show_error_dialog(
                            _(
                                "The token could not be saved in the system keyring. "
                                "Check that the keyring is unlocked and try again."
                            )
                        )
                        return False
                    github_api = self.build_package.github_api
                    github_api.token = token_text
                    github_api.headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"token {token_text}",
                    }
                    self.show_toast(_("✓ Token saved successfully"))
                    self.operation_runner.run_with_progress(pending_operation, pending_title, pending_description)
                    return False

                threading.Thread(target=store_token, daemon=True).start()
            else:
                dialog.close()

        dialog.connect("response", on_response)
        dialog.present()
