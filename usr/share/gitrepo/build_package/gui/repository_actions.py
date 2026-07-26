"""Repository, commit, package, AUR, and token UI actions."""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.common.translation import _
from gi.repository import Adw, GLib, Gtk

from gitrepo.common.page_hero import git_command_description, github_action_description


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

    def on_commit_requested(self, widget, commit_message):
        """Handle commit request from commit widget - show branch confirmation first"""
        current_branch = GitUtils.get_current_branch()
        dev_branch = GitUtils.get_personal_branch(
            self.build_package.github_user_name,
            getattr(self.build_package, "repo_path", None),
        )

        # Store commit message for later use
        self._pending_commit_message = commit_message

        # Check if on a protected branch
        is_protected = current_branch in ["main", "master"]

        # Show confirmation dialog
        self._show_commit_branch_dialog(current_branch, dev_branch, is_protected)

    def _show_commit_branch_dialog(self, current_branch, dev_branch, is_protected):
        """Show dialog to confirm target branch for commit"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        if is_protected:
            dialog.set_heading(_("⚠️ Commit to Protected Branch?"))
            dialog.set_body(
                _(
                    "You are about to commit directly to '{0}'.\n\n"
                    "This is usually protected. Consider using your development branch instead.\n\n{1}"
                ).format(
                    current_branch,
                    git_command_description(
                        "git add -A",
                        'git commit -m "MESSAGE"',
                        "git push -u origin BRANCH",
                    ),
                )
            )
        else:
            dialog.set_heading(_("Confirm Commit Branch"))
            dialog.set_body(
                _("Choose where to publish your changes. {0}").format(
                    git_command_description(
                        "git add -A",
                        'git commit -m "MESSAGE"',
                        "git push -u origin BRANCH",
                    )
                )
            )
        dialog.set_extra_child(self._build_commit_branch_content(current_branch, dev_branch, is_protected))
        self._add_commit_branch_responses(dialog, current_branch, dev_branch, is_protected)
        dialog.connect("response", self._on_commit_branch_response, current_branch, dev_branch)
        dialog.present()

    @staticmethod
    def _build_commit_branch_content(current_branch, dev_branch, is_protected):
        """Build theme-safe branch context for the confirmation dialog."""
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(400, -1)
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
        current_box.append(branch_label)
        content_box.append(current_box)
        if current_branch != dev_branch:
            suggestion_label = Gtk.Label()
            suggestion_label.set_text(_("Your dev branch: {0}").format(dev_branch))
            suggestion_label.set_margin_top(8)
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

        # If we need to switch branches first
        if target_branch != current_branch:
            self._switch_then_commit(target_branch, self._pending_commit_message)
        else:
            self._do_commit(self._pending_commit_message, target_branch)

        self._pending_commit_message = None

    def _switch_then_commit(self, target_branch, commit_message):
        """Switch branch, sync remote, restore stash, commit — delegates to core/branch_handler.py."""
        from gitrepo.build_package.core.branch_handler import switch_and_commit

        self.operation_runner.run_with_progress(
            lambda: switch_and_commit(self.build_package, target_branch, commit_message),
            _("Preparing and publishing changes"),
            _("Switching to {0}, then running the publish command sequence...").format(target_branch),
        )

    def _do_commit(self, commit_message, target_branch):
        """Execute commit on current branch"""

        def commit_operation():
            return self._execute_commit(commit_message, target_branch)

        self.operation_runner.run_with_progress(
            commit_operation,
            _("Publishing changes"),
            _("Running git add, git commit, and git push for {0}...").format(target_branch),
        )

    def _execute_commit(self, commit_message, target_branch=None):
        """Stage, commit, and push — delegates to core/commit_handler.py."""
        from gitrepo.build_package.core.commit_handler import execute_commit as _execute

        return _execute(self.build_package, commit_message, target_branch)

    def on_pull_requested(self, widget):
        """Handle pull request"""

        def pull_operation():
            # Import V2 operation
            from gitrepo.build_package.core.pull_operations import pull_latest

            before = GitUtils.get_head_sha()
            if not pull_latest(self.build_package):
                return False
            after = GitUtils.get_head_sha()
            return {"before": before, "after": after, "changes": GitUtils.get_revision_changes(before, after)}

        self.operation_runner.run_with_progress(
            pull_operation,
            _("Downloading updates"),
            _("Running git fetch and git merge for the current branch..."),
            completion_callback=self._show_pulled_changes,
        )

    def _show_pulled_changes(self, result):
        """Show which files a completed pull brought in."""
        from gitrepo.build_package.gui.dialogs.diff_viewer_dialog import present_diff_viewer

        if not isinstance(result, dict) or not result.get("changes"):
            self.show_toast(_("Repository is already up to date"))
            return
        before, after = result["before"], result["after"]
        present_diff_viewer(
            self,
            _("Changes received from the remote"),
            result["changes"],
            lambda filepath: GitUtils.get_revision_file_diff(before, after, filepath),
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
        """Ensure GitHub token is available before running a package operation.

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
        dialog.set_body(
            _(
                "A GitHub Personal Access Token is required for package operations.\n\n"
                "To create one:\n"
                "1. Go to: github.com/settings/tokens\n"
                "2. Click 'Generate new token (classic)'\n"
                "3. Select scopes: 'repo' and 'workflow'\n"
                "4. Copy the generated token"
            )
        )

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
