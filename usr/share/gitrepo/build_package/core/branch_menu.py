# intentional-log: the CLI branch menu reports every outcome to the user.
#
# core/branch_menu.py - Interactive branch management for the CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

from rich.console import Group
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from gitrepo.common.translation import _

from . import branch_overview as overview_core
from . import main_sync
from .branch_handler import create_branch, delete_branch, describe_branch, rename_branch, switch_branch
from .git_utils import PROTECTED_BRANCHES, GitUtils


def _ask_branch_name(prompt: str) -> str:
    """Read a branch name; an empty answer cancels."""
    return Prompt.ask(prompt, default="", show_default=False).strip()


def _pick_branch(bp, title: str, branches: list[str], default: str = "") -> str:
    """Offer *branches* in an arrow-key menu; return "" when the user backs out."""
    if not branches:
        bp.logger.log("yellow", _("No branch is eligible for this operation."))
        return ""
    options = [*branches, _("Back")]
    default_index = branches.index(default) if default in branches else 0
    result = bp.menu.show_menu(title, options, default_index=default_index)
    if result is None or result[0] == len(branches):
        return ""
    return branches[result[0]]


def _all_branches() -> tuple[list[str], list[str], str]:
    local = GitUtils.list_local_branches()
    remote = GitUtils.list_remote_branches()
    return local, remote, GitUtils.get_current_branch()


def branch_menu(bp) -> None:
    """Switch, create, rename or delete branches with the commands spelled out."""
    if not bp.is_git_repo:
        bp.logger.log("red", _("This operation is only available in Git repositories."))
        return
    actions = (
        (_("Sync with main (is my work in main?)"), _sync_flow),
        (_("Switch branch"), _switch_branch_flow),
        (_("Create branch"), _create_branch_flow),
        (_("Rename branch"), _rename_branch_flow),
        (_("Delete branch"), _delete_branch_flow),
        (_("Back"), None),
    )
    while True:
        current = GitUtils.get_current_branch() or _("Detached HEAD")
        result = bp.menu.show_menu(
            _("Branches"),
            [label for label, _flow in actions],
            additional_content=_("Current branch: {0}").format(current),
        )
        if result is None or actions[result[0]][1] is None:
            return
        actions[result[0]][1](bp)


# Rich styles for the semantic tones of core/branch_overview.py.
_TONE_STYLES = {
    overview_core.TONE_OK: "bold green",
    overview_core.TONE_AHEAD: "bold cyan",
    overview_core.TONE_BEHIND: "bold yellow",
    overview_core.TONE_DIVERGED: "bold red",
    overview_core.TONE_NEUTRAL: "dim",
}


def _tone_text(tone: str, text: str) -> Text:
    """A coloured label led by a symbol, so the state reads without colour too."""
    return Text(f"{overview_core.TONE_GLYPHS[tone]} {text}", style=_TONE_STYLES[tone])


def _tip_cell(tip) -> Text:
    if tip is None:
        return Text("—", style="dim")
    return Text(tip.short_sha, style="magenta")


def _freshness(status_or_overview) -> Text:
    tone, text = overview_core.describe_freshness(status_or_overview)
    return Text(text, style=_TONE_STYLES[tone])


def _overview_renderable(overview) -> Group:
    """Lay every branch out as one table plus the freshness of origin and a legend."""
    table = Table(box=None, pad_edge=False, header_style="bold", expand=False)
    table.add_column("", width=1)
    table.add_column(_("Branch"), no_wrap=True)
    table.add_column(_("Local"), no_wrap=True)
    table.add_column("origin", no_wrap=True)
    table.add_column(_("Local × origin"), no_wrap=True)
    table.add_column(_("× {0}").format(overview.base_ref or "main"), no_wrap=True)
    for branch in overview.branches:
        # Text, not markup: a branch name is shown exactly as it is named.
        name = Text(branch.name, style="bold bright_white" if branch.is_current else "white")
        table.add_row(
            Text("●", style="bold green") if branch.is_current else Text(""),
            name,
            _tip_cell(branch.local),
            _tip_cell(branch.remote),
            _tone_text(*overview_core.describe_vs_remote(branch)),
            _tone_text(*overview_core.describe_vs_base(branch, overview)),
        )
    legend = Text()
    for tone, meaning in overview_core.legend():
        legend.append_text(_tone_text(tone, meaning))
        legend.append("   ")
    return Group(table, Text(""), _freshness(overview), legend)


