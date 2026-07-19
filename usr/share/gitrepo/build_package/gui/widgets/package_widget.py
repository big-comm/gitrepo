#
# gui/widgets/package_widget.py - Package generation widget for GUI interface
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GObject
from gitrepo.common.translation import _

from gitrepo.common.page_hero import (
    BuildPackagePageHero as PageHero,
    git_command_description,
    github_action_description,
)


class PackageWidget(Gtk.Box):
    """Widget for package generation operations"""

    __gsignals__ = {
        "package-build-requested": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (str, bool),
        ),  # type, tmate
        "commit-and-build-requested": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (str, str, bool),
        ),  # type, commit_msg, tmate
    }

    def __init__(self, build_package, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.build_package = build_package
        self.settings = settings
        self._is_syncing_feature = False
        self.selected_package_type = None
        self.commit_message = ""
        self._has_changes = False
        self._package_name = ""

        self.create_ui()

    def create_ui(self):
        """Create the widget UI"""

        self.append(
            PageHero(
                "build-package-package",
                _("Build and publish a package"),
                _("Choose a destination and start a GitHub Actions build. With pending files, first run: {0}").format(
                    git_command_description(
                        "git add -A",
                        'git commit -m "MESSAGE"',
                        "git push -u origin BRANCH",
                    )
                ),
            )
        )

        page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page_content.add_css_class("page-frame")
        self.append(page_content)

        feature_group = Adw.PreferencesGroup()
        feature_group.set_title(_("GitHub package workflow"))
        feature_group.set_description(
            _(
                "This optional feature publishes a request to GitHub Actions. It does not build the package on this computer."
            )
        )
        self.feature_row = Adw.SwitchRow()
        self.feature_row.set_title(_("Enable package generation"))
        self.feature_row.set_subtitle(
            _(
                "Show the testing, stable, and extra publication workflow. Running it requires a GitHub access token with the permissions listed on the Access Tokens page."
            )
        )
        self.feature_row.connect("notify::active", self._on_feature_changed)
        feature_group.add(self.feature_row)
        page_content.append(feature_group)

        self.workflow_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page_content.append(self.workflow_content)

        # Repository status
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Repository Status"))
        status_group.set_description(_("Confirms the package, branch, and working tree used by the workflow."))

        self.package_name_row = Adw.ActionRow()
        self.package_name_row.set_title(_("Package Name"))
        package_icon = Gtk.Image.new_from_icon_name("build-package-package")
        package_icon.set_pixel_size(24)
        package_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.package_name_row.add_prefix(package_icon)
        status_group.add(self.package_name_row)

        self.working_branch_row = Adw.ActionRow()
        self.working_branch_row.set_title(_("Working Branch"))
        branch_icon = Gtk.Image.new_from_icon_name("build-package-branches")
        branch_icon.set_pixel_size(24)
        branch_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.working_branch_row.add_prefix(branch_icon)
        status_group.add(self.working_branch_row)

        self.changes_status_row = Adw.ActionRow()
        self.changes_status_row.set_title(_("Changes Status"))
        changes_icon = Gtk.Image.new_from_icon_name("build-package-repository")
        changes_icon.set_pixel_size(24)
        changes_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.changes_status_row.add_prefix(changes_icon)
        status_group.add(self.changes_status_row)

        self.workflow_content.append(status_group)

        # Package type selection with radio buttons style
        package_type_group = Adw.PreferencesGroup()
        package_type_group.set_title(_("Target Repository"))
        package_type_group.set_description(
            github_action_description(_("build the package and publish it to the selected repository"))
        )

        # Package types
        self.package_types = [
            (
                "testing",
                _("Testing"),
                _("Validate the package before a stable release"),
                "build-package-testing",
            ),
            ("stable", _("Stable"), _("Publish the package for all users"), "build-package-stable"),
            ("extra", _("Extra"), _("Publish an optional or additional package"), "build-package-extra"),
        ]

        # Use a ListBox for selection
        self.package_types_list = Gtk.ListBox()
        self.package_types_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.package_types_list.add_css_class("boxed-list")
        self.package_types_list.connect("row-selected", self.on_package_type_selected)

        for pkg_type, title, description, icon_name in self.package_types:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(description)
            row.set_activatable(True)
            row.package_type = pkg_type

            # Add icon as prefix
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(24)
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(icon)

            # Add checkmark (hidden by default)
            check_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            check_icon.set_visible(False)
            check_icon.add_css_class("success")
            row.check_icon = check_icon
            row.add_suffix(check_icon)

            self.package_types_list.append(row)

        package_type_group.add(self.package_types_list)
        self.workflow_content.append(package_type_group)

        # NOTE: seleção será feita após criar build_button em refresh_status

        # Commit message (conditional)
        self.commit_group = Adw.PreferencesGroup()
        self.commit_group.set_title(_("Record pending files before building"))
        self.commit_group.set_description(
            git_command_description("git add -A", 'git commit -m "MESSAGE"', "git push -u origin BRANCH")
        )

        # Get commit types from build_package
        self.commit_types = self.build_package.get_commit_types()
        self.selected_commit_type = None
        self.selected_emoji = None

        # Create expander row for commit types
        self.commit_type_expander = Adw.ExpanderRow()
        self.commit_type_expander.set_title(_("Commit Type"))
        self.commit_type_expander.set_subtitle(_("Select the type of change"))

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

        self.commit_group.add(self.commit_type_expander)

        # Commit message - multiline support (same as commit_widget.py)
        # Label for description
        message_label = Gtk.Label()
        message_label.set_text(_("Commit Message"))
        message_label.set_halign(Gtk.Align.START)
        message_label.add_css_class("dim-label")
        message_label.set_margin_start(6)
        message_label.set_margin_bottom(4)
        message_label.set_margin_top(6)

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
        self.message_textview.get_buffer().connect("changed", self.on_commit_message_changed)
        message_scroll.set_child(self.message_textview)

        message_frame.set_child(message_scroll)

        # Add to group using a vertical box
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        message_box.append(message_label)
        message_box.append(message_frame)
        message_box.set_margin_bottom(6)

        commit_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        commit_section.append(self.commit_group)
        commit_section.append(message_box)
        self.workflow_content.append(commit_section)

        # Store reference for visibility control
        self.commit_message_box = commit_section

        # Select first commit type by default
        self._select_first_commit_type()

        # Build options
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("Advanced Options"))
        options_group.set_description(_("Optional tools for diagnosing the remote workflow."))

        options_expander = Adw.ExpanderRow()
        options_expander.set_title(_("Remote Debugging"))
        options_expander.set_subtitle(_("Keep disabled for normal package builds"))

        self.tmate_row = Adw.SwitchRow()
        self.tmate_row.set_title(_("Enable TMATE Debug"))
        self.tmate_row.set_subtitle(_("Enable terminal access for debugging build issues"))
        options_expander.add_row(self.tmate_row)
        options_group.add(options_expander)

        self.workflow_content.append(options_group)

        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)

        # Cancel/Reset button
        reset_content = Adw.ButtonContent(label=_("Reset"), icon_name="edit-clear-symbolic")
        cancel_button = Gtk.Button(child=reset_content)
        cancel_button.add_css_class("build-package-action-button")
        cancel_button.connect("clicked", self.on_reset_clicked)
        actions_box.append(cancel_button)

        # Build button
        self.build_button_content = Adw.ButtonContent(
            label=_("Start package workflow"), icon_name="build-package-package"
        )
        self.build_button = Gtk.Button(child=self.build_button_content)
        self.build_button.add_css_class("suggested-action")
        self.build_button.add_css_class("build-package-primary-action")
        self.build_button.connect("clicked", self.on_build_clicked)
        self.build_button.set_sensitive(False)
        actions_box.append(self.build_button)

        self.workflow_content.append(actions_box)

        # Select testing by default (after all widgets created)
        first_row = self.package_types_list.get_row_at_index(0)
        if first_row:
            # Set package type without triggering update_build_button_state
            actual_row = first_row.get_child() if first_row.get_child() else first_row
            if hasattr(actual_row, "package_type"):
                self.selected_package_type = actual_row.package_type
            if hasattr(actual_row, "check_icon"):
                actual_row.check_icon.set_visible(True)
            self.package_types_list.select_row(first_row)

        self.sync_feature_enabled()

    def sync_feature_enabled(self):
        """Reconcile the visible workflow with its persisted feature flag."""
        enabled = self.settings.get("package_features_enabled", False)
        self._is_syncing_feature = True
        self.feature_row.set_active(enabled)
        self.workflow_content.set_visible(enabled)
        self._is_syncing_feature = False

    def _on_feature_changed(self, switch, _pspec):
        if self._is_syncing_feature:
            return
        enabled = switch.get_active()
        if not self.settings.set("package_features_enabled", enabled):
            self.sync_feature_enabled()
            return
        self.workflow_content.set_visible(enabled)
        root = self.get_root()
        if hasattr(root, "refresh_features"):
            root.refresh_features()

    def apply_snapshot(self, snapshot):
        """Render package prerequisites from captured repository state."""
        self._has_changes = snapshot.has_changes is True
        self._package_name = snapshot.package_name
        if not snapshot.package_name or snapshot.package_name.startswith("error"):
            self.package_name_row.set_subtitle(_("Error: PKGBUILD not found"))
            self.package_name_row.add_css_class("error")
        else:
            self.package_name_row.set_subtitle(snapshot.package_name)
            self.package_name_row.remove_css_class("error")
        branch = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        self.working_branch_row.set_subtitle(branch)
        self.changes_status_row.remove_css_class("warning")
        self.changes_status_row.remove_css_class("success")
        self.changes_status_row.remove_css_class("error")
        if getattr(self, "_changes_suffix_icon", None):
            self.changes_status_row.remove(self._changes_suffix_icon)
        if snapshot.has_changes is None:
            subtitle, icon_name, style = (
                _("Working tree status unavailable"),
                "gitrepo-status-error-symbolic",
                "error",
            )
        elif snapshot.has_changes:
            subtitle, icon_name, style = (
                _("Uncommitted changes present"),
                "gitrepo-status-warning-symbolic",
                "warning",
            )
        else:
            subtitle, icon_name, style = _("Working directory clean"), "gitrepo-status-ready-symbolic", "success"
        self.changes_status_row.set_subtitle(subtitle)
        self._changes_suffix_icon = Gtk.Image.new_from_icon_name(icon_name)
        self.changes_status_row.add_suffix(self._changes_suffix_icon)
        self.changes_status_row.add_css_class(style)
        self.commit_group.set_visible(self._has_changes)
        self.commit_message_box.set_visible(self._has_changes)
        self.update_build_button_state()

    def on_package_type_selected(self, _list_box, row):
        """Handle package type selection"""
        # Hide all checkmarks first
        for i in range(3):  # 3 package types
            child_row = self.package_types_list.get_row_at_index(i)
            if child_row and hasattr(child_row.get_child(), "check_icon"):
                child_row.get_child().check_icon.set_visible(False)
            elif child_row:
                # Get the actual row from ListBoxRow
                actual_row = child_row.get_child() if child_row.get_child() else child_row
                if hasattr(actual_row, "check_icon"):
                    actual_row.check_icon.set_visible(False)

        if row:
            # Show checkmark on selected
            actual_row = row.get_child() if hasattr(row, "get_child") and row.get_child() else row
            if hasattr(actual_row, "check_icon"):
                actual_row.check_icon.set_visible(True)
            if hasattr(actual_row, "package_type"):
                self.selected_package_type = actual_row.package_type
            elif hasattr(row, "package_type"):
                self.selected_package_type = row.package_type

            self.update_build_button_state()

            # Update build button text
            type_names = {
                "testing": _("Start testing build"),
                "stable": _("Start stable build"),
                "extra": _("Start extra build"),
            }

            if self.selected_package_type in type_names:
                self.build_button_content.set_label(type_names[self.selected_package_type])

    def on_commit_message_changed(self, buffer):
        """Handle commit message changes"""
        # Get text from TextView buffer
        start, end = buffer.get_bounds()
        self.commit_message = buffer.get_text(start, end, False).strip()
        self.update_build_button_state()

    def _select_first_commit_type(self):
        """Select first commit type by default"""
        if len(self.commit_types) > 0:
            # Find and select first row in expander
            first_row = None
            child = self.commit_type_expander.get_first_child()
            while child:
                if hasattr(child, "commit_type"):
                    first_row = child
                    break
                child = child.get_next_sibling()

            if first_row:
                self._select_commit_type_row(first_row)

    def on_commit_type_row_activated(self, row):
        """Handle commit type row activation"""
        self._select_commit_type_row(row)

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

        self.update_build_button_state()

    def update_build_button_state(self):
        """Update build button sensitivity"""
        # Check if package type is selected
        has_package_type = self.selected_package_type is not None

        # Check if commit message and type are provided when needed
        has_commit_msg = bool(self.commit_message) if self._has_changes else True
        has_commit_type = (self.selected_commit_type is not None) if self._has_changes else True

        # Check if package name is valid
        has_valid_package = bool(self._package_name) and not self._package_name.startswith("error")

        self.build_button.set_sensitive(has_package_type and has_commit_msg and has_commit_type and has_valid_package)

    def on_reset_clicked(self, button):
        """Handle reset button click"""
        # Clear selections
        self.package_types_list.unselect_all()
        self.selected_package_type = None

        # Reset commit type selection
        self._select_first_commit_type()

        # Clear commit message
        self.message_textview.get_buffer().set_text("")
        self.commit_message = ""

        # Reset TMATE option
        self.tmate_row.set_active(False)

        # Reset build button
        self.build_button.set_label(_("Start package workflow"))
        self.update_build_button_state()

    def on_build_clicked(self, button):
        """Handle build button click"""
        if not self.selected_package_type:
            return

        tmate_enabled = self.tmate_row.get_active()
        if self._has_changes and self.commit_message:
            # Format commit message with type (support multiline)
            if self.selected_commit_type == "custom":
                formatted_message = self.commit_message
            else:
                # For multiline messages, put type on first line
                if "\n" in self.commit_message:
                    lines = self.commit_message.split("\n", 1)
                    formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {lines[0]}\n\n{lines[1]}"
                else:
                    formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {self.commit_message}"

            # Need to commit first, then build
            self.emit("commit-and-build-requested", self.selected_package_type, formatted_message, tmate_enabled)
        else:
            # Direct build (no uncommitted changes)
            self.emit("package-build-requested", self.selected_package_type, tmate_enabled)
