#
# gui/widgets/branch_widget.py - Branch management widget for GUI interface
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GObject
from gitrepo.common.translation import _

from gitrepo.common.help_popover import help_button
from gitrepo.common.page_layout import page_body
from gitrepo.common.page_hero import (
    BuildPackagePageHero as PageHero,
    git_command_description,
    github_action_description,
)


class BranchRow(Adw.ActionRow):
    """Custom row for branch display"""

    __gtype_name__ = "BranchRow"

    def __init__(self, branch_name, is_current=False, is_remote=False):
        super().__init__()

        self.branch_name = branch_name
        self.is_current = is_current
        self.is_remote = is_remote

        self.set_title(branch_name)
        self.set_activatable(True)

        # Add indicators
        if is_current:
            self.set_subtitle(_("Checked out right now"))
            current_icon = Gtk.Image.new_from_icon_name("gitrepo-status-ready-symbolic")
            current_icon.add_css_class("status-ok")
            self.add_prefix(current_icon)
            # A pill states the fact; colouring the whole row only implied it.
            pill = Gtk.Label(label=_("Current"))
            pill.add_css_class("state-pill")
            pill.add_css_class("status-ok")
            pill.set_valign(Gtk.Align.CENTER)
            self.add_suffix(pill)
        elif is_remote:
            # What is worth saying per row is what differs between rows. The
            # group already states that selecting one runs git checkout.
            self.set_subtitle(_("Only on origin; created locally on first checkout"))

        if is_remote:
            remote_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
            remote_icon.set_tooltip_text(_("Exists only on origin; it is created locally on first checkout"))
            self.add_suffix(remote_icon)

        if not is_current:
            self.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))