def _sync_renderable(status) -> Group:
    """The verdict in words first, then the four copies it was drawn from."""
    tone, title, description = main_sync.verdict(status)
    parts = [_tone_text(tone, title), Text(description), Text("")]
    if status.refs:
        table = Table(box=None, pad_edge=False, header_style="bold", expand=False)
        table.add_column(_("Copy"), no_wrap=True)
        table.add_column(_("Commit"), no_wrap=True)
        table.add_column(_("Situation"), no_wrap=True)
        table.add_column(_("Last commit"), overflow="ellipsis", no_wrap=True, max_width=48)
        for ref in status.refs:
            table.add_row(
                Text(ref.label, style="bold"),
                _tip_cell(ref.tip),
                _tone_text(*main_sync.describe_ref(ref)),
                Text(ref.tip.subject if ref.tip else "", style="dim"),
            )
        parts.extend([table, Text("")])
    parts.append(_freshness(status))
    return Group(*parts)


def _pause() -> None:
    Prompt.ask(_("Press Enter to continue"), default="", show_default=False)


def _all_branches_flow(bp) -> None:
    overview = overview_core.capture_branch_overview()
    if overview.error:
        bp.logger.log("red", _("Could not read the branches of this repository."))
        return
    bp.menu.show_menu(_("All branches"), [_("Back")], additional_content=_overview_renderable(overview))


def _sync_flow(bp) -> None:
    """Say whether the branch is in main, and align every copy on request."""
    options = [
        _("Synchronize with origin/main (git fetch, then fast-forward)"),
        _("Only check origin (git fetch --prune origin)"),
        _("Show all branches"),
        _("Back"),
    ]
    while True:
        status = main_sync.capture_sync_status()
        default = 0 if status.state == main_sync.CATCH_UP else 3
        result = bp.menu.show_menu(
            _("Sync with main"), options, default_index=default, additional_content=_sync_renderable(status)
        )
        if result is None or result[0] == 3:
            return
        if result[0] == 0:
            main_sync.sync_with_main(bp)
            _pause()
        elif result[0] == 1:
            bp.logger.log("cyan", _("Running git fetch --prune origin..."))
            success, error = overview_core.fetch_origin()
            if not success:
                bp.logger.log("red", _("git fetch failed: {0}").format(error or _("unknown error")))
                _pause()
        else:
            _all_branches_flow(bp)


def _switch_branch_flow(bp) -> None:
    local, remote, current = _all_branches()
    candidates = sorted(set(local + remote) - {current})
    target = _pick_branch(bp, _("Select branch to check out (git checkout BRANCH)"), candidates)
    if not target:
        return
    stash_first = discard_first = False
    if GitUtils.has_changes():
        choice = bp.menu.show_menu(
            _("You have uncommitted changes. What should happen to them?"),
            [
                _("Preserve files and switch (git stash → git checkout → git stash pop)"),
                _("Discard files and switch (git checkout -- . → git clean -fd)"),
                _("Cancel"),
            ],
        )
        if choice is None or choice[0] == 2:
            bp.logger.log("yellow", _("Branch switch cancelled."))
            return
        stash_first = choice[0] == 0
        discard_first = choice[0] == 1
        if discard_first and not bp.menu.confirm(
            _("Permanently discard all uncommitted changes and untracked files?"), default_yes=False
        ):
            bp.logger.log("yellow", _("Branch switch cancelled."))
            return
    result = switch_branch(bp, target, stash_first=stash_first, discard_first=discard_first)
    bp.logger.log("green" if result["success"] else "red", result["message"])


