"""Safe pull journey with preview, stash preservation, and conflict recovery."""

from dataclasses import dataclass

from gitrepo.common import child_process as subprocess

from .git_utils import GitUtils
from .operation_preview import OperationPlan
from .repository_lock import journey
from gitrepo.common.translation import _


@dataclass(frozen=True)
class PullPreview:
    """Immutable remote update reviewed before it touches the worktree."""

    branch: str
    local_head: str
    remote_head: str
    merge_base: str
    changes: tuple[tuple[str, str], ...]


def _remote_branch_exists(branch: str) -> bool:
    result = subprocess.run_git(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _revision(*arguments: str) -> str:
    result = subprocess.run_git(
        ["git", *arguments],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _fetch_remote_branch(bp, branch: str) -> bool:
    result = subprocess.run_git(
        ["git", "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        return True
    bp.logger.log("red", _("Could not fetch origin/{0}: {1}").format(branch, result.stderr.strip()))
    return False


def _create_pull_plan(bp, branch: str, should_stash: bool) -> OperationPlan:
    plan = OperationPlan(
        bp.logger,
        bp.menu,
        show_preview=True,
        dry_run=getattr(bp, "dry_run_mode", False),
    )
    if should_stash:
        plan.add(
            _("Temporarily stash local changes"),
            ["git", "stash", "push", "-u", "-m", f"gitrepo-pull-{branch}"],
        )
    plan.add(
        _("Fetch origin/{0}").format(branch),
        ["git", "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
    )
    plan.add(_("Merge origin/{0} into {0}").format(branch), ["git", "merge", "--no-edit", f"origin/{branch}"])
    return plan


def _create_reviewed_merge_plan(bp, branch: str, should_stash: bool) -> OperationPlan:
    """Create only the worktree-changing steps already accepted in the diff."""
    plan = OperationPlan(
        bp.logger,
        bp.menu,
        show_preview=False,
        dry_run=getattr(bp, "dry_run_mode", False),
    )
    if should_stash:
        plan.add(
            _("Temporarily stash local changes"),
            ["git", "stash", "push", "-u", "-m", f"gitrepo-pull-{branch}"],
        )
    plan.add(_("Merge origin/{0} into {0}").format(branch), ["git", "merge", "--no-edit", f"origin/{branch}"])
    return plan


def _complete_merge_conflict(bp, branch: str) -> bool:
    # One announced decision resolves every file; declining falls back to the
    # per-file review. Either way the discard is never silent.
    resolver = bp.conflict_resolver
    if not resolver.resolve_keeping_current(
        branch, f"origin/{branch}", recovery_hint="git diff HEAD^2 -- FILE"
    ) and not resolver.resolve(branch, f"origin/{branch}"):
        bp.logger.log("red", _("Merge remains incomplete; resolve the listed files manually."))
        return False
    subprocess.run_git(["git", "add", "-A"], check=True, capture_output=True, intent="ordinary")
    result = subprocess.run_git(
        ["git", "commit", "-m", _("Merge origin/{0} after conflict resolution").format(branch)],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode != 0:
        bp.logger.log("red", _("Resolved files could not complete the merge: {0}").format(result.stderr.strip()))
        return False
    return True


def _restore_stash(bp, branch: str) -> bool:
    result = subprocess.run_git(
        ["git", "stash", "pop", "--index"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        bp.logger.log("green", _("Local changes restored."))
        return True
    if bp.conflict_resolver.has_conflicts():
        if bp.conflict_resolver.resolve(branch, _("stashed local changes")):
            subprocess.run_git(
                ["git", "stash", "drop", "stash@{0}"],
                capture_output=True,
                text=True,
                check=False,
                intent="ordinary",
            )
            return True
        return False
    bp.logger.log("red", _("Local changes remain in the stash: {0}").format(result.stderr.strip()))
    return False


@journey("reviewing remote updates", False)
def prepare_pull(build_package_instance) -> PullPreview | bool:
    """Fetch the current remote branch and describe its incoming changes."""
    bp = build_package_instance
    if not bp.is_git_repo:
        bp.logger.log("red", _("This operation is only available in Git repositories."))
        return False
    if bp.conflict_resolver.has_conflicts():
        bp.logger.log("red", _("Resolve the existing conflicts before pulling."))
        return False

    branch = GitUtils.get_current_branch()
    if not branch or not _remote_branch_exists(branch):
        bp.logger.log("yellow", _("The current branch has no matching branch on origin."))
        return False
    if not _fetch_remote_branch(bp, branch):
        return False

    local_head = GitUtils.get_head_sha()
    remote_head = _revision("rev-parse", "--verify", f"origin/{branch}")
    merge_base = _revision("merge-base", local_head, remote_head)
    if not local_head or not remote_head or not merge_base:
        bp.logger.log("red", _("Could not compare the local and remote revisions."))
        return False

    changes = tuple(GitUtils.get_revision_changes(merge_base, remote_head))
    if not changes:
        bp.logger.log("green", _("Repository is already up to date."))
    return PullPreview(branch, local_head, remote_head, merge_base, changes)


@journey("applying reviewed remote updates", False)
def apply_pull_preview(build_package_instance, preview: PullPreview) -> bool:
    """Merge exactly the remote revision accepted in *preview*."""
    bp = build_package_instance
    if not bp.is_git_repo or bp.conflict_resolver.has_conflicts():
        bp.logger.log("red", _("Repository state no longer allows this update. Review it again."))
        return False

    current_branch = GitUtils.get_current_branch()
    current_head = GitUtils.get_head_sha()
    current_remote = _revision("rev-parse", "--verify", f"origin/{preview.branch}")
    if current_branch != preview.branch or current_head != preview.local_head or current_remote != preview.remote_head:
        bp.logger.log("yellow", _("The repository changed after the preview. Review the updates again."))
        return False

    should_stash = GitUtils.has_changes()
    result = _create_reviewed_merge_plan(bp, preview.branch, should_stash).execute()
    if getattr(bp, "dry_run_mode", False):
        return bool(result)
    if result == "conflict" and not _complete_merge_conflict(bp, preview.branch):
        return False
    if result is False:
        if should_stash:
            _restore_stash(bp, preview.branch)
        return False
    if should_stash and not _restore_stash(bp, preview.branch):
        return False

    after = GitUtils.get_head_sha()
    outcome = _("Updated to {0}").format(after[:12]) if preview.local_head != after else _("Already up to date")
    bp.logger.log("green", outcome)
    return True


@journey("downloading updates", False)
def pull_latest(build_package_instance) -> bool:
    """Fetch and merge the current branch while preserving local changes."""
    bp = build_package_instance
    if not bp.is_git_repo:
        bp.logger.log("red", _("This operation is only available in Git repositories."))
        return False
    if bp.conflict_resolver.has_conflicts():
        bp.logger.log("red", _("Resolve the existing conflicts before pulling."))
        return False

    branch = GitUtils.get_current_branch()
    if not branch or not _remote_branch_exists(branch):
        bp.logger.log("yellow", _("The current branch has no matching branch on origin."))
        return False

    before = GitUtils.get_head_sha()
    should_stash = GitUtils.has_changes()
    result = _create_pull_plan(bp, branch, should_stash).execute_with_confirmation()
    if getattr(bp, "dry_run_mode", False):
        return bool(result)
    if result == "conflict" and not _complete_merge_conflict(bp, branch):
        return False
    if result is False:
        if should_stash:
            _restore_stash(bp, branch)
        return False
    if should_stash and not _restore_stash(bp, branch):
        return False

    after = GitUtils.get_head_sha()
    outcome = _("Updated to {0}").format(after[:12]) if before != after else _("Already up to date")
    bp.logger.log("green", outcome)
    return True