class BranchWidget(Gtk.Box):
    """Widget for branch management operations"""

    # Constant for main branch creation option
    MAIN_CREATE_NEW = "main (create new)"

    __gsignals__ = {
        "branch-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "merge-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str, bool)),  # source, target, auto_merge
        "cleanup-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.build_package = build_package
        self.current_branch = None
        self.branches = []
        self._block_selection_signal = False  # Flag to prevent signal loops

        self.create_ui()

    def create_ui(self):
        """Create the widget UI"""

        self.append(
            PageHero(
                "build-package-branches",
                _("Organize lines of work"),
                _(
                    "Switch branches with git checkout, publish new branches with git push, or propose integration on GitHub."
                ),
            )
        )

        clamp, page_content = page_body(spacing=18)
        self.append(clamp)

        # Current status
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Current Status"))
        status_group.set_description(_("Shows the active branch and the most recently updated local branch."))

        self.current_branch_row = Adw.ActionRow()
        self.current_branch_row.set_title(_("Active Branch"))
        active_icon = Gtk.Image.new_from_icon_name("build-package-branches")
        active_icon.set_pixel_size(24)
        active_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.current_branch_row.add_prefix(active_icon)
        status_group.add(self.current_branch_row)

        self.most_recent_row = Adw.ActionRow()
        self.most_recent_row.set_title(_("Most Recent Branch"))
        self.most_recent_row.set_subtitle(_("Branch with latest commits"))
        recent_icon = Gtk.Image.new_from_icon_name("build-package-commit")
        recent_icon.set_pixel_size(24)
        recent_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.most_recent_row.add_prefix(recent_icon)
        status_group.add(self.most_recent_row)

        page_content.append(status_group)

        # Branch list
        branches_group = Adw.PreferencesGroup()
        branches_group.set_title(_("Available Branches"))
        branches_group.set_description(
            _("Selecting another branch runs git checkout BRANCH; remote-only branches are created locally first.")
        )

        # Scrolled window for branch list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(220)
        scrolled.set_max_content_height(300)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.branches_list = Gtk.ListBox()
        self.branches_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.branches_list.set_activate_on_single_click(True)
        self.branches_list.add_css_class("boxed-list")
        self.branches_list.connect("row-activated", self.on_branch_activated)

        scrolled.set_child(self.branches_list)
        branches_group.add(scrolled)

        page_content.append(branches_group)

        # Quick actions for branch management
        quick_actions_group = Adw.PreferencesGroup()
        quick_actions_group.set_title(_("Quick Actions"))
        quick_actions_group.set_description(_("Return to the main line of development with an explicit Git command."))

        # Create/Switch to main button
        self.switch_main_row = Adw.ActionRow()
        self.switch_main_row.set_title(_("Return to the main branch"))
        self.switch_main_row.set_subtitle(
            git_command_description("git checkout main", "git checkout -b main (if needed)")
        )
        self.switch_main_row.set_activatable(True)

        switch_content = Adw.ButtonContent(label=_("Open main"), icon_name="build-package-branches")
        switch_main_button = Gtk.Button(child=switch_content)
        switch_main_button.set_valign(Gtk.Align.CENTER)
        switch_main_button.add_css_class("suggested-action")
        switch_main_button.connect("clicked", self.on_switch_main_clicked)
        self.switch_main_row.add_suffix(switch_main_button)

        quick_actions_group.add(self.switch_main_row)
        page_content.append(quick_actions_group)

        # Merge operations
        merge_group = Adw.PreferencesGroup()
        merge_group.set_title(_("Propose branch integration"))
        merge_group.set_header_suffix(
            help_button(
                _("How integration works"),
                _(
                    "The source branch is the one carrying your work; the target is where it should "
                    "land. GitRepo opens a pull request on GitHub instead of merging locally, so the "
                    "review and the checks still run."
                ),
            )
        )
        merge_group.set_description(
            github_action_description(_("open a Pull Request from the source branch to the target branch"))
        )

        # Source branch selection
        self.source_branch_row = Adw.ComboRow()
        self.source_branch_row.set_title(_("Source Branch"))
        self.source_branch_row.set_subtitle(_("Branch to merge from"))
        merge_group.add(self.source_branch_row)

        # Target branch selection
        self.target_branch_row = Adw.ComboRow()
        self.target_branch_row.set_title(_("Target Branch"))
        self.target_branch_row.set_subtitle(_("Branch to merge into"))
        merge_group.add(self.target_branch_row)

        # Auto-merge option
        self.auto_merge_row = Adw.SwitchRow()
        self.auto_merge_row.set_title(_("Auto-merge"))
        self.auto_merge_row.set_subtitle(_("Automatically merge if no conflicts"))
        merge_group.add(self.auto_merge_row)

        page_content.append(merge_group)

        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)

        # Refresh button
        refresh_content = Adw.ButtonContent(label=_("Refresh"), icon_name="view-refresh-symbolic")
        refresh_button = Gtk.Button(child=refresh_content)
        refresh_button.set_tooltip_text(_("Refresh branch list"))
        refresh_button.connect("clicked", self.on_refresh_clicked)
        actions_box.append(refresh_button)

        # Cleanup button
        cleanup_content = Adw.ButtonContent(label=_("Remove old branches"), icon_name="build-package-cleanup")
        cleanup_button = Gtk.Button(child=cleanup_content)
        cleanup_button.set_tooltip_text(
            git_command_description(
                "git fetch --all --prune", "git branch -D BRANCH", "git push origin --delete BRANCH"
            )
        )
        cleanup_button.add_css_class("destructive-action")
        cleanup_button.connect("clicked", self.on_cleanup_clicked)
        actions_box.append(cleanup_button)

        # Merge button
        merge_content = Adw.ButtonContent(label=_("Open Pull Request"), icon_name="build-package-branches")
        self.merge_button = Gtk.Button(child=merge_content)
        self.merge_button.add_css_class("suggested-action")
        self.merge_button.connect("clicked", self.on_merge_clicked)
        self.merge_button.set_sensitive(False)
        actions_box.append(self.merge_button)

        page_content.append(actions_box)

        # Connect combo box changes
        self.source_branch_row.connect("notify::selected", self.on_merge_selection_changed)
        self.target_branch_row.connect("notify::selected", self.on_merge_selection_changed)

    def refresh_branches(self):
        """Ask the owning window to refresh the shared snapshot."""
        window = self.get_root()
        if window and hasattr(window, "refresh_all_widgets"):
            window.refresh_all_widgets()

    def apply_snapshot(self, snapshot):
        """Render branch state captured outside the GTK main loop."""
        self._block_selection_signal = True
        self.current_branch = snapshot.branch
        active = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        self.current_branch_row.set_subtitle(active)
        self.most_recent_row.set_subtitle(snapshot.most_recent_branch or _("Not available"))
        all_branches = sorted(set(snapshot.local_branches + snapshot.remote_branches))
        while (row := self.branches_list.get_row_at_index(0)) is not None:
            self.branches_list.remove(row)
        for branch in all_branches:
            self.branches_list.append(
                BranchRow(
                    branch,
                    branch == snapshot.branch,
                    branch in snapshot.remote_branches and branch not in snapshot.local_branches,
                )
            )
        self.update_combo_boxes(all_branches)
        self._block_selection_signal = False

    def update_combo_boxes(self, branches):
        """Update merge combo boxes with branch list"""
        # Check if 'main' or 'master' exists in the branches list
        has_main = "main" in branches
        has_master = "master" in branches

        # Only add 'main (create new)' if neither main nor master exists
        if not has_main and not has_master:
            branches = [self.MAIN_CREATE_NEW] + branches

        # Create string list for branches
        branch_list = Gtk.StringList()
        for branch in branches:
            branch_list.append(branch)

        # Update combo boxes
        self.source_branch_row.set_model(branch_list)
        self.target_branch_row.set_model(branch_list)

        # Set default selections - prefer main/master for target
        if "main" in branches:
            main_index = branches.index("main")
            self.target_branch_row.set_selected(main_index)
        elif "master" in branches:
            main_index = branches.index("master")
            self.target_branch_row.set_selected(main_index)
        elif self.MAIN_CREATE_NEW in branches:
            main_index = branches.index(self.MAIN_CREATE_NEW)
            self.target_branch_row.set_selected(main_index)

        if self.current_branch and self.current_branch in branches:
            current_index = branches.index(self.current_branch)
            self.source_branch_row.set_selected(current_index)

    def on_branch_activated(self, _list_box, row):
        """Handle an explicit branch-row activation."""
        if self._block_selection_signal or not row:
            return
        branch_name = row.branch_name
        self.emit("branch-selected", branch_name)

    def on_merge_selection_changed(self, _combo_row, _param):
        """Handle merge combo box changes"""
        source_selected = self.source_branch_row.get_selected() != Gtk.INVALID_LIST_POSITION
        target_selected = self.target_branch_row.get_selected() != Gtk.INVALID_LIST_POSITION

        self.merge_button.set_sensitive(source_selected and target_selected)

    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.refresh_branches()

    def on_cleanup_clicked(self, button):
        """Handle cleanup button click"""
        self.emit("cleanup-requested")

    def on_merge_clicked(self, button):
        """Handle merge button click"""
        source_index = self.source_branch_row.get_selected()
        target_index = self.target_branch_row.get_selected()

        if source_index == Gtk.INVALID_LIST_POSITION or target_index == Gtk.INVALID_LIST_POSITION:
            return

        source_model = self.source_branch_row.get_model()
        target_model = self.target_branch_row.get_model()

        source_branch = source_model.get_string(source_index)
        target_branch = target_model.get_string(target_index)

        # Convert "main (create new)" to "main"
        if source_branch == self.MAIN_CREATE_NEW:
            source_branch = "main"
        if target_branch == self.MAIN_CREATE_NEW:
            target_branch = "main"

        if source_branch == target_branch:
            # Returning in silence made the suggested action look broken.
            root = self.get_root()
            if hasattr(root, "show_error_toast"):
                root.show_error_toast(_("Source and target are the same branch. Choose a different target."))
            return

        # Get auto-merge setting
        auto_merge = self.auto_merge_row.get_active()

        self.emit("merge-requested", source_branch, target_branch, auto_merge)

    def on_switch_main_clicked(self, button):
        """Route switching to main through the window's reviewed branch flow."""
        if self.current_branch != "main":
            self.emit("branch-selected", "main")
