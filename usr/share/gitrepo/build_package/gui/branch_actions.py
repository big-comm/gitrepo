"""Branch, merge, cleanup, and revert UI actions."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.common.translation import _
from gi.repository import Adw, Gtk

from gitrepo.common.page_hero import git_command_description, github_action_description


class BranchActionsMixin:
    """Own branch lifecycle and advanced destructive journeys."""

    def on_branch_selected(self, widget, branch_name):
        """Handle branch selection - switch to selected branch intelligently"""
        snapshot = getattr(self, "_repository_snapshot", None)
        if not snapshot or snapshot.has_changes is None:
            self.show_error_toast(_("Repository status is unavailable. Refresh before switching branches."))
            return
        current_branch = snapshot.branch

        # Don't switch if already on this branch
        if branch_name == current_branch:
            return  # Silently ignore

        # Check for local changes
        if snapshot.has_changes:
            # Show confirmation dialog with options
            self._show_branch_switch_dialog(branch_name, current_branch)
        else:
            # No changes, switch directly
            self._do_branch_switch(branch_name, stash_first=False)

    def _show_branch_switch_dialog(self, target_branch, current_branch):
        """Show dialog asking what to do with local changes"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Uncommitted Changes Detected"))
        dialog.set_body(
            _("You have uncommitted changes. Preserve them with {0}, or discard them with {1}.").format(
                git_command_description(
                    "git stash push -u -m TEMPORARY_NAME",
                    "git checkout BRANCH",
                    "git stash pop",
                ),
                git_command_description("git checkout -- .", "git clean -fd", "git checkout BRANCH"),
            )
        )

        # Add visual content with icon and branch info - wrapper for min width
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)  # Force minimum width

        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(32)
        content_box.set_margin_end(32)
        content_box.set_halign(Gtk.Align.CENTER)

        # Warning icon
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(56)
        icon.add_css_class("warning")
        content_box.append(icon)

        # Branch info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_box.set_valign(Gtk.Align.CENTER)

        from_label = Gtk.Label()
        from_label.set_text(_("Current: {0}").format(current_branch))
        from_label.set_halign(Gtk.Align.START)
        info_box.append(from_label)

        to_label = Gtk.Label()
        to_label.set_text(_("Switch to: {0}").format(target_branch))
        to_label.set_halign(Gtk.Align.START)
        info_box.append(to_label)

        content_box.append(info_box)
        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)

        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard files and switch"))
        dialog.add_response("stash", _("Preserve files and switch"))

        dialog.set_response_appearance("stash", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("stash")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_branch_switch_response, target_branch)
        dialog.present()

    def _on_branch_switch_response(self, dialog, response, target_branch):
        """Handle branch switch dialog response"""
        if response == "stash":
            self._do_branch_switch(target_branch, stash_first=True)
        elif response == "discard":
            self._do_branch_switch(target_branch, discard_first=True)
        # Cancel does nothing

    def _do_branch_switch(self, target_branch, stash_first=False, discard_first=False):
        """Perform branch switch — delegates git logic to core/branch_handler.py."""
        from gitrepo.build_package.core.branch_handler import switch_branch

        def operation():
            result = switch_branch(
                self.build_package,
                target_branch,
                stash_first=stash_first,
                discard_first=discard_first,
            )
            self.build_package.logger.log(result["message_type"], result["message"])
            return result["success"]

        self.operation_runner.run_with_progress(
            operation,
            _("Opening another branch"),
            _("Running git checkout for '{0}'...").format(target_branch),
        )

    def on_merge_requested(self, widget, source_branch, target_branch, auto_merge):
        """Handle merge request - create PR or create branch if target doesn't exist"""
        snapshot = getattr(self, "_repository_snapshot", None)
        branches = set(snapshot.local_branches + snapshot.remote_branches) if snapshot else set()
        if target_branch not in branches:
            self._show_create_branch_dialog(source_branch, target_branch)
            return

        repo_name = snapshot.repository_name if snapshot else ""
        if not repo_name:
            self._show_no_remote_error()
            return

        self._show_merge_confirmation(source_branch, target_branch, auto_merge)

    def _show_create_branch_dialog(self, source_branch, target_branch):
        """Show dialog to create a branch that doesn't exist and push to remote"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)

        dialog.set_heading(_("Create Branch '{0}'?").format(target_branch))
        dialog.set_body(
            _("The branch '{0}' doesn't exist yet. Create it from '{1}' and publish it?\n\n{2}").format(
                target_branch,
                source_branch,
                git_command_description(
                    "git checkout SOURCE_BRANCH",
                    "git checkout -b TARGET_BRANCH",
                    "git push -u origin TARGET_BRANCH",
                ),
            )
        )

        # Visual content - wrapper for consistent width
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Flow visualization
        flow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        flow_box.set_halign(Gtk.Align.CENTER)

        source_label = Gtk.Label()
        source_label.set_text(source_branch)
        source_label.add_css_class("heading")
        flow_box.append(source_label)

        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(24)
        flow_box.append(arrow)

        target_label = Gtk.Label()
        target_label.set_text(_("{0} (new)").format(target_branch))
        target_label.add_css_class("heading")
        flow_box.append(target_label)

        content_box.append(flow_box)

        info_label = Gtk.Label()
        info_label.set_text(
            _("This will copy all code from '{0}' to the new '{1}' branch").format(source_branch, target_branch)
        )
        info_label.set_wrap(True)
        info_label.set_margin_top(8)
        content_box.append(info_label)

        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)

        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create and publish branch"))

        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_create_branch_response, source_branch, target_branch)
        dialog.present()

    def _on_create_branch_response(self, dialog, response, source_branch, target_branch):
        """Handle create branch dialog response — delegates to core/branch_handler.py."""
        if response != "create":
            return

        from gitrepo.build_package.core.branch_handler import create_branch_and_push

        self.operation_runner.run_with_progress(
            lambda: create_branch_and_push(self.build_package, source_branch, target_branch),
            _("Creating Branch"),
            _("Creating '{0}' from '{1}' and pushing...").format(target_branch, source_branch),
        )

    def _show_merge_confirmation(self, source_branch, target_branch, auto_merge):
        """Show merge confirmation dialog"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)

        dialog.set_heading(_("Propose branch integration?"))
        dialog.set_body(
            github_action_description(_("open a Pull Request on GitHub; this does not run git merge on your computer"))
        )

        # Visual content
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(420, -1)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Branch flow visualization
        flow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        flow_box.set_halign(Gtk.Align.CENTER)

        source_label = Gtk.Label()
        source_label.set_text(source_branch)
        source_label.add_css_class("heading")
        flow_box.append(source_label)

        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(24)
        flow_box.append(arrow)

        target_label = Gtk.Label()
        target_label.set_text(target_branch)
        target_label.add_css_class("heading")
        flow_box.append(target_label)

        content_box.append(flow_box)

        # Auto-merge status
        merge_status = Gtk.Label()
        if auto_merge:
            merge_status.set_text(_("✓ Auto-merge enabled"))
        else:
            merge_status.set_text(_("Manual approval required"))
            merge_status.add_css_class("dim-label")
        merge_status.set_margin_top(8)
        content_box.append(merge_status)

        wrapper.append(content_box)
        dialog.set_extra_child(wrapper)

        # Responses
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Open Pull Request"))

        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_merge_confirm_response, source_branch, target_branch, auto_merge)
        dialog.present()

    def _on_merge_confirm_response(self, dialog, response, source_branch, target_branch, auto_merge):
        """Handle merge confirmation response"""
        if response != "create":
            return

        def merge_operation():
            return self.build_package.github_api.create_pull_request(
                source_branch, target_branch, auto_merge, self.build_package.logger
            )

        merge_type = _("Auto-merge") if auto_merge else _("Manual")
        self.operation_runner.run_with_progress(
            merge_operation,
            _("Opening Pull Request"),
            _("{0}: {1} → {2}").format(merge_type, source_branch, target_branch),
        )

    def on_branch_cleanup_requested(self, widget):
        """Handle branch cleanup request"""
        self.on_cleanup_branches_requested(widget)

    def on_cleanup_branches_requested(self, widget):
        """Handle cleanup branches request"""

        def cleanup_operation():
            return GitUtils.cleanup_old_branches(self.build_package.logger, self.build_package.menu)

        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Removing old branches"),
            _("Running the reviewed git branch and git push deletion commands..."),
        )

    def on_cleanup_actions_requested(self, widget, status_type):
        """Handle cleanup actions request"""

        def cleanup_operation():
            return self.build_package.github_api.clean_action_jobs(
                status_type, self.build_package.logger, self.build_package.menu
            )

        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Removing workflow runs"),
            github_action_description(_("delete {0} GitHub Actions runs").format(status_type)),
        )

    def on_cleanup_tags_requested(self, widget):
        """Handle cleanup tags request"""

        def cleanup_operation():
            return self.build_package.github_api.clean_all_tags(self.build_package.logger, self.build_package.menu)

        self.operation_runner.run_with_progress(
            cleanup_operation,
            _("Removing remote tags"),
            github_action_description(_("delete all remote tag references; local tags are unchanged")),
        )

    def on_revert_commit_requested(self, widget, commit_hash, method):
        """Handle commit revert request — delegates to revert_operations."""
        from gitrepo.build_package.core.revert_operations import execute_revert_by_hash

        def revert_operation():
            return execute_revert_by_hash(self.build_package, commit_hash, method)

        self.operation_runner.run_with_progress(
            revert_operation,
            _("Reverting Commit"),
            _("Reverting commit {0} using {1} method...").format(commit_hash[:7], method),
        )
