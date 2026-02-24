#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/commit_handler.py - Git stage/commit/push logic shared by GUI and CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

import subprocess

from .git_utils import GitUtils
from .translation_utils import _

# ---------------------------------------------------------------------------
# Push error diagnosis
# ---------------------------------------------------------------------------

def analyze_push_error(error_output: str, branch: str) -> dict:
    """Return a diagnosis + solutions dict for a *git push* error string."""
    error_lower = error_output.lower()

    # Authentication errors
    if any(
        x in error_lower
        for x in [
            "authentication",
            "permission denied",
            "403",
            "401",
            "could not read username",
        ]
    ):
        return {
            "diagnosis": _(
                "Authentication failed - credentials may be expired or invalid"
            ),
            "solutions": [
                _("Run 'gh auth login' to authenticate with GitHub CLI"),
                _("Check if your SSH key is added: ssh -T git@github.com"),
                _("For HTTPS, run: git credential reject"),
                _("Generate a new Personal Access Token on GitHub"),
            ],
        }

    # Remote branch ahead (need to pull)
    if any(
        x in error_lower
        for x in ["non-fast-forward", "updates were rejected", "fetch first"]
    ):
        return {
            "diagnosis": _("Remote branch has changes you don't have locally"),
            "solutions": [
                _("Use 'Pull Latest' button first to get remote changes"),
                _("Or run: git pull --rebase origin {0}").format(branch),
                _("Then try pushing again"),
            ],
        }

    # Protected branch
    if any(
        x in error_lower
        for x in ["protected branch", "required status", "review required"]
    ):
        return {
            "diagnosis": _(
                "This branch has protection rules - direct push is not allowed"
            ),
            "solutions": [
                _("Push to a development branch instead (e.g., dev-yourname)"),
                _("Create a Pull Request to merge your changes"),
                _("Ask a maintainer to temporarily disable branch protection"),
            ],
        }

    # Network errors
    if any(
        x in error_lower
        for x in ["could not resolve", "network", "connection refused", "timed out"]
    ):
        return {
            "diagnosis": _("Network error - cannot reach remote server"),
            "solutions": [
                _("Check your internet connection"),
                _("Try again in a few moments"),
                _("Check if GitHub/remote is accessible"),
            ],
        }

    # Repository access
    if any(x in error_lower for x in ["repository not found", "does not exist"]):
        return {
            "diagnosis": _("Remote repository not found or you don't have access"),
            "solutions": [
                _("Verify the remote URL: git remote -v"),
                _("Check if you have write access to the repository"),
                _("Request access from the repository owner"),
            ],
        }

    # Branch doesn't exist on remote
    if "src refspec" in error_lower and "does not match any" in error_lower:
        return {
            "diagnosis": _("Local branch configuration issue"),
            "solutions": [
                _("Try: git push --set-upstream origin {0}").format(branch),
                _("Or verify you have commits on this branch"),
            ],
        }

    # Default / unknown error
    return {
        "diagnosis": _("Push failed with error: {0}").format(error_output[:200]),
        "solutions": [
            _("Check the error message above for details"),
            _("Try running 'git push' in terminal to see full output"),
            _("Check GitHub status: https://githubstatus.com"),
        ],
    }


# ---------------------------------------------------------------------------
# Commit + push
# ---------------------------------------------------------------------------

