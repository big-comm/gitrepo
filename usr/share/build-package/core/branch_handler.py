#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/branch_handler.py - Branch-switching and commit flow
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

import subprocess

from .commit_handler import execute_commit
from .git_utils import GitUtils
from .translation_utils import _


def switch_and_commit(bp, target_branch: str, commit_message: str) -> bool:
    """Stash → switch branch → sync remote → restore stash → commit + push → return.

    Extracted from ``MainWindow._switch_then_commit``.

    Flow:
    1. Stash changes
    2. Switch to *target_branch* (create if needed)
    3. Sync target branch with remote (pull --rebase) — BEFORE restoring stash
    4. Restore stash (user's changes on top of up-to-date branch)
    5. Commit + push via :func:`commit_handler.execute_commit`
    6. Return to original branch
    7. Merge target into original branch (keep dev in sync)

    Args:
        bp: BuildPackage instance — provides ``bp.logger``.
        target_branch: Branch to switch to before committing.
        commit_message: The commit message text.

    Returns:
        True on success; raises on unrecoverable failure.
    """
    has_changes = GitUtils.has_changes()
    logger = bp.logger if hasattr(bp, "logger") else None

    def log(style: str, msg: str) -> None:
        if logger:
            logger.log(style, msg)
        else:
            print("[{0}] {1}".format(style, msg))

    stashed = False
    original_branch = GitUtils.get_current_branch()

    try:
        log("cyan", _("Preparing branch switch..."))
        log("dim", f"    From: {original_branch} → To: {target_branch}")

        # === Step 1: Stash changes ===
        if has_changes:
            log("cyan", _("Stashing local changes..."))
            stash_result = subprocess.run(
                [
                    "git",
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    f"auto-stash-commit-to-{target_branch}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if stash_result.returncode == 0:
                stashed = True
                log("green", _("✓ Changes stashed"))
            else:
                log("yellow", _("⚠ Could not stash (continuing anyway)"))

        # === Step 2: Switch to target branch ===
        log("cyan", _("Switching to branch {0}...").format(target_branch))

        local_check = subprocess.run(
            ["git", "rev-parse", "--verify", target_branch],
            capture_output=True,
            check=False,
        )
        remote_check = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{target_branch}"],
            capture_output=True,
            check=False,
        )

        if remote_check.returncode == 0 and local_check.returncode != 0:
            log(
                "cyan",
                _("Creating local branch from remote: {0}").format(target_branch),
            )
            checkout_result = subprocess.run(
                ["git", "checkout", "-b", target_branch, f"origin/{target_branch}"],
                capture_output=True,
                text=True,
                check=False,
            )
        elif local_check.returncode == 0 or remote_check.returncode == 0:
            checkout_result = subprocess.run(
                ["git", "checkout", target_branch],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            log("cyan", _("Creating new branch: {0}").format(target_branch))
            checkout_result = subprocess.run(
                ["git", "checkout", "-b", target_branch],
                capture_output=True,
                text=True,
                check=False,
            )

        if checkout_result.returncode != 0:
            error_msg = (
                checkout_result.stderr.strip() or checkout_result.stdout.strip()
            )
            log("red", _("✗ Failed to switch branch: {0}").format(error_msg))
            if stashed:
                subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
                log("yellow", _("Restored stashed changes"))
            raise Exception(_("Failed to switch to branch {0}").format(target_branch))

        log("green", _("✓ Switched to {0}").format(target_branch))

        # === Step 3: Sync target branch with remote BEFORE restoring stash ===
        log("cyan", _("Syncing {0} with remote...").format(target_branch))
        subprocess.run(
            ["git", "fetch", "origin", target_branch],
            capture_output=True,
            text=True,
            check=False,
        )

        divergence = GitUtils.check_branch_divergence(target_branch)
        is_protected = target_branch in ("main", "master")

        if divergence.get("behind", 0) > 0 or divergence.get("diverged"):
            behind = divergence.get("behind", 0)
            log("cyan", _("Pulling {0} commit(s) from remote...").format(behind))

            sync_result = subprocess.run(
                ["git", "pull", "--rebase", "origin", target_branch],
                capture_output=True,
                text=True,
                check=False,
            )

            if sync_result.returncode == 0:
                log("green", _("✓ Synced with remote"))
            else:
                subprocess.run(
                    ["git", "rebase", "--abort"], capture_output=True, check=False
                )
                log("yellow", _("⚠ Rebase failed, trying merge..."))

                sync_result = subprocess.run(
                    ["git", "pull", "--no-rebase", "origin", target_branch],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if sync_result.returncode == 0:
                    log("green", _("✓ Merged with remote"))
                elif is_protected:
                    # Protected branches (main/master): remote is source of truth
                    subprocess.run(
                        ["git", "merge", "--abort"], capture_output=True, check=False
                    )
                    log(
                        "yellow",
                        _("⚠ Local {0} diverged from remote — resetting to remote version").format(
                            target_branch
                        ),
                    )
                    reset_result = subprocess.run(
                        ["git", "reset", "--hard", f"origin/{target_branch}"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if reset_result.returncode == 0:
                        log("green", _("✓ {0} reset to origin/{0}").format(target_branch))
                    else:
                        log("red", _("✗ Could not reset {0}").format(target_branch))
                        log("yellow", _("Returning to {0}...").format(original_branch))
                        subprocess.run(
                            ["git", "checkout", original_branch],
                            capture_output=True,
                            check=False,
                        )
                        if stashed:
                            subprocess.run(
                                ["git", "stash", "pop"], capture_output=True, check=False
                            )
                            log("yellow", _("Restored stashed changes"))
                        raise Exception(
                            _("Failed to sync {0} with remote").format(target_branch)
                        )
                else:
                    subprocess.run(
                        ["git", "merge", "--abort"], capture_output=True, check=False
                    )
                    log(
                        "red",
                        _("✗ Could not sync {0} with remote").format(target_branch),
                    )
                    log("yellow", _("Returning to {0}...").format(original_branch))
                    subprocess.run(
                        ["git", "checkout", original_branch],
                        capture_output=True,
                        check=False,
                    )
                    if stashed:
                        subprocess.run(
                            ["git", "stash", "pop"], capture_output=True, check=False
                        )
                        log("yellow", _("Restored stashed changes"))
                    raise Exception(
                        _(
                            "Failed to sync {0} with remote - please sync manually first"
                        ).format(target_branch)
                    )
        else:
            log("green", _("✓ Already in sync with remote"))

        # === Step 4: Restore stash ===
        if stashed:
            log("cyan", _("Restoring stashed changes..."))
            pop_result = subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True,
                check=False,
            )
            if pop_result.returncode == 0:
                log("green", _("✓ Stash restored"))
            else:
                log(
                    "yellow",
                    _("⚠ Conflicts while restoring stash - please resolve manually"),
                )

        # === Step 5: Commit + push ===
        result = execute_commit(bp, commit_message, target_branch)

        # === Step 6: Return to original branch ===
        if original_branch and original_branch != target_branch:
            log("cyan", _("Returning to {0}...").format(original_branch))
            back_result = subprocess.run(
                ["git", "checkout", original_branch],
                capture_output=True,
                text=True,
                check=False,
            )
            if back_result.returncode == 0:
                log("green", _("✓ Returned to {0}").format(original_branch))

                # === Step 7: Merge target into original branch ===
                log(
                    "cyan",
                    _("Syncing {0} with {1}...").format(original_branch, target_branch),
                )
                merge_result = subprocess.run(
                    ["git", "merge", target_branch, "--no-edit"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if merge_result.returncode == 0:
                    log(
                        "green",
                        _("✓ {0} is now in sync with {1}").format(
                            original_branch, target_branch
                        ),
                    )
                    # Push synced branch to remote
                    push_sync = subprocess.run(
                        ["git", "push", "-u", "origin", original_branch],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if push_sync.returncode == 0:
                        log("green", _("✓ {0} pushed to remote").format(original_branch))
                    else:
                        log(
                            "yellow",
                            _("⚠ Could not push {0} — you can push later").format(
                                original_branch
                            ),
                        )
                else:
                    log(
                        "yellow",
                        _(
                            "⚠ Could not auto-sync {0} — you can sync later with Pull"
                        ).format(original_branch),
                    )
                    subprocess.run(
                        ["git", "merge", "--abort"], capture_output=True, check=False
                    )
            else:
                log(
                    "yellow",
                    _("⚠ Could not return to {0} — still on {1}").format(
                        original_branch, target_branch
                    ),
                )

        return result

    except subprocess.CalledProcessError as e:
        log("red", _("Error: {0}").format(str(e)))
        if stashed:
            subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
            log("yellow", _("Restored stashed changes"))
        raise


# ---------------------------------------------------------------------------
# Undo last commit
# ---------------------------------------------------------------------------

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

    result = subprocess.run(
        ["git", "reset", "HEAD~1"], capture_output=True, text=True, check=False
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
            subprocess.run(
                ["git", "checkout", source_branch], capture_output=True, check=True
            )

        # Step 2: Create the new branch from source
        log("cyan", _("Creating branch: {0}").format(target_branch))
        log("dim", f"    git checkout -b {target_branch}")

        result = subprocess.run(
            ["git", "checkout", "-b", target_branch],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            log("red", _("Failed to create branch: {0}").format(result.stderr))
            return False

        log("green", _("✓ Branch '{0}' created").format(target_branch))

        # Step 3: Push to remote
        log("cyan", _("Pushing to remote..."))
        log("dim", f"    git push -u origin {target_branch}")

        push_result = subprocess.run(
            ["git", "push", "-u", "origin", target_branch],
            capture_output=True,
            text=True,
            check=False,
        )

        if push_result.returncode != 0:
            log("red", _("Push failed: {0}").format(push_result.stderr))
            return False

        log(
            "green",
            _("✓ Successfully pushed '{0}' to remote!").format(target_branch),
        )
        log(
            "green",
            _("✓ All code from '{0}' is now in '{1}'").format(
                source_branch, target_branch
            ),
        )
        return True

    except subprocess.CalledProcessError as e:
        log("red", _("Error: {0}").format(str(e)))
        return False


# ---------------------------------------------------------------------------
# Configure git remote and push
# ---------------------------------------------------------------------------

def configure_remote_and_push(bp, url: str) -> bool:
    """Add (or update) *origin* remote URL and push current branch.

    Args:
        bp: BuildPackage instance — provides ``bp.logger``.
        url: Repository URL to set as *origin*.

    Returns:
        True on success, False on failure.
    """
    logger = bp.logger if hasattr(bp, "logger") else None

    def log(style: str, msg: str) -> None:
        if logger:
            logger.log(style, msg)

    log("cyan", _("Configuring remote origin..."))
    log("dim", f"    git remote add origin {url}")

    # Add or update remote
    result = subprocess.run(
        ["git", "remote", "add", "origin", url],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        if "already exists" in result.stderr:
            log("yellow", _("Remote 'origin' already exists, updating URL..."))
            result = subprocess.run(
                ["git", "remote", "set-url", "origin", url],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                log("red", _("Failed to update remote: {0}").format(result.stderr))
                return False
        else:
            log("red", _("Failed to add remote: {0}").format(result.stderr))
            return False

    log("green", _("✓ Remote origin configured successfully"))

    # Push current branch
    current_branch = GitUtils.get_current_branch() or "main"
    log("cyan", _("Pushing to remote..."))
    log("dim", f"    git push -u origin {current_branch}")

    push_result = subprocess.run(
        ["git", "push", "-u", "origin", current_branch],
        capture_output=True,
        text=True,
        check=False,
    )

    if push_result.returncode != 0:
        log("red", _("Push failed: {0}").format(push_result.stderr))
        log("yellow", _("You may need to create the repository on GitHub first"))
        return False

    log("green", _("✓ Successfully pushed to remote!"))
    return True


def switch_branch(
    bp,
    target_branch: str,
    stash_first: bool = False,
    discard_first: bool = False,
) -> dict:
    """Execute branch switch handling stash/discard; return result dict for UI feedback.

    Returns:
        {'success': bool, 'message': str, 'message_type': 'toast'|'error'|'info'}
    """
    import subprocess

    stashed = False

    def _ok(msg: str, t: str = "toast") -> dict:
        return {"success": True, "message": msg, "message_type": t}

    def _err(msg: str) -> dict:
        return {"success": False, "message": msg, "message_type": "error"}

    try:
        # Step 1: Handle local changes
        if discard_first:
            subprocess.run(["git", "checkout", "--", "."], check=True, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True)
        elif stash_first:
            stash_result = subprocess.run(
                [
                    "git",
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    f"auto-stash-before-switch-to-{target_branch}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if stash_result.returncode != 0:
                return _err(_("Failed to stash changes"))
            stashed = True

        # Step 2: Resolve checkout strategy (local / remote-tracking / new)
        local_ok = subprocess.run(
            ["git", "rev-parse", "--verify", target_branch],
            capture_output=True,
            check=False,
        ).returncode == 0
        remote_ok = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{target_branch}"],
            capture_output=True,
            check=False,
        ).returncode == 0

        if remote_ok and not local_ok:
            cmd = ["git", "checkout", "-b", target_branch, f"origin/{target_branch}"]
        elif local_ok or remote_ok:
            cmd = ["git", "checkout", target_branch]
        else:
            cmd = ["git", "checkout", "-b", target_branch]

        checkout_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if checkout_result.returncode != 0:
            if stashed:
                subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
            return _err(checkout_result.stderr.strip())

        # Step 3: Restore stash
        if stashed:
            pop_result = subprocess.run(
                ["git", "stash", "pop"], capture_output=True, text=True, check=False
            )
            if pop_result.returncode != 0:
                conflict = "CONFLICT" in pop_result.stdout or "CONFLICT" in pop_result.stderr
                if conflict:
                    return _ok(
                        _("Switched to {0}. Conflicts detected - resolve manually.").format(
                            target_branch
                        ),
                        "info",
                    )
                return _ok(
                    _("Switched to {0}. Check 'git stash list' for your changes.").format(
                        target_branch
                    ),
                    "info",
                )
            return _ok(_("Switched to {0} with your changes restored.").format(target_branch))

        return _ok(_("Switched to branch: {0}").format(target_branch))

    except subprocess.CalledProcessError as e:
        return _err(_("Error switching branch: {0}").format(str(e)))

