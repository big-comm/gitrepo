# intentional-log: branch recovery failures must remain visible to CLI callers.
#
# core/branch_handler.py - Branch-switching and commit flow
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git

from .git_utils import GitUtils
from .repository_lock import journey
from gitrepo.common.translation import _


def _valid_branch_name(branch: str) -> bool:
    return GitUtils.is_valid_branch_name(branch)


def _fetch_remote_branch(branch: str) -> bool:
    """Refresh ``origin/<branch>`` so the checkout sees the published tip."""
    return (
        subprocess.run_git(
            ["git", "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        ).returncode
        == 0
    )


def _fast_forward_to_remote(branch: str) -> None:
    """Advance the checked-out branch to its remote when that loses nothing.

    A stale local branch is the whole problem this guards against: stashed work
    restored onto it lands on files the published branch may have moved or
    deleted, which surfaces as conflicts the user cannot resolve sensibly.
    ``--ff-only`` keeps unpublished local commits untouched — the merge simply
    refuses and the branch stays where it was.
    """
    subprocess.run_git(
        ["git", "merge", "--ff-only", f"origin/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )


def _checkout_branch(branch: str) -> bool:
    fetched = _fetch_remote_branch(branch)
    local = subprocess.run_git(["git", "show-ref", "--verify", f"refs/heads/{branch}"], check=False, intent="ordinary")
    if local.returncode == 0:
        command = ["git", "checkout", branch]
    else:
        remote = subprocess.run_git(
            ["git", "show-ref", "--verify", f"refs/remotes/origin/{branch}"], check=False, intent="ordinary"
        )
        command = (
            ["git", "checkout", "-b", branch, f"origin/{branch}"]
            if remote.returncode == 0
            else ["git", "checkout", "-b", branch]
        )
    if subprocess.run_git(command, capture_output=True, text=True, check=False, intent="ordinary").returncode != 0:
        return False
    if fetched:
        _fast_forward_to_remote(branch)
    return True


def _stash_working_tree(branch: str) -> bool:
    if not GitUtils.has_changes():
        return False
    result = subprocess.run_git(
        ["git", "stash", "push", "-u", "-m", f"gitrepo-switch-{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or _("Could not preserve local changes"))
    return True


def _restore_working_tree(bp, source_branch: str, target_branch: str) -> None:
    result = subprocess.run_git(
        ["git", "stash", "pop", "--index"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        return
    resolver = getattr(bp, "conflict_resolver", None)
    if (
        resolver
        and resolver.has_conflicts()
        and hasattr(resolver, "resolve_stashed_work")
        and resolver.resolve_stashed_work(source_branch, target_branch)
    ):
        bp.logger.log(
            "yellow",
            _("A backup of the transferred work remains in Git stash because conflicts occurred."),
        )
        return
    raise RuntimeError(_("Local changes remain in the stash and need manual resolution."))


def _commits_behind(target_branch: str, source_branch: str) -> int:
    """Count commits *source_branch* has that *target_branch* does not."""
    if not target_branch or not source_branch or target_branch == source_branch:
        return 0
    if not GitUtils.ref_exists(f"refs/heads/{target_branch}"):
        # A branch that does not exist yet is created from here, so it is current.
        return 0
    result = subprocess.run_git(
        ["git", "rev-list", "--count", f"{target_branch}..{source_branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    count = result.stdout.strip() if result.returncode == 0 else ""
    return int(count) if count.isdigit() else 0


def _offer_to_integrate(bp, target_branch: str, source_branch: str, behind: int) -> str:
    """Ask what to do about a target branch that trails the work's own base.

    Returns "integrate", "skip" or "cancel". Work written on top of one branch
    and replayed onto an older one conflicts for a reason that has nothing to do
    with the change itself, and resolving those conflicts by keeping the stashed
    side silently reverts whatever the target had gained meanwhile.
    """
    question = _(
        "Integrate {0} into {1} before committing?\n\n"
        "{1} is {2} commit(s) behind {0}, and your work was written on top of {0}.\n"
        "Committing without integrating makes those files conflict, and keeping "
        "your version can discard what {0} gained meanwhile.\n\n"
        "Commands: git merge {0} → apply your work → git commit"
    ).format(source_branch, target_branch, behind)
    options = [
        _("Integrate {0}, then commit").format(source_branch),
        _("Commit without integrating"),
        _("Cancel"),
    ]
    menu = getattr(bp, "menu", None)
    if menu is None:
        return "integrate"
    if not hasattr(menu, "show_menu"):
        return "integrate" if menu.confirm(question, default_yes=False) else "cancel"
    result = menu.show_menu(question, options, default_index=0)
    if result is None or result[0] == 2:
        return "cancel"
    return "integrate" if result[0] == 0 else "skip"


def _integrate_source_branch(bp, source_branch: str, target_branch: str) -> bool:
    """Merge *source_branch* into the checked-out *target_branch*."""
    bp.logger.log("cyan", _("Integrating {0} into {1}...").format(source_branch, target_branch))
    result = subprocess.run_git(
        ["git", "merge", "--no-edit", source_branch],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        bp.logger.log("green", _("✓ {0} integrated into {1}").format(source_branch, target_branch))
        return True
    resolver = getattr(bp, "conflict_resolver", None)
    if resolver and resolver.has_conflicts() and resolver.resolve():
        bp.logger.log("green", _("✓ {0} integrated into {1}").format(source_branch, target_branch))
        return True
    subprocess.run_git(["git", "merge", "--abort"], capture_output=True, check=False, intent="ordinary")
    detail = (result.stderr or result.stdout).strip()
    bp.logger.log("red", _("Could not integrate {0}: {1}").format(source_branch, detail))
    return False


@journey("preparing a commit", False)
def switch_and_commit(bp, target_branch: str, commit_message: str, *, push: bool = True) -> bool:
    """Move pending work to an explicit branch, then commit and optionally push it."""
    if not _valid_branch_name(target_branch):
        bp.logger.log("red", _("Invalid target branch: {0}").format(target_branch))
        return False
    original_branch = GitUtils.get_current_branch()

    # Decided before anything is stashed or checked out, so cancelling here
    # leaves the working tree exactly as the user left it.
    integrate = False
    behind = _commits_behind(target_branch, original_branch)
    if behind:
        choice = _offer_to_integrate(bp, target_branch, original_branch, behind)
        if choice == "cancel":
            bp.logger.log("yellow", _("Commit cancelled."))
            return False
        integrate = choice == "integrate"
        if not integrate:
            bp.logger.log(
                "yellow",
                _("Committing without integrating; {0} stays {1} commit(s) behind {2}.").format(
                    target_branch, behind, original_branch
                ),
            )

    stashed = False
    try:
        stashed = original_branch != target_branch and _stash_working_tree(target_branch)
        if original_branch != target_branch and not _checkout_branch(target_branch):
            switch_error = _("Could not switch to {0}").format(target_branch)
            if stashed:
                try:
                    _restore_working_tree(bp, original_branch, original_branch)
                    stashed = False
                except RuntimeError as restore_error:
                    raise RuntimeError(_("{0}. {1}").format(switch_error, restore_error)) from restore_error
            raise RuntimeError(switch_error)

        # Before the work is replayed, not after: the merge needs a clean tree,
        # and applying the stash onto the integrated branch is what keeps the
        # conflicts down to the ones the change itself causes.
        if integrate and not _integrate_source_branch(bp, original_branch, target_branch):
            raise RuntimeError(_("Could not integrate {0} into {1}").format(original_branch, target_branch))

        if stashed:
            _restore_working_tree(bp, original_branch, target_branch)
            stashed = False
        from .commit_handler import execute_commit

        return execute_commit(bp, commit_message, target_branch, push=push)
    except (RuntimeError, subprocess.SubprocessError) as error:
        bp.logger.log("red", _("Commit preparation failed: {0}").format(error))
        return False


def undo_last_commit(bp) -> bool:
    """Execute ``git reset HEAD~1`` to undo the last commit (keep changes staged).

    Args:
        bp: BuildPackage instance — provides ``bp.logger``.

    Returns:
        True on success; raises on failure.
    """
    logger = bp.logger if hasattr(bp, "logger") else None

    def log(style: str, msg: str) -> None:
        if logger:
            logger.log(style, msg)
        else:
            print("[{0}] {1}".format(style, msg))

    log("cyan", _("Undoing last commit..."))
    log("dim", "    git reset HEAD~1")

    result = subprocess.run_git(
        ["git", "reset", "HEAD~1"], capture_output=True, text=True, check=False, intent="ordinary"
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        log("red", _("✗ Failed to undo commit: {0}").format(error_msg))
        raise Exception(_("Failed to undo commit: {0}").format(error_msg))

    log("green", _("✓ Last commit undone successfully"))
    log("white", _("Your changes are now in the working directory"))
    log("yellow", _("You can modify files and commit again"))
    return True


# ---------------------------------------------------------------------------
# Create branch and push to remote
# ---------------------------------------------------------------------------


@journey("creating a branch", False)
def create_branch_and_push(bp, source_branch: str, target_branch: str) -> bool:
    """Create *target_branch* from *source_branch* and push to remote.

    Args:
        bp: BuildPackage instance — provides ``bp.logger``.
        source_branch: Branch to branch off from.
        target_branch: Name for the new branch.

    Returns:
        True on success, False on failure.
    """
    logger = bp.logger if hasattr(bp, "logger") else None

    def log(style: str, msg: str) -> None:
        if logger:
            logger.log(style, msg)

    current_branch = GitUtils.get_current_branch()

    try:
        # Step 1: Switch to source branch if not already there
        if current_branch != source_branch:
            log("cyan", _("Switching to source branch: {0}").format(source_branch))
            subprocess.run_git(["git", "checkout", source_branch], capture_output=True, check=True, intent="ordinary")

        # Step 2: Create the new branch from source
        log("cyan", _("Creating branch: {0}").format(target_branch))
        log("dim", f"    git checkout -b {target_branch}")

        result = subprocess.run_git(
            ["git", "checkout", "-b", target_branch], capture_output=True, text=True, check=False, intent="ordinary"
        )

        if result.returncode != 0:
            log("red", _("Failed to create branch: {0}").format(result.stderr))
            return False

        log("green", _("✓ Branch '{0}' created").format(target_branch))

        # Step 3: Push to remote
        refspec = f"refs/heads/{target_branch}:refs/heads/{target_branch}"
        log("cyan", _("Pushing to remote..."))
        log("dim", f"    git push -u origin {refspec}")

        push_result = subprocess.run_git(
            ["git", "push", "-u", "origin", refspec],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )

        if push_result.returncode != 0:
            # The branch exists locally and may already hold work. Saying only
            # "failed" invites the user to delete it and lose that work.
            log("red", _("Push failed: {0}").format(push_result.stderr))
            log("yellow", _("The branch '{0}' exists locally and was kept.").format(target_branch))
            log("cyan", _("Retry publishing it with: git push -u origin {0}").format(refspec))
            bp.last_operation_details = {
                "local_branch_created": target_branch,
                "remote_unchanged": True,
                "retry_command": f"git push -u origin {refspec}",
            }
            return False

        log(
            "green",
            _("✓ Successfully pushed '{0}' to remote!").format(target_branch),
        )
        log(
            "green",
            _("✓ All code from '{0}' is now in '{1}'").format(source_branch, target_branch),
        )
        return True

    except subprocess.CalledProcessError as e:
        log("red", _("Error: {0}").format(str(e)))
        return False


def _switch_result(success: bool, message: str, message_type: str = "toast") -> dict:
    return {"success": success, "message": message, "message_type": message_type}


def switch_branch(bp, target_branch: str, stash_first: bool = False, discard_first: bool = False) -> dict:
    """Switch to a validated branch after the user's explicit preservation choice."""
    if not _valid_branch_name(target_branch):
        return _switch_result(False, _("Invalid branch name"), "error")
    source_branch = GitUtils.get_current_branch()
    try:
        stashed = _stash_working_tree(target_branch) if stash_first else False
        if discard_first:
            with authorize_destructive_git():
                subprocess.run_git(
                    ["git", "checkout", "--", "."], check=True, capture_output=True, intent="destructive"
                )
                subprocess.run_git(["git", "clean", "-fd"], check=True, capture_output=True, intent="destructive")
        if not _checkout_branch(target_branch):
            if stashed:
                _restore_working_tree(bp, source_branch, source_branch)
            return _switch_result(False, _("Could not switch branch"), "error")
        if stashed:
            _restore_working_tree(bp, source_branch, target_branch)
            return _switch_result(True, _("Switched to {0} with local changes restored.").format(target_branch))
        return _switch_result(True, _("Switched to branch: {0}").format(target_branch))
    except (RuntimeError, subprocess.SubprocessError) as error:
        return _switch_result(False, _("Error switching branch: {0}").format(error), "error")
