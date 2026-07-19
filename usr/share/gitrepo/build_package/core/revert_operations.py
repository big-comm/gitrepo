#
# core/revert_operations.py - Commit revert and reset operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git

from .git_utils import GitUtils
from gitrepo.common.translation import _

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def revert_commit_menu(bp) -> None:
    """Display a reviewed revert or reset flow."""
    if not bp.is_git_repo:
        bp.logger.log("red", _("This operation is only available in git repositories."))
        return
    current_branch = GitUtils.get_current_branch()
    own_branch = f"dev-{bp.github_user_name or 'unknown'}"
    if current_branch not in ("main", own_branch):
        bp.logger.log("red", _("You can only revert commits on your own branch ({0}) or main.").format(own_branch))
        return
    revert_method = _choose_revert_method(bp, current_branch, own_branch)
    if not revert_method:
        return
    selected_commit = _choose_revert_commit(bp, revert_method)
    if not selected_commit:
        return
    show_revert_preview(bp, selected_commit, revert_method)
    question = _("Proceed with {0} on {1}?").format(revert_method, selected_commit["hash"][:7])
    if not bp.menu.confirm(question, default_yes=False):
        bp.logger.log("yellow", _("Operation cancelled by user."))
        return
    success = execute_revert(bp, selected_commit, revert_method, current_branch, confirmed=True)
    if not success:
        bp.logger.log("red", _("Failed to {0} commit.").format(revert_method))
        return
    details = getattr(bp, "last_revert_details", {})
    show_operation_summary(bp, revert_method, selected_commit, details)
    if hasattr(bp, "last_revert_details"):
        delattr(bp, "last_revert_details")


def _choose_revert_method(bp, current_branch, own_branch):
    if current_branch == "main":
        bp.logger.log("cyan", _("Shared main branch: only the history-preserving revert method is available."))
        return "revert"
    result = bp.menu.show_menu(
        _("Branch: {0} - Select revert method").format(own_branch),
        [_("Revert (keep history)"), _("Reset (remove from history)"), _("Back")],
    )
    if result is None or result[0] == 2:
        return ""
    return "revert" if result[0] == 0 else "reset"


def _choose_revert_commit(bp, revert_method):
    commits = get_recent_commits(bp, 10)
    if not commits:
        bp.logger.log("yellow", _("No commits found to revert."))
        return None
    options = [
        f"{commit['hash'][:7]} - {commit['author']} - {commit['date']}\n    {commit['message'][:60]}"
        for commit in commits
    ]
    result = bp.menu.show_menu(
        _("Select commit to revert ({0})").format(revert_method),
        options + [_("Back")],
    )
    return None if result is None or result[0] == len(commits) else commits[result[0]]


# Commit listing
# ---------------------------------------------------------------------------


