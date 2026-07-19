"""Repository overview with adaptive status and workflow cards."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.common.translation import _
from gi.repository import Adw, GObject, Gtk, Pango

from gitrepo.common.page_hero import BuildPackagePageHero as PageHero, github_action_description


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

    def update_value(self, value: str) -> None:
        text = str(value)
        self.value_label.set_text(text)
        self.value_label.update_property([Gtk.AccessibleProperty.LABEL], [f"{self._title}: {text}"])

    def set_state(self, icon_name: str, css_class: str | None = None, tooltip: str | None = None) -> None:
        for candidate in ("status-ok", "status-warning", "status-error"):
            self.state_icon.remove_css_class(candidate)
        self.state_icon.set_from_icon_name(icon_name)
        if css_class:
            self.state_icon.add_css_class(css_class)
        self.state_icon.set_tooltip_text(tooltip)


class OverviewWidget(Gtk.Box):
    """Task-focused dashboard backed by a repository snapshot."""

    __gsignals__ = {
        "quick-action": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, build_package) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.build_package = build_package
        self._changed_file_rows = []
        self.create_ui()

    def create_ui(self) -> None:
        refresh_content = Adw.ButtonContent(label=_("Refresh"), icon_name="view-refresh-symbolic")
        refresh_button = Gtk.Button(child=refresh_content)
        refresh_button.add_css_class("pill")
        refresh_button.set_tooltip_text(_("Refresh repository status"))
        refresh_button.connect("clicked", self.on_refresh_clicked)

        hero = PageHero(
            "build-package-overview",
            _("Repository workspace"),
            _("Checking repository state…"),
            refresh_button,
        )
        self.hero_subtitle = hero.description_label
        self.append(hero)

        self.page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.page_content.add_css_class("page-frame")
        self.append(self.page_content)

        self.page_content.append(self._create_status_section())
        self._create_changed_files()
        self._create_quick_actions()
        self._create_recent_activity()

    def _create_status_section(self) -> Gtk.Widget:
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Label(label=_("Repository Status"), xalign=0)
        heading.add_css_class("section-heading")
        status_box.append(heading)

        status_grid = Gtk.FlowBox()
        status_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        status_grid.set_min_children_per_line(1)
        status_grid.set_max_children_per_line(3)
        status_grid.set_homogeneous(True)
        status_grid.set_column_spacing(12)
        status_grid.set_row_spacing(12)
        status_grid.add_css_class("build-package-status-grid")

        self.branch_status = StatusCard(_("Branch"), "build-package-branches")
        self.changes_status = StatusCard(_("Changes"), "build-package-repository")
        self.commits_status = StatusCard(_("Commits"), "build-package-commit")
        status_grid.insert(self.branch_status, -1)
        status_grid.insert(self.changes_status, -1)
        status_grid.insert(self.commits_status, -1)
        status_box.append(status_grid)
        return status_box

    def _create_changed_files(self) -> None:
        self.changed_files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Label(label=_("Changed Files"), xalign=0)
        heading.add_css_class("section-heading")
        self.changed_files_box.append(heading)

        self.changed_files_expander = Adw.ExpanderRow()
        self.changed_files_expander.set_title(_("View changed files"))
        self.changed_files_expander.set_subtitle(_("Expand to review the working tree"))
        changed_list = Gtk.ListBox()
        changed_list.set_selection_mode(Gtk.SelectionMode.NONE)
        changed_list.add_css_class("premium-list")
        changed_list.append(self.changed_files_expander)
        self.changed_files_box.append(changed_list)
        self.changed_files_box.set_visible(False)
        self.page_content.append(self.changed_files_box)

    def _create_quick_actions(self) -> None:
        actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Label(label=_("Quick Actions"), xalign=0)
        heading.add_css_class("section-heading")
        actions_box.append(heading)

        self.quick_actions_flow = Gtk.FlowBox()
        self.quick_actions_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.quick_actions_flow.set_min_children_per_line(2)
        self.quick_actions_flow.set_max_children_per_line(2)
        self.quick_actions_flow.set_homogeneous(True)
        self.quick_actions_flow.set_column_spacing(12)
        self.quick_actions_flow.set_row_spacing(12)
        self.quick_actions_flow.add_css_class("build-package-destinations")
        actions_box.append(self.quick_actions_flow)
        self.page_content.append(actions_box)
        self.refresh_quick_actions()

    def _create_destination_card(self, icon_name: str, title: str, subtitle: str, action_id: str) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_halign(Gtk.Align.FILL)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(30)
        icon.set_halign(Gtk.Align.START)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(icon)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        title_label.set_hexpand(True)
        title_label.set_valign(Gtk.Align.CENTER)
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        heading.append(title_label)
        content.append(heading)

        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("dim-label")
        subtitle_label.add_css_class("caption")
        subtitle_label.set_wrap(True)
        subtitle_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        subtitle_label.set_width_chars(1)
        subtitle_label.set_max_width_chars(38)
        subtitle_label.set_yalign(0)
        content.append(subtitle_label)

        button = Gtk.Button(child=content)
        button.add_css_class("build-package-destination-card")
        button.set_tooltip_text(title)
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])
        button.connect("clicked", lambda _button: self.emit("quick-action", action_id))
        return button

    def _create_recent_activity(self) -> None:
        activity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Label(label=_("Recent Activity"), xalign=0)
        heading.add_css_class("section-heading")
        activity_box.append(heading)

        activity_list = Gtk.ListBox()
        activity_list.set_selection_mode(Gtk.SelectionMode.NONE)
        activity_list.add_css_class("premium-list")
        self.activity_row = Adw.ActionRow(
            title=_("No recent activity"),
            subtitle=_("Activity will appear here after operations"),
        )
        activity_icon = Gtk.Image.new_from_icon_name("build-package-commit")
        activity_icon.set_pixel_size(24)
        activity_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.activity_row.add_prefix(activity_icon)
        activity_list.append(self.activity_row)
        activity_box.append(activity_list)
        self.page_content.append(activity_box)

    def apply_snapshot(self, snapshot) -> None:
        repository = (
            snapshot.repository_name.split("/")[-1]
            if snapshot.is_repository and snapshot.repository_name
            else (_("Local repository") if snapshot.is_repository else _("Not a Git repository"))
        )
        branch = _("Detached HEAD") if snapshot.is_detached else snapshot.branch or _("Unknown")
        self.branch_status.update_value(branch)
        self.commits_status.update_value("—" if snapshot.commit_count is None else str(snapshot.commit_count))
        self.quick_actions_flow.set_sensitive(snapshot.is_repository and snapshot.has_changes is not None)

        if not snapshot.is_repository:
            self._apply_non_repository_snapshot()
        elif snapshot.has_changes is None:
            self._apply_unavailable_status_snapshot(repository)
        elif snapshot.has_changes:
            self._apply_changed_snapshot(repository, branch, snapshot.changed_files)
        else:
            self._apply_clean_snapshot(repository, branch)
        self.update_recent_activity(snapshot)

    def _apply_non_repository_snapshot(self) -> None:
        self.hero_subtitle.set_text(_("Open GitRepo from a Git repository to enable repository actions."))
        self.branch_status.set_state("gitrepo-status-error-symbolic", "status-error", _("Not a Git repository"))
        self.changes_status.update_value(_("Unavailable"))
        self.changes_status.set_state(
            "gitrepo-status-error-symbolic", "status-error", _("Repository status unavailable")
        )
        self.commits_status.set_state("gitrepo-status-error-symbolic", "status-error", _("Commit history unavailable"))
        self.changed_files_box.set_visible(False)

    def _apply_unavailable_status_snapshot(self, repository: str) -> None:
        self.hero_subtitle.set_text(_("{0} • repository status is unavailable").format(repository))
        self.branch_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Active branch detected"))
        self.changes_status.update_value(_("Unavailable"))
        self.changes_status.set_state(
            "gitrepo-status-warning-symbolic", "status-warning", _("Repository status unavailable")
        )
        self.commits_status.set_state(
            "gitrepo-status-warning-symbolic", "status-warning", _("Commit count may be stale")
        )
        self.changed_files_box.set_visible(False)

    def _apply_changed_snapshot(self, repository: str, branch: str, changed_files: tuple[tuple[str, str], ...]) -> None:
        count = len(changed_files)
        self.hero_subtitle.set_text(_("{0} • branch {1} • {2} changed file(s)").format(repository, branch, count))
        self.branch_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Active branch detected"))
        self.changes_status.update_value(str(count))
        self.changes_status.set_state(
            "gitrepo-status-warning-symbolic", "status-warning", _("Uncommitted changes present")
        )
        self.commits_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Commit history available"))
        self._update_changed_files_list(changed_files)

    def _apply_clean_snapshot(self, repository: str, branch: str) -> None:
        self.hero_subtitle.set_text(_("{0} • branch {1} • working tree clean").format(repository, branch))
        self.branch_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Active branch detected"))
        self.changes_status.update_value(_("No changes"))
        self.changes_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Working tree clean"))
        self.commits_status.set_state("gitrepo-status-ready-symbolic", "status-ok", _("Commit history available"))
        self.changed_files_box.set_visible(False)

    def _update_changed_files_list(self, changed_files) -> None:
        for row in self._changed_file_rows:
            self.changed_files_expander.remove(row)
        self._changed_file_rows = []
        labels = {
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
            row = Adw.ActionRow(title=filepath, subtitle=labels.get(status, status))
            if status == "D":
                icon_name = "edit-delete-symbolic"
            elif status in ("A", "AM", "??"):
                icon_name = "list-add-symbolic"
            elif status in ("R", "C"):
                icon_name = "edit-copy-symbolic"
            else:
                icon_name = "document-edit-symbolic"
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(icon)
            self.changed_files_expander.add_row(row)
            self._changed_file_rows.append(row)
        count = len(changed_files)
        self.changed_files_expander.set_title(_("{0} changed file(s)").format(count))
        self.changed_files_expander.set_subtitle(_("Expand to review the working tree"))
        self.changed_files_box.set_visible(count > 0)

    def update_recent_activity(self, snapshot) -> None:
        if not snapshot.last_commit:
            self.activity_row.set_title(_("No commits yet"))
            self.activity_row.set_subtitle(_("Create your first commit to start tracking activity"))
            return
        _commit_hash, message = snapshot.last_commit.split("|", 1)
        self.activity_row.set_title(_("Last commit"))
        self.activity_row.set_subtitle(message)

    def _quick_actions(self):
        actions = [
            (
                "pull",
                _("Download updates"),
                _(
                    "Download and combine the remote branch.\n\n"
                    "Git commands:\n{0}\n{1}\n"
                    "Local changes are preserved during the update."
                ).format("git fetch origin BRANCH", "git merge --no-edit origin/BRANCH"),
                "build-package-pull",
            ),
            (
                "commit",
                _("Publish changes"),
                _("Record and send pending changes.\n\nGit commands:\n{0}\n{1}\n{2}").format(
                    "git add -A", 'git commit -m "MESSAGE"', "git push -u origin BRANCH"
                ),
                "build-package-commit",
            ),
        ]
        settings = self.build_package.settings
        if settings.get("package_features_enabled", False):
            actions.extend(
                [
                    (
                        "package_testing",
                        _("Test a package"),
                        github_action_description(_("build and publish the package in the testing repository")),
                        "build-package-testing",
                    ),
                    (
                        "package_stable",
                        _("Publish a stable package"),
                        github_action_description(_("build and publish the package in the stable repository")),
                        "build-package-stable",
                    ),
                ]
            )
        if settings.get("aur_features_enabled", False):
            actions.append(
                (
                    "aur",
                    _("Build from the AUR"),
                    github_action_description(_("build a package from the selected community source")),
                    "build-package-aur",
                )
            )
        return actions

    def refresh_quick_actions(self) -> None:
        child = self.quick_actions_flow.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.quick_actions_flow.remove(child)
            child = next_child
        for action_id, title, description, icon_name in self._quick_actions():
            self.quick_actions_flow.insert(
                self._create_destination_card(icon_name, title, description, action_id),
                -1,
            )

    def on_refresh_clicked(self, _button) -> None:
        self.emit("refresh-requested")
