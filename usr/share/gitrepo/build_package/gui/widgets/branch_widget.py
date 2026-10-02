#
# gui/widgets/branch_widget.py - Branch management widget for GUI interface
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, GObject
from gitrepo.common.translation import _

from gitrepo.build_package.core import branch_overview as overview_core
from gitrepo.build_package.core import main_sync
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


# CSS classes for the semantic tones of core/branch_overview.py.
_TONE_CLASSES = {
    overview_core.TONE_OK: "status-ok",
    overview_core.TONE_AHEAD: "status-accent",
    overview_core.TONE_BEHIND: "status-warning",
    overview_core.TONE_DIVERGED: "status-error",
    overview_core.TONE_NEUTRAL: "dim-label",
}


def _tone_pill(tone, text, tooltip=""):
    """A coloured label led by a symbolic icon, so the state reads without colour too."""
    pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    pill.add_css_class("state-pill")
    pill.add_css_class(_TONE_CLASSES[tone])
    pill.set_valign(Gtk.Align.CENTER)
    icon_name = overview_core.TONE_ICONS[tone]
    if icon_name:
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(12)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        pill.append(icon)
    pill.append(Gtk.Label(label=text))
    if tooltip:
        pill.set_tooltip_text(tooltip)
    return pill


# Icon and colour of the verdict that heads the sync group.
_VERDICT_ICONS = {
    main_sync.SYNCED: "gitrepo-status-ready-symbolic",
    main_sync.CATCH_UP: "gitrepo-status-warning-symbolic",
    main_sync.WORK_PENDING: "go-up-symbolic",
    main_sync.UNAVAILABLE: "gitrepo-status-checking-symbolic",
}


class SyncRefRow(Adw.ActionRow):
    """One copy of the work (here or on origin) and where it stands against origin/main."""

    __gtype_name__ = "SyncRefRow"

    def __init__(self, ref):
        super().__init__()
        self.set_title(GLib.markup_escape_text(ref.label))
        on_origin = ref.label.startswith("origin/")
        place = Gtk.Image.new_from_icon_name("network-server-symbolic" if on_origin else "computer-symbolic")
        place.set_tooltip_text(_("Copy on origin (GitHub)") if on_origin else _("Copy on this computer"))
        self.add_prefix(place)
        if ref.tip:
            subtitle = _("commit {0} · {1} · {2}").format(
                ref.tip.short_sha, ref.tip.subject, overview_core.describe_age(ref.tip.committed_at)
            )
        else:
            subtitle = _("This copy does not exist.")
        self.set_subtitle(GLib.markup_escape_text(subtitle))
        self.set_subtitle_lines(1)
        self.add_suffix(_tone_pill(*main_sync.describe_ref(ref)))


class BranchComparisonRow(Adw.ActionRow):
    """One branch with its commit, compared with origin and with the base branch."""

    __gtype_name__ = "BranchComparisonRow"

    def __init__(self, branch, overview):
        super().__init__()
        self.branch_name = branch.name
        self.set_title(GLib.markup_escape_text(branch.name))
        local = branch.local.short_sha if branch.local else "—"
        remote = branch.remote.short_sha if branch.remote else "—"
        tip = branch.local or branch.remote
        self.set_subtitle(
            _("local {0} · origin {1} · last commit {2}").format(
                local, remote, overview_core.describe_age(tip.committed_at if tip else None)
            )
        )
        if tip:
            self.set_tooltip_text(tip.subject)
        if branch.is_current:
            current_icon = Gtk.Image.new_from_icon_name("gitrepo-status-ready-symbolic")
            current_icon.add_css_class("status-ok")
            current_icon.set_tooltip_text(_("Checked out right now"))
            self.add_prefix(current_icon)
        remote_tone, remote_text = overview_core.describe_vs_remote(branch)
        self.add_suffix(_tone_pill(remote_tone, remote_text, _("Local branch × origin/{0}").format(branch.name)))
        base_tone, base_text = overview_core.describe_vs_base(branch, overview)
        self.add_suffix(_tone_pill(base_tone, base_text, _("This branch × {0}").format(overview.base_ref or "main")))