def get_recent_commits(bp, count: int = 10) -> list:
    """Return the *count* most recent commits as a list of dicts."""
    try:
        result = subprocess.run_git(
            ["git", "log", f"-{count}", "--pretty=format:%H|%an|%ad|%s", "--date=short"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            intent="ordinary",
        )
        commits = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("|", 3)
                if len(parts) == 4:
                    commits.append(
                        {
                            "hash": parts[0],
                            "author": parts[1],
                            "date": parts[2],
                            "message": parts[3],
                        }
                    )
        return commits
    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error getting commit history: {0}").format(e))
        return []
    except Exception as e:
        bp.logger.log("red", _("Unexpected error getting commits: {0}").format(e))
        return []


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def show_revert_preview(bp, commit: dict, revert_method: str) -> None:
    """Log a visual preview of what will change."""
    try:
        commit_hash = commit["hash"]
        short_hash = commit_hash[:7]

        current_commit_result = subprocess.run_git(
            ["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, text=True, check=True, intent="ordinary"
        )
        current_commit = current_commit_result.stdout.strip()[:7]

        preview_data = [
            (_("Target Commit Hash"), short_hash),
            (_("Author"), commit["author"]),
            (_("Date"), commit["date"]),
            (_("Message"), commit["message"]),
            (_("Method"), revert_method.upper()),
        ]

        if revert_method == "revert":
            preview_data.append((_("Result"), _("Code will be restored to this commit's exact state")))
            preview_data.append((_("New Commit"), _("Will create new commit with restored state")))
            preview_data.append((_("History"), _("All commits remain in history (non-destructive)")))
            preview_data.append((_("Current Code"), f"From {current_commit} → To {short_hash}"))
        else:
            preview_data.append((_("Result"), _("Repository will be reset to this commit")))
            preview_data.append((_("History"), _("Commits after this will be removed from history")))

        bp.logger.display_summary(_("Revert Preview"), preview_data)

        if revert_method == "revert":
            try:
                diff_result = subprocess.run_git(
                    ["git", "diff", "--name-status", commit_hash, "HEAD"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True,
                    intent="ordinary",
                )
                if diff_result.stdout.strip():
                    bp.logger.log("cyan", _("Files that will be restored to target state:"))
                    diff_lines = diff_result.stdout.strip().split("\n")
                    for line in diff_lines[:10]:
                        if line.strip():
                            status = line[0] if line else ""
                            filename = line[2:] if len(line) > 2 else ""
                            status_text = {"M": "Modified", "A": "Added", "D": "Deleted"}.get(status, status)
                            bp.logger.log("white", f"  {status_text}: {filename}")
                    if len(diff_lines) > 10:
                        bp.logger.log("yellow", f"  ... and {len(diff_lines) - 10} more files")
                else:
                    bp.logger.log("yellow", _("No differences detected - code is already at target state"))
            except subprocess.CalledProcessError:
                bp.logger.log("yellow", _("Could not analyze file differences"))

    except subprocess.CalledProcessError as e:
        bp.logger.log("yellow", _("Could not show commit details: {0}").format(e))
    except Exception as e:
        bp.logger.log("yellow", _("Error showing preview: {0}").format(e))


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def execute_revert(bp, commit: dict, revert_method: str, current_branch: str, *, confirmed: bool = False) -> bool:
    """Perform the revert or reset and return success status."""
    if not confirmed:
        bp.logger.log("yellow", _("Operation requires explicit confirmation."))
        return False
    try:
        commit_hash = commit["hash"]
        short_hash = commit_hash[:7]

        remote_exists = check_commit_in_remote(commit_hash)
        bp.logger.log("cyan", _("Executing {0} for commit {1}...").format(revert_method, short_hash))

        if revert_method == "revert":
            success = _execute_revert_method(bp, commit_hash, current_branch, remote_exists, confirmed=confirmed)
        else:
            success = _execute_reset_method(bp, commit_hash, current_branch, remote_exists, confirmed=confirmed)

        if success:
            details = getattr(bp, "last_operation_details", {})
            bp.last_revert_details = details
            if hasattr(bp, "last_operation_details"):
                delattr(bp, "last_operation_details")

        return success

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if hasattr(e, "stderr") and e.stderr else str(e)
        bp.logger.log("red", _("Error during {0}: {1}").format(revert_method, error_msg))
        _cleanup_revert_state()
        return False
    except Exception as e:
        bp.logger.log("red", _("Unexpected error during {0}: {1}").format(revert_method, str(e)))
        return False


def _execute_revert_method(
    bp, commit_hash: str, current_branch: str, remote_exists: bool, *, confirmed: bool = False
) -> bool:
    """Restore the working tree to *commit_hash* and create a new commit."""
    if not confirmed:
        return False
    try:
        bp.logger.log("cyan", _("Getting commit information..."))
        commit_message_result = subprocess.run_git(
            ["git", "log", "-1", "--pretty=format:%s", commit_hash],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
            intent="ordinary",
        )
        original_message = commit_message_result.stdout.strip()

        bp.logger.log("cyan", _("Restoring code state from selected commit..."))
        with authorize_destructive_git():
            subprocess.run_git(["git", "checkout", commit_hash, "--", "."], check=True, intent="destructive")

        bp.logger.log("cyan", _("Staging restored files..."))
        subprocess.run_git(["git", "add", "--", "."], check=True, intent="ordinary")

        status_result = subprocess.run_git(
            ["git", "status", "--porcelain"], stdout=subprocess.PIPE, text=True, check=True, intent="ordinary"
        )
        if not status_result.stdout.strip():
            bp.logger.log("yellow", _("No changes detected - code is already at selected state"))
            return True

        new_commit_message = (
            f"Revert to: {original_message}\n\nThis restores the complete state from commit {commit_hash[:7]}."
        )
        bp.logger.log("cyan", _("Creating revert commit..."))
        subprocess.run_git(["git", "commit", "-m", new_commit_message], check=True, intent="ordinary")

        bp.logger.log("green", _("Revert completed successfully - code restored to selected commit state"))
        return _push_revert_changes(bp, current_branch, remote_exists)

    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error during revert operation: {0}").format(e))
        _cleanup_revert_state()
        return False
    except Exception as e:
        bp.logger.log("red", _("Unexpected error during revert: {0}").format(e))
        return False


def _execute_reset_method(
    bp, commit_hash: str, current_branch: str, remote_exists: bool, *, confirmed: bool = False
) -> bool:
    """Hard-reset to *commit_hash* and optionally force-push."""
    if not confirmed:
        return False
    bp.logger.log("cyan", _("Resetting to previous commit..."))
    with authorize_destructive_git():
        subprocess.run_git(["git", "reset", "--hard", commit_hash], check=True, intent="destructive")

    details = {}
    if remote_exists:
        bp.logger.log("yellow", _("Commit exists in remote - force push required"))
        if bp.menu.confirm(_("This will force push and rewrite remote history. Continue?"), default_yes=False):
            bp.logger.log("cyan", _("Force pushing changes..."))
            with authorize_destructive_git():
                subprocess.run_git(
                    [
                        "git",
                        "push",
                        "origin",
                        f"refs/heads/{current_branch}:refs/heads/{current_branch}",
                        "--force",
                    ],
                    check=True,
                    intent="destructive",
                )
            bp.logger.log("green", _("Reset completed and force pushed"))
            details["force_pushed"] = True
        else:
            bp.logger.log("yellow", _("Reset completed locally only (remote unchanged)"))
            details["local_only"] = True
    else:
        bp.logger.log("green", _("Reset completed (commit was only local)"))
        details["local_only"] = True

    bp.last_operation_details = details
    return True


def _push_revert_changes(bp, current_branch: str, remote_exists: bool) -> bool:
    """Push the revert commit when the original commit was in the remote."""
    if not remote_exists:
        bp.logger.log("green", _("Revert completed (commit was only local)"))
        return True

    bp.logger.log("cyan", _("Pushing revert changes..."))
    push_result = subprocess.run_git(
        ["git", "push", "origin", f"refs/heads/{current_branch}:refs/heads/{current_branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if push_result.returncode == 0:
        bp.logger.log("green", _("Revert changes pushed successfully"))
        return True

    bp.logger.log(
        "red",
        _("Failed to push revert: {0}").format(push_result.stderr.strip() if push_result.stderr else "Unknown error"),
    )
    return False


def _cleanup_revert_state() -> None:
    """Abort any in-progress revert or reset."""
    subprocess.run_git(["git", "revert", "--abort"], capture_output=True, check=False, intent="ordinary")
    subprocess.run_git(["git", "reset", "--abort"], capture_output=True, check=False, intent="ordinary")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def show_operation_summary(bp, operation_type: str, commit_info: dict, details: dict = None) -> None:
    """Report the observable post-operation HEAD and publication scope."""
    head = _git_output(["git", "rev-parse", "--short", "HEAD"]) or _("unknown")
    rows = [
        (_("Operation"), operation_type),
        (_("Target Commit"), commit_info["hash"][:7]),
        (_("Target Message"), commit_info["message"]),
        (_("Current HEAD"), head),
    ]
    if details and details.get("force_pushed"):
        rows.append((_("Remote"), _("Force-pushed after explicit confirmation")))
    elif details and details.get("local_only"):
        rows.append((_("Remote"), _("Unchanged; reset is local only")))
    else:
        rows.append((_("Remote"), _("Updated without rewriting history")))
    bp.logger.display_summary(_("Operation completed"), rows)


def _git_output(command):
    result = subprocess.run_git(command, capture_output=True, text=True, check=False, intent="ordinary")
    return result.stdout.strip() if result.returncode == 0 else ""


def execute_revert_by_hash(bp, commit_hash: str, revert_method: str, *, confirmed: bool = False) -> bool:
    """Execute revert/reset using a raw commit hash (bridge for GUI signals).

    The GUI emits (commit_hash: str, method: str) while :func:`execute_revert`
    expects a commit dict.  This helper builds the dict and resolves the current
    branch so callers don't have to duplicate that logic.
    """
    if not confirmed:
        bp.logger.log("yellow", _("Operation requires explicit confirmation."))
        return False
    current_branch = GitUtils.get_current_branch()
    if not current_branch:
        bp.logger.log("red", _("✗ Could not determine current branch"))
        return False

    try:
        result = subprocess.run_git(
            ["git", "log", "-1", "--pretty=format:%an|%ad|%s", "--date=short", commit_hash],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode == 0 and result.stdout.strip():
            author, date, message = result.stdout.strip().split("|", 2)
        else:
            author, date, message = "unknown", "", "unknown"
    except (ValueError, subprocess.SubprocessError):
        author, date, message = "unknown", "", "unknown"

    commit = {"hash": commit_hash, "author": author, "date": date, "message": message}
    return execute_revert(bp, commit, revert_method, current_branch, confirmed=confirmed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def check_commit_in_remote(commit_hash: str) -> bool:
    """Return True if *commit_hash* appears in any remote-tracking branch."""
    try:
        result = subprocess.run_git(
            ["git", "branch", "-r", "--contains", commit_hash],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            intent="ordinary",
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return True  # Assume remote if undetermined (safer)
