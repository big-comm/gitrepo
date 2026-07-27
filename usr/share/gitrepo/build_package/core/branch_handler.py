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


def _checkout_branch(branch: str) -> bool:
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
    return subprocess.run_git(command, capture_output=True, text=True, check=False, intent="ordinary").returncode == 0


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


@journey("preparing a commit", False)
def switch_and_commit(bp, target_branch: str, commit_message: str) -> bool:
    """Move pending work to an explicit branch, then commit and push it."""
    if not _valid_branch_name(target_branch):
        bp.logger.log("red", _("Invalid target branch: {0}").format(target_branch))
        return False
    original_branch = GitUtils.get_current_branch()
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
        if stashed:
            _restore_working_tree(bp, original_branch, target_branch)
            stashed = False
        from .commit_handler import execute_commit

        return execute_commit(bp, commit_message, target_branch)
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
                _restore_working_tree(bp)
            return _switch_result(False, _("Could not switch branch"), "error")
        if stashed:
            _restore_working_tree(bp)
            return _switch_result(True, _("Switched to {0} with local changes restored.").format(target_branch))
        return _switch_result(True, _("Switched to branch: {0}").format(target_branch))
    except (RuntimeError, subprocess.SubprocessError) as error:
        return _switch_result(False, _("Error switching branch: {0}").format(error), "error")
