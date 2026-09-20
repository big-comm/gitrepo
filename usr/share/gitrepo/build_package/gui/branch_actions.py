"""Branch, merge, cleanup, and revert UI actions."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.git_utils import PROTECTED_BRANCHES, GitUtils
from gitrepo.common.translation import _
from gi.repository import Adw, Gtk, Pango

from gitrepo.common.page_hero import git_command_description, github_action_description


def _branch_endpoint(caption: str, branch: str, css_class: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)

    caption_label = Gtk.Label(label=caption)
    caption_label.add_css_class("caption")
    caption_label.add_css_class("dim-label")
    box.append(caption_label)

    branch_label = Gtk.Label(label=branch)
    branch_label.add_css_class("heading")
    branch_label.add_css_class(css_class)
    branch_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    branch_label.set_max_width_chars(24)
    branch_label.set_selectable(True)
    branch_label.set_tooltip_text(branch)
    branch_label.update_property([Gtk.AccessibleProperty.LABEL], [f"{caption}: {branch}"])
    box.append(branch_label)
    return box


def _dialog_form(width: int = 460) -> tuple[Gtk.Box, Adw.PreferencesGroup]:
    """Return a sized wrapper and the preferences group that holds the form rows."""
    wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    wrapper.set_size_request(width, -1)
    group = Adw.PreferencesGroup()
    group.set_margin_top(12)
    group.set_margin_bottom(6)
    wrapper.append(group)
    return wrapper, group


def _combo_row(title: str, choices: list[str], default: str = "") -> Adw.ComboRow:
    row = Adw.ComboRow()
    row.set_title(title)
    model = Gtk.StringList()
    for choice in choices:
        model.append(choice)
    row.set_model(model)
    if default in choices:
        row.set_selected(choices.index(default))
    return row


def _combo_value(row: Adw.ComboRow) -> str:
    index = row.get_selected()
    model = row.get_model()
    if index == Gtk.INVALID_LIST_POSITION or model is None:
        return ""
    return model.get_string(index)


def _merge_status_presentation(auto_merge: bool) -> tuple[str, str, str]:
    if auto_merge:
        return "gitrepo-status-ready-symbolic", _("✓ Auto-merge enabled"), "status-ok"
    return "gitrepo-status-warning-symbolic", _("Manual approval required"), "status-warning"


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

    # ------------------------------------------------------------------
    # Explicit branch management: create, rename, delete
    # ------------------------------------------------------------------

    def _branch_inventory(self):
        """Return (local, remote, current) from the shared snapshot, or None when it is stale."""
        snapshot = getattr(self, "_repository_snapshot", None)
        if not snapshot or snapshot.has_changes is None:
            self.show_error_toast(_("Repository status is unavailable. Refresh before managing branches."))
            return None
        return list(snapshot.local_branches), list(snapshot.remote_branches), snapshot.branch

    def _validate_new_branch_name(self, name: str, existing: set[str]) -> bool:
        if not name:
            self.show_error_toast(_("Type a name for the branch."))
            return False
        if name in existing:
            self.show_error_toast(_("A branch named '{0}' already exists.").format(name))
            return False
        if not GitUtils.is_valid_branch_name(name):
            self.show_error_toast(_("Invalid branch name: {0}").format(name))
            return False
        return True

    def on_create_branch_requested(self, widget):
        """Ask for a name, a source and the follow-up steps, then create the branch."""
        inventory = self._branch_inventory()
        if inventory is None:
            return
        local, remote, current = inventory
        choices = sorted(set(local + remote))
        if not choices:
            self.show_error_toast(_("No branch to create from. Make a first commit before branching."))
            return

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Create a branch"))
        dialog.set_body(
            git_command_description("git branch NEW SOURCE", "git checkout NEW", "git push -u origin NEW (optional)")
        )
        wrapper, group = _dialog_form()

        name_row = Adw.EntryRow()
        name_row.set_title(_("New branch name"))
        group.add(name_row)

        source_row = _combo_row(_("Create from"), choices, current)
        source_row.set_subtitle(_("The new branch starts at this branch's current commit"))
        group.add(source_row)

        checkout_row = Adw.SwitchRow()
        checkout_row.set_title(_("Switch to it after creating"))
        checkout_row.set_subtitle(_("Uncommitted changes are carried over; nothing is stashed or discarded"))
        checkout_row.set_active(True)
        group.add(checkout_row)

        publish_row = Adw.SwitchRow()
        publish_row.set_title(_("Publish to origin now"))
        publish_row.set_subtitle("git push -u origin NEW")
        publish_row.set_active(False)
        group.add(publish_row)

        dialog.set_extra_child(wrapper)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create branch"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("create", False)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")
        name_row.connect("changed", lambda row: dialog.set_response_enabled("create", bool(row.get_text().strip())))

        def on_response(_dialog, response):
            if response != "create":
                return
            new_name = name_row.get_text().strip()
            if not self._validate_new_branch_name(new_name, set(choices)):
                return
            self._run_branch_operation(
                "create",
                new_name,
                source=_combo_value(source_row),
                checkout=checkout_row.get_active(),
                publish=publish_row.get_active(),
            )

        dialog.connect("response", on_response)
        dialog.present()

    def on_rename_branch_requested(self, widget):
        """Pick a local branch, type its new name and decide whether origin follows."""
        inventory = self._branch_inventory()
        if inventory is None:
            return
        local, remote, current = inventory
        choices = [branch for branch in local if branch not in PROTECTED_BRANCHES]
        if not choices:
            self.show_error_toast(_("No local branch can be renamed; main, master and dev are shared."))
            return

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Rename a branch"))
        dialog.set_body(
            git_command_description(
                "git branch -m OLD NEW", "git push -u origin NEW (optional)", "git push origin --delete OLD (optional)"
            )
        )
        wrapper, group = _dialog_form()

        branch_row = _combo_row(_("Branch to rename"), choices, current)
        group.add(branch_row)

        name_row = Adw.EntryRow()
        name_row.set_title(_("New name"))
        group.add(name_row)

        remote_row = Adw.SwitchRow()
        remote_row.set_title(_("Also rename on origin"))
        remote_row.set_active(False)
        group.add(remote_row)

        def sync_remote_row(*_args):
            selected = _combo_value(branch_row)
            on_origin = selected in remote
            remote_row.set_sensitive(on_origin)
            if on_origin:
                remote_row.set_subtitle(
                    _("Publishes the new name and deletes origin/{0}; anyone tracking it loses it").format(selected)
                )
            else:
                remote_row.set_active(False)
                remote_row.set_subtitle(_("'{0}' is not on origin").format(selected))

        branch_row.connect("notify::selected", sync_remote_row)
        sync_remote_row()

        dialog.set_extra_child(wrapper)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename branch"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("rename", False)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        name_row.connect("changed", lambda row: dialog.set_response_enabled("rename", bool(row.get_text().strip())))

        def on_response(_dialog, response):
            if response != "rename":
                return
            old_name = _combo_value(branch_row)
            new_name = name_row.get_text().strip()
            if not self._validate_new_branch_name(new_name, set(local + remote)):
                return
            self._run_branch_operation("rename", old_name, new_name=new_name, rename_remote=remote_row.get_active())

        dialog.connect("response", on_response)
        dialog.present()

    def on_delete_branch_requested(self, widget):
        """Pick a branch, show what deleting it loses, and ask before removing it."""
        from gitrepo.build_package.core.branch_handler import describe_branch

        inventory = self._branch_inventory()
        if inventory is None:
            return
        local, remote, current = inventory
        choices = sorted((set(local) | set(remote)) - set(PROTECTED_BRANCHES) - {current})
        if not choices:
            self.show_error_toast(_("No branch can be deleted: the checked-out branch and shared branches stay."))
            return

        dialog = Adw.MessageDialog(transient_for=self, modal=True)
        dialog.set_heading(_("Delete a branch"))
        dialog.set_body(git_command_description("git branch -D BRANCH", "git push origin --delete BRANCH (optional)"))
        wrapper, group = _dialog_form()

        branch_row = _combo_row(_("Branch to delete"), choices)
        group.add(branch_row)

        remote_row = Adw.SwitchRow()
        remote_row.set_title(_("Also delete on origin"))
        remote_row.set_active(False)
        group.add(remote_row)

        status_label = Gtk.Label(xalign=0)
        status_label.set_wrap(True)
        status_label.set_margin_top(10)
        status_label.set_margin_start(6)
        status_label.set_margin_end(6)
        wrapper.append(status_label)

        facts = {}

        def sync_facts(*_args):
            selected = _combo_value(branch_row)
            facts.clear()
            facts.update(describe_branch(selected))
            remote_row.set_sensitive(facts["remote"])
            if facts["remote"]:
                remote_row.set_subtitle(_("origin/{0} is deleted as well").format(selected))
            else:
                remote_row.set_active(False)
                remote_row.set_subtitle(_("'{0}' is not on origin").format(selected))
            if not facts["local"]:
                # Only the remote copy exists, so the switch is the whole operation.
                remote_row.set_active(True)
            for css in ("error", "warning", "success"):
                status_label.remove_css_class(css)
            if facts["unmerged_commits"]:
                status_label.set_text(
                    _("'{0}' holds {1} commit(s) that are not in {2}. Deleting it loses them.").format(
                        selected, facts["unmerged_commits"], facts["base_label"]
                    )
                )
                status_label.add_css_class("error")
                dialog.set_response_label("delete", _("Delete anyway"))
            elif not facts["base"]:
                status_label.set_text(
                    _("No main or master branch to compare against; the branch cannot be proven merged.")
                )
                status_label.add_css_class("warning")
                dialog.set_response_label("delete", _("Delete anyway"))
            else:
                status_label.set_text(
                    _("Every commit of '{0}' is already in {1}.").format(selected, facts["base_label"])
                )
                status_label.add_css_class("success")
                dialog.set_response_label("delete", _("Delete branch"))

        dialog.set_extra_child(wrapper)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete branch"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        branch_row.connect("notify::selected", sync_facts)
        sync_facts()

        def on_response(_dialog, response):
            if response != "delete":
                return
            self._run_branch_operation(
                "delete",
                _combo_value(branch_row),
                delete_remote=remote_row.get_active(),
                force=bool(facts.get("unmerged_commits")) or not facts.get("base"),
            )

        dialog.connect("response", on_response)
        dialog.present()

    def _run_branch_operation(self, kind, branch, **options):
        """Run one reviewed branch operation from core/branch_handler.py with progress."""
        from functools import partial

        from gitrepo.build_package.core import branch_handler

        if kind == "create":
            operation = partial(
                branch_handler.create_branch,
                self.build_package,
                branch,
                options["source"],
                checkout=options["checkout"],
                publish=options["publish"],
            )
            title = _("Creating Branch")
            description = _("Running git branch {0} {1}...").format(branch, options["source"])
        elif kind == "rename":
            operation = partial(
                branch_handler.rename_branch,
                self.build_package,
                branch,
                options["new_name"],
                rename_remote=options["rename_remote"],
            )
            title = _("Renaming Branch")
            description = _("Running git branch -m {0} {1}...").format(branch, options["new_name"])
        else:
            operation = partial(
                branch_handler.delete_branch,
                self.build_package,
                branch,
                delete_remote=options["delete_remote"],
                force=options["force"],
            )
            title = _("Deleting Branch")
            description = _("Running git branch -D {0}...").format(branch)
        self.operation_runner.run_with_progress(operation, title, description)

    def _show_merge_confirmation(self, source_branch, target_branch, auto_merge):
        """Show merge confirmation dialog"""
        dialog = Adw.MessageDialog(transient_for=self, modal=True)

        dialog.set_heading(_("Propose branch integration?"))
        dialog.set_body("")

        # Visual content
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrapper.set_size_request(520, -1)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        action_box.add_css_class("build-package-github-action")
        action_icon = Gtk.Image.new_from_icon_name("build-package-pull")
        action_icon.set_pixel_size(22)
        action_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        action_box.append(action_icon)
        action_label = Gtk.Label(
            label=github_action_description(
                _("open a Pull Request on GitHub; this does not run git merge on your computer")
            ),
            xalign=0,
        )
        action_label.set_hexpand(True)
        action_label.set_wrap(True)
        action_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        action_label.set_selectable(True)
        action_box.append(action_label)
        content_box.append(action_box)

        # Branch flow visualization
        flow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        flow_box.set_halign(Gtk.Align.CENTER)
        flow_box.add_css_class("build-package-pr-card")

        flow_box.append(_branch_endpoint(_("Source Branch"), source_branch, "build-package-pr-source"))

        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(24)
        arrow.add_css_class("build-package-pr-arrow")
        arrow.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        flow_box.append(arrow)

        flow_box.append(_branch_endpoint(_("Target Branch"), target_branch, "build-package-pr-target"))

        content_box.append(flow_box)

        # Auto-merge status
        status_icon_name, status_text, status_class = _merge_status_presentation(auto_merge)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.add_css_class("state-pill")
        status_box.add_css_class(status_class)
        status_icon = Gtk.Image.new_from_icon_name(status_icon_name)
        status_icon.set_pixel_size(16)
        status_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        status_box.append(status_icon)
        status_box.append(Gtk.Label(label=status_text))
        content_box.append(status_box)

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
        self._ensure_token_and_run(
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

        self._ensure_token_and_run(
            cleanup_operation,
            _("Removing workflow runs"),
            github_action_description(_("delete {0} GitHub Actions runs").format(status_type)),
        )

    def on_cleanup_tags_requested(self, widget):
        """Handle cleanup tags request"""

        def cleanup_operation():
            return self.build_package.github_api.clean_all_tags(self.build_package.logger, self.build_package.menu)

        self._ensure_token_and_run(
            cleanup_operation,
            _("Removing remote tags"),
            github_action_description(_("delete all remote tag references; local tags are unchanged")),
        )

    def on_revert_commit_requested(self, widget, commit_hash, method):
        """Handle commit revert request — delegates to revert_operations."""
        from gitrepo.build_package.core.revert_operations import execute_revert_by_hash

        def revert_operation():
            return execute_revert_by_hash(self.build_package, commit_hash, method, confirmed=True)

        self.operation_runner.run_with_progress(
            revert_operation,
            _("Reverting Commit"),
            _("Reverting commit {0} using {1} method...").format(commit_hash[:7], method),
        )
