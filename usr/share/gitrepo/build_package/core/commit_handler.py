# intentional-log: the CLI adapter reports the requested commit result to stdout.
#
# core/commit_handler.py - Git stage/commit/push logic shared by GUI and CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

from gitrepo.common import child_process as subprocess

from .git_utils import GitUtils
from .repository_lock import journey
from gitrepo.common.translation import _

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
            "diagnosis": _("Authentication failed - credentials may be expired or invalid"),
            "solutions": [
                _("Run 'gh auth login' to authenticate with GitHub CLI"),
                _("Check if your SSH key is added: {0}").format("ssh -T git@github.com"),
                _("For HTTPS, run: git credential reject"),
                _("Generate a new Personal Access Token on GitHub"),
            ],
        }

    # Remote branch ahead (need to pull)
    if any(x in error_lower for x in ["non-fast-forward", "updates were rejected", "fetch first"]):
        return {
            "diagnosis": _("Remote branch has changes you don't have locally"),
            "solutions": [
                _("Use 'Download updates' first (git fetch followed by git merge)"),
                _("Or run: git pull --rebase origin {0}").format(branch),
                _("Then try pushing again"),
            ],
        }

    # Protected branch
    if any(x in error_lower for x in ["protected branch", "required status", "review required"]):
        return {
            "diagnosis": _("This branch has protection rules - direct push is not allowed"),
            "solutions": [
                _("Push to a development branch instead (e.g., dev-yourname)"),
                _("Create a Pull Request to merge your changes"),
                _("Ask a maintainer to temporarily disable branch protection"),
            ],
        }

    # Network errors
    if any(x in error_lower for x in ["could not resolve", "network", "connection refused", "timed out"]):
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
                _("Try: git push --set-upstream origin {0}").format(f"refs/heads/{branch}:refs/heads/{branch}"),
                _("Or verify you have commits on this branch"),
            ],
        }

    # Default / unknown error
    return {
        "diagnosis": _("Push failed with error: {0}").format(error_output[:200]),
        "solutions": [
            _("Check the error message above for details"),
            _("Try running 'git push' in terminal to see full output"),
            _("Check GitHub status: {0}").format("https://githubstatus.com"),
        ],
    }


# ---------------------------------------------------------------------------
# Commit + push
# ---------------------------------------------------------------------------


def _log(bp, style: str, message: str) -> None:
    """Write through the configured logger, with a small CLI fallback."""
    if getattr(bp, "logger", None):
        bp.logger.log(style, message)
    else:
        print(f"[{style}] {message}")


def _stage_changes(bp) -> None:
    """Stage the complete working tree or raise with Git's diagnostic."""
    result = subprocess.run_git(["git", "add", "-A"], capture_output=True, text=True, check=False, intent="ordinary")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
        raise RuntimeError(_("Failed to stage changes: {0}").format(detail))
    _log(bp, "green", _("✓ Changes staged"))