def _create_branch_flow(bp) -> None:
    local, remote, current = _all_branches()
    new_name = _ask_branch_name(_("New branch name (empty to cancel)"))
    if not new_name:
        return
    if not GitUtils.is_valid_branch_name(new_name):
        bp.logger.log("red", _("Invalid branch name: {0}").format(new_name))
        return
    if new_name in local or new_name in remote:
        bp.logger.log("red", _("A branch named '{0}' already exists.").format(new_name))
        return
    source = _pick_branch(bp, _("Create from which branch?"), sorted(set(local + remote)), default=current)
    if not source:
        return
    checkout = bp.menu.confirm(_("Switch to '{0}' after creating it?").format(new_name), default_yes=True)
    publish = bp.menu.confirm(
        _("Publish '{0}' to origin now? (git push -u origin {0})").format(new_name), default_yes=False
    )
    steps = [f"git branch {new_name} {source}"]
    if checkout:
        steps.append(f"git checkout {new_name}")
    if publish:
        steps.append(f"git push -u origin {new_name}")
    if not bp.menu.confirm(_("Run: {0}?").format(" → ".join(steps)), default_yes=True):
        bp.logger.log("yellow", _("Branch creation cancelled."))
        return
    create_branch(bp, new_name, source, checkout=checkout, publish=publish)


def _rename_branch_flow(bp) -> None:
    local, remote, current = _all_branches()
    candidates = [branch for branch in local if branch not in PROTECTED_BRANCHES]
    old_name = _pick_branch(bp, _("Select branch to rename"), candidates, default=current)
    if not old_name:
        return
    new_name = _ask_branch_name(_("New name for '{0}' (empty to cancel)").format(old_name))
    if not new_name:
        return
    if not GitUtils.is_valid_branch_name(new_name):
        bp.logger.log("red", _("Invalid branch name: {0}").format(new_name))
        return
    if new_name in local or new_name in remote:
        bp.logger.log("red", _("A branch named '{0}' already exists.").format(new_name))
        return
    rename_remote = False
    steps = [f"git branch -m {old_name} {new_name}"]
    if old_name in remote:
        rename_remote = bp.menu.confirm(
            _(
                "'{0}' is also on origin. Rename it there too?\n"
                "This publishes '{1}' and deletes origin/{0}; anyone tracking the old name loses it."
            ).format(old_name, new_name),
            default_yes=False,
        )
        if rename_remote:
            steps.extend([f"git push -u origin {new_name}", f"git push origin --delete {old_name}"])
    if not bp.menu.confirm(_("Run: {0}?").format(" → ".join(steps)), default_yes=True):
        bp.logger.log("yellow", _("Branch rename cancelled."))
        return
    rename_branch(bp, old_name, new_name, rename_remote=rename_remote)


def _delete_branch_flow(bp) -> None:
    local, remote, current = _all_branches()
    candidates = sorted((set(local) | set(remote)) - PROTECTED_BRANCHES - {current})
    branch = _pick_branch(bp, _("Select branch to delete"), candidates)
    if not branch:
        return
    facts = describe_branch(branch)
    force = False
    if facts["unmerged_commits"]:
        bp.logger.log(
            "red",
            _("'{0}' holds {1} commit(s) that are not in {2}. Deleting it loses them.").format(
                branch, facts["unmerged_commits"], facts["base_label"]
            ),
        )
        force = bp.menu.confirm(_("Delete '{0}' anyway and lose those commits?").format(branch), default_yes=False)
        if not force:
            bp.logger.log("yellow", _("Branch deletion cancelled."))
            return
    elif not facts["base"]:
        bp.logger.log(
            "yellow", _("No main or master branch to compare against; '{0}' cannot be proven merged.").format(branch)
        )
        force = bp.menu.confirm(_("Delete '{0}' anyway?").format(branch), default_yes=False)
        if not force:
            bp.logger.log("yellow", _("Branch deletion cancelled."))
            return
    delete_remote = False
    steps = [f"git branch -D {branch}"] if facts["local"] else []
    if facts["remote"]:
        delete_remote = bp.menu.confirm(
            _("'{0}' is also on origin. Delete origin/{0} too?").format(branch), default_yes=False
        )
        if delete_remote:
            steps.append(f"git push origin --delete {branch}")
    if not steps:
        bp.logger.log("yellow", _("Nothing to delete: origin/{0} was kept.").format(branch))
        return
    if not bp.menu.confirm(_("Permanently run: {0}?").format(" → ".join(steps)), default_yes=False):
        bp.logger.log("yellow", _("Branch deletion cancelled."))
        return
    delete_branch(bp, branch, delete_remote=delete_remote, force=force)