def execute_commit(bp, commit_message: str, target_branch: str = None) -> bool:
    """Stage all changes, commit, sync with remote, and push.

    Extracted from ``MainWindow._execute_commit``.  Uses *bp* (a BuildPackage
    instance) only for its *logger* attribute; all git operations run via
    ``subprocess`` and ``GitUtils``.

    Args:
        bp: BuildPackage instance — provides ``bp.logger``.
        commit_message: The commit message text.
        target_branch: Branch to push to.  When *None*, the current branch is
            resolved via ``GitUtils.get_current_branch()``.

    Returns:
        True on success, raises on failure so the caller can show the error.
    """
    logger = bp.logger if hasattr(bp, "logger") else None

    def log(style: str, msg: str) -> None:
        if logger:
            logger.log(style, msg)
        else:
            print("[{0}] {1}".format(style, msg))

    # Resolve branch
    current_branch = target_branch if target_branch else GitUtils.get_current_branch()
    if not current_branch:
        log("red", _("✗ Could not determine branch name!"))
        log("white", _("Please check your git repository state."))
        raise Exception(_("Could not determine branch name for push"))

    # Step 1: Stage all changes
    log("cyan", _("Staging all changes..."))
    try:
        result = subprocess.run(
            ["git", "add", "-A"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            error_msg = (
                result.stderr.strip() or result.stdout.strip() or _("Unknown error")
            )
            log("red", _("Failed to stage changes: {0}").format(error_msg))
            raise Exception(_("Failed to stage changes: {0}").format(error_msg))
        log("green", _("✓ Changes staged"))
    except Exception as e:
        log("red", str(e))
        raise

    # Step 2: Commit
    log("cyan", _("Creating commit..."))
    log(
        "dim",
        f'    git commit -m "{commit_message[:50]}..."'
        if len(commit_message) > 50
        else f'    git commit -m "{commit_message}"',
    )
    try:
        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_msg = (
                result.stderr.strip() or result.stdout.strip() or _("Unknown error")
            )
            if "nothing to commit" in error_msg.lower():
                log("yellow", _("⚠ No changes to commit"))
                return True
            log("red", _("Failed to commit: {0}").format(error_msg))
            raise Exception(_("Failed to commit: {0}").format(error_msg))
        log("green", _("✓ Commit created successfully"))
    except Exception as e:
        if "No changes to commit" not in str(e):
            log("red", str(e))
            raise

    # Step 3: Check for divergence and sync before push
    log("cyan", _("Checking remote status..."))
    divergence = GitUtils.check_branch_divergence(current_branch)

    if divergence.get("error"):
        log(
            "yellow",
            _("⚠ Could not check remote status: {0}").format(divergence["error"]),
        )
        log("dim", _("    Proceeding with push anyway..."))
    elif divergence.get("diverged") or divergence.get("behind", 0) > 0:
        behind_count = divergence.get("behind", 0)
        ahead_count = divergence.get("ahead", 0)

        if divergence.get("diverged"):
            log("yellow", _("⚠ Branch has diverged from remote"))
            log("dim", _("    Local: {0} commit(s) ahead").format(ahead_count))
            log("dim", _("    Remote: {0} commit(s) to sync").format(behind_count))
        else:
            log(
                "cyan",
                _("Remote has {0} new commit(s) - syncing...").format(behind_count),
            )

        log("cyan", _("Pulling with rebase to sync..."))
        log("dim", _("    git pull --rebase origin {0}").format(current_branch))

        if GitUtils.resolve_divergence(current_branch, "rebase", logger):
            log("green", _("✓ Synced with remote successfully"))
        else:
            log("yellow", _("⚠ Rebase had conflicts, trying merge..."))
            if GitUtils.resolve_divergence(current_branch, "merge", logger):
                log("green", _("✓ Merged with remote successfully"))
            else:
                log("red", _("✗ Could not sync with remote automatically"))
                log("white", _("Please resolve conflicts manually and try again"))
                raise Exception(
                    _(
                        "Failed to sync with remote - conflicts need manual resolution"
                    )
                )
    else:
        log("green", _("✓ Already in sync with remote"))

    # Step 4: Push
    log("cyan", _("Pushing to remote..."))
    log("dim", f"    git push -u origin {current_branch}")
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", current_branch],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            error_output = result.stderr.strip() or result.stdout.strip() or ""
            error_info = analyze_push_error(error_output, current_branch)

            log("red", _("✗ Push failed!"))
            log("red", _("Error: {0}").format(error_output))
            log("yellow", "")
            log("yellow", _("═══ Diagnosis ═══"))
            log("orange", error_info["diagnosis"])
            log("yellow", "")
            log("yellow", _("═══ Suggested Solutions ═══"))
            for solution in error_info["solutions"]:
                log("white", f"  • {solution}")

            raise Exception(error_info["diagnosis"])

        log("green", _("✓ Pushed to origin/{0}").format(current_branch))
    except Exception:
        raise

    log("green", "")
    log("green", _("═══ Commit Complete ═══"))
    log("white", _("Branch: {0}").format(current_branch))
    log(
        "white",
        _("Message: {0}").format(
            commit_message[:60] + "..."
            if len(commit_message) > 60
            else commit_message
        ),
    )

    return True