def _create_commit(bp, message: str) -> bool:
    """Create one commit and report whether Git produced a new object."""
    result = subprocess.run_git(
        ["git", "commit", "-m", message], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode == 0:
        _log(bp, "green", _("✓ Commit created successfully"))
        return True
    detail = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
    if "nothing to commit" in detail.lower():
        _log(bp, "yellow", _("No changes to commit"))
        return False
    raise RuntimeError(_("Failed to create commit: {0}").format(detail))


def _sync_branch(bp, branch: str) -> None:
    """Integrate remote work without rewriting either side's history."""
    divergence = GitUtils.check_branch_divergence(branch)
    if divergence.get("error"):
        _log(bp, "yellow", _("Could not verify remote state: {0}").format(divergence["error"]))
        return
    if not divergence.get("diverged") and divergence.get("behind", 0) == 0:
        _log(bp, "green", _("✓ Already in sync with remote"))
        return
    for method in ("rebase", "merge"):
        if GitUtils.resolve_divergence(branch, method, bp.logger, bp.menu):
            _log(bp, "green", _("✓ Remote changes integrated with {0}").format(method))
            return
    # Last resort before asking for manual work: an announced merge that keeps
    # this branch wherever the two disagree.
    if GitUtils.resolve_divergence(
        branch, "merge-keep-current", bp.logger, bp.menu, getattr(bp, "conflict_resolver", None)
    ):
        _log(bp, "green", _("✓ Remote changes integrated keeping {0}").format(branch))
        return
    raise RuntimeError(_("Remote changes conflict with the local branch; resolve them manually."))


def _record_unpublished_commit(bp, branch: str, *, deliberate: bool = False) -> None:
    """Record the local branch tip that has not reached the remote yet.

    The same state is reached two ways: a push that failed, and a commit the
    user asked to keep local. Both leave work only this machine knows about, so
    both are recorded identically and are resumable by the same retry path —
    only the wording changes, because one is a setback and the other a choice.
    """
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    retry_command = f"git push -u origin {refspec}"
    commit_sha = GitUtils.get_head_sha()
    current_branch = GitUtils.get_current_branch() or branch
    bp.last_operation_details = {
        "local_commit_created": commit_sha,
        "current_branch": current_branch,
        "remote_unchanged": True,
        "retry_command": retry_command,
        "commit_only": deliberate,
    }
    if deliberate:
        _log(bp, "yellow", _("The commit {0} is local only; origin/{1} is unchanged.").format(commit_sha[:12], branch))
        _log(bp, "cyan", _("Publish it later with: {0}").format(retry_command))
        return
    _log(bp, "yellow", _("The commit {0} was created locally and was kept.").format(commit_sha[:12]))
    _log(bp, "cyan", _("Retry publishing it with: {0}").format(retry_command))


def _push_branch(bp, branch: str) -> None:
    """Push one branch and translate common remote failures into next steps."""
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    result = subprocess.run_git(
        ["git", "push", "-u", "origin", refspec],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        details = getattr(bp, "last_operation_details", {})
        if details.get("local_commit_created") and details.get("current_branch") == branch:
            bp.last_operation_details = {}
        _log(bp, "green", _("✓ Pushed to origin/{0}").format(branch))
        return
    detail = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
    diagnosis = analyze_push_error(detail, branch)
    _log(bp, "red", diagnosis["diagnosis"])
    for solution in diagnosis["solutions"]:
        _log(bp, "white", f"• {solution}")
    _record_unpublished_commit(bp, branch)
    raise RuntimeError(diagnosis["diagnosis"])


def publish_existing_commit(bp, branch: str, *, sync: bool = False) -> bool:
    """Push the current branch tip without creating another commit.

    Set *sync* when nothing has integrated the remote yet, as for a commit the
    user deliberately kept local: the push would be rejected as soon as origin
    moved on. Callers that already synchronized — the retry after a failed push
    — leave it off so the branch is not touched a second time.

    Work in progress is set aside for the duration of that integration. Having
    edits on top of an unpublished commit is the normal state here, and Git
    refuses `pull --rebase` outright while the tree is dirty; a plain merge only
    survives it while the incoming files happen not to overlap.
    """
    if not sync:
        _push_branch(bp, branch)
        _log(bp, "green", _("Existing local commit published to origin/{0}.").format(branch))
        return True

    from .branch_handler import _stash_working_tree

    stashed = _stash_working_tree(branch)
    if stashed:
        _log(bp, "cyan", _("Uncommitted changes were set aside while the remote is integrated."))
    try:
        _sync_branch(bp, branch)
        _push_branch(bp, branch)
    finally:
        # Restoring runs even when publishing failed: work left in a stash
        # entry nobody mentioned is work the user cannot find.
        if stashed:
            _restore_stashed_work(bp, branch)
    _log(bp, "green", _("Existing local commit published to origin/{0}.").format(branch))
    return True


def _restore_stashed_work(bp, branch: str) -> None:
    """Return the set-aside work, naming where it is if it cannot be applied.

    A failure here must not replace the error that publishing raised, nor turn
    a completed push into one: the commit did reach origin, and the pending
    edits are still recoverable by name.
    """
    from .branch_handler import _restore_working_tree

    try:
        _restore_working_tree(bp, branch, branch)
    except (RuntimeError, subprocess.SubprocessError) as error:
        _log(bp, "yellow", _("Your uncommitted changes are kept in git stash: {0}").format(error))
        _log(bp, "cyan", _("Recover them with: {0}").format("git stash pop"))
        return
    _log(bp, "green", _("✓ Uncommitted changes restored"))


@journey("publishing changes", False)
def execute_commit(bp, commit_message: str, target_branch: str | None = None, *, push: bool = True) -> bool:
    """Stage, commit, and — unless *push* is false — publish the selected branch.

    Refuses an unresolved merge before staging: `git add -A` would otherwise
    stage the conflict markers themselves, `git commit` would complete the merge
    around them, and the push would publish them. The CLI journey has always
    refused this; the GUI reaches this function directly, so the guard belongs
    here rather than in one caller.

    With ``push=False`` the function stops after the commit and skips the remote
    entirely — no fetch, no merge, no push. Nothing is left half-done, so the
    branch stays exactly where the commit put it and remains publishable later
    through :func:`publish_existing_commit`.
    """
    branch = target_branch or GitUtils.get_current_branch()
    if not branch:
        raise RuntimeError(_("Could not determine branch name for push"))
    resolver = getattr(bp, "conflict_resolver", None)
    if resolver and resolver.has_conflicts() and not resolver.resolve():
        _log(bp, "red", _("Resolve all conflicts before committing."))
        return False
    _stage_changes(bp)
    if not _create_commit(bp, commit_message):
        return True
    if not push:
        # Syncing with the remote is part of publishing, not of committing:
        # a rebase or merge here would rewrite or extend history the user
        # asked to keep untouched until they decide to publish.
        _record_unpublished_commit(bp, branch, deliberate=True)
        _log(bp, "green", _("Committed locally on {0}; nothing was pushed").format(branch))
        return True
    try:
        _sync_branch(bp, branch)
    except (RuntimeError, subprocess.SubprocessError):
        _record_unpublished_commit(bp, branch)
        raise
    _push_branch(bp, branch)
    _log(bp, "green", _("Changes published to {0} with git commit and git push").format(branch))
    return True