class BranchWidget(Gtk.Box):
    """Widget for branch management operations"""

    # Constant for main branch creation option
    MAIN_CREATE_NEW = "main (create new)"

    __gsignals__ = {
        "branch-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "merge-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str, bool)),  # source, target, auto_merge
        "cleanup-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "create-branch-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "rename-branch-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "delete-branch-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "fetch-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "sync-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
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
                    "Switch, create, rename or delete branches with explicit Git commands, or propose integration on GitHub."
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

        # Is my work in main? The four copies that answer it, and one button to align them.
        self.sync_group = Adw.PreferencesGroup()
        self.sync_group.set_title(_("Sync with main"))
        self.sync_group.set_description(
            _(
                "Shows whether your work is already in origin/main, where pull requests land and stable packages are built from."
            )
        )
        sync_suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_suffix.append(
            help_button(
                _("How synchronizing works"),
                _(
                    "Synchronize runs git fetch and then only moves copies forward: your branch and the local "
                    "main advance to origin/main, and your branch is published when it already matches main. "
                    "Commits that exist only in the local main are kept in a backup branch first. Nothing is "
                    "merged and no work is discarded."
                ),
            )
        )
        self.fetch_button = Gtk.Button(
            child=Adw.ButtonContent(label=_("Check origin"), icon_name="network-server-symbolic")
        )
        self.fetch_button.set_valign(Gtk.Align.CENTER)
        self.fetch_button.set_tooltip_text(
            _("Read the latest state of origin without changing any branch.")
            + "\n"
            + git_command_description("git fetch --prune origin")
        )
        self.fetch_button.connect("clicked", self.on_fetch_clicked)
        sync_suffix.append(self.fetch_button)
        self.sync_group.set_header_suffix(sync_suffix)

        self.verdict_row = Adw.ActionRow()
        self.verdict_row.set_title_lines(0)
        self.verdict_row.set_subtitle_lines(0)
        self.verdict_icon = Gtk.Image()
        self.verdict_icon.set_pixel_size(32)
        self.verdict_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.verdict_row.add_prefix(self.verdict_icon)
        self.sync_button = Gtk.Button(
            child=Adw.ButtonContent(label=_("Synchronize"), icon_name="view-refresh-symbolic")
        )
        self.sync_button.set_valign(Gtk.Align.CENTER)
        self.sync_button.set_tooltip_text(
            git_command_description(
                "git fetch --prune origin",
                "git merge --ff-only origin/main",
                "git push origin BRANCH (when it already matches main)",
            )
        )
        self.sync_button.connect("clicked", self.on_sync_clicked)
        self.verdict_row.add_suffix(self.sync_button)
        self.sync_group.add(self.verdict_row)

        self.refs_list = Gtk.ListBox()
        self.refs_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.refs_list.add_css_class("boxed-list")
        self.refs_list.set_margin_top(12)
        self.sync_group.add(self.refs_list)

        self.freshness_label = Gtk.Label(xalign=0, wrap=True)
        self.freshness_label.add_css_class("caption")
        self.freshness_label.set_margin_top(6)
        self.sync_group.add(self.freshness_label)

        all_list = Gtk.ListBox()
        all_list.set_selection_mode(Gtk.SelectionMode.NONE)
        all_list.add_css_class("boxed-list")
        all_list.set_margin_top(12)
        self.all_branches_row = Adw.ExpanderRow()
        self.all_branches_row.set_title(_("All branches"))
        all_list.append(self.all_branches_row)
        self.sync_group.add(all_list)
        self._all_branch_rows = []
        page_content.append(self.sync_group)

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

        # Explicit branch management: create, rename, delete
        manage_group = Adw.PreferencesGroup()
        manage_group.set_title(_("Manage branches"))
        manage_group.set_description(
            _("Each action shows its Git commands and asks before anything is published or deleted.")
        )

        self.create_branch_row = self._manage_row(
            _("Create branch"),
            git_command_description("git branch NEW SOURCE", "git checkout NEW", "git push -u origin NEW (optional)"),
            _("Create…"),
            "list-add-symbolic",
            "suggested-action",
            self.on_create_branch_clicked,
        )
        manage_group.add(self.create_branch_row)

        self.rename_branch_row = self._manage_row(
            _("Rename branch"),
            git_command_description(
                "git branch -m OLD NEW", "git push -u origin NEW (optional)", "git push origin --delete OLD (optional)"
            ),
            _("Rename…"),
            "document-edit-symbolic",
            "",
            self.on_rename_branch_clicked,
        )
        manage_group.add(self.rename_branch_row)

        self.delete_branch_row = self._manage_row(
            _("Delete branch"),
            git_command_description("git branch -D BRANCH", "git push origin --delete BRANCH (optional)"),
            _("Delete…"),
            "user-trash-symbolic",
            "destructive-action",
            self.on_delete_branch_clicked,
        )
        manage_group.add(self.delete_branch_row)

        page_content.append(manage_group)

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

    @staticmethod
    def _manage_row(title, subtitle, button_label, icon_name, css_class, handler):
        """Build one row whose suffix button opens a reviewed branch dialog."""
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(subtitle)
        button = Gtk.Button(child=Adw.ButtonContent(label=button_label, icon_name=icon_name))
        button.set_valign(Gtk.Align.CENTER)
        if css_class:
            button.add_css_class(css_class)
        button.connect("clicked", handler)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        return row

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
        self._apply_sync(snapshot.sync_status)
        self._apply_overview(snapshot.branch_overview)
        self._block_selection_signal = False

    def _apply_sync(self, status):
        tone, title, description = main_sync.verdict(status)
        self.verdict_row.set_title(GLib.markup_escape_text(title))
        self.verdict_row.set_subtitle(GLib.markup_escape_text(description))
        self.verdict_icon.set_from_icon_name(_VERDICT_ICONS[status.state])
        for css_class in _TONE_CLASSES.values():
            self.verdict_icon.remove_css_class(css_class)
        self.verdict_icon.add_css_class(_TONE_CLASSES[tone])
        self.sync_button.set_visible(status.state != main_sync.UNAVAILABLE)
        if status.state == main_sync.CATCH_UP:
            self.sync_button.add_css_class("suggested-action")
        else:
            self.sync_button.remove_css_class("suggested-action")
        while (row := self.refs_list.get_row_at_index(0)) is not None:
            self.refs_list.remove(row)
        for ref in status.refs:
            self.refs_list.append(SyncRefRow(ref))
        self.refs_list.set_visible(bool(status.refs))
        freshness_tone, freshness_text = overview_core.describe_freshness(status)
        self.freshness_label.set_label(freshness_text)
        for css_class in _TONE_CLASSES.values():
            self.freshness_label.remove_css_class(css_class)
        self.freshness_label.add_css_class(_TONE_CLASSES[freshness_tone])

    def _apply_overview(self, overview):
        for row in self._all_branch_rows:
            self.all_branches_row.remove(row)
        self._all_branch_rows = [BranchComparisonRow(branch, overview) for branch in overview.branches]
        for row in self._all_branch_rows:
            self.all_branches_row.add_row(row)
        self.all_branches_row.set_subtitle(
            _("{0} branches, each against its copy on origin and against {1}").format(
                len(overview.branches), overview.base_ref or "main"
            )
        )

    def set_fetching(self, is_fetching):
        self.fetch_button.set_sensitive(not is_fetching)
        self.sync_button.set_sensitive(not is_fetching)

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

    def on_fetch_clicked(self, button):
        self.emit("fetch-requested")

    def on_sync_clicked(self, button):
        self.emit("sync-requested")

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

    def on_create_branch_clicked(self, button):
        self.emit("create-branch-requested")

    def on_rename_branch_clicked(self, button):
        self.emit("rename-branch-requested")

    def on_delete_branch_clicked(self, button):
        self.emit("delete-branch-requested")

    def on_switch_main_clicked(self, button):
        """Route switching to main through the window's reviewed branch flow."""
        if self.current_branch != "main":
            self.emit("branch-selected", "main")
