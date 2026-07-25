# intentional-log: the CLI adapter reports the requested commit result to stdout.
#
# core/commit_handler.py - Git stage/commit/push logic shared by GUI and CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.

from gitrepo.common import child_process as subprocess

from .git_utils import GitUtils
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


def _push_branch(bp, branch: str) -> None:
    """Push one branch and translate common remote failures into next steps."""
    result = subprocess.run_git(
        ["git", "push", "-u", "origin", f"refs/heads/{branch}:refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        _log(bp, "green", _("✓ Pushed to origin/{0}").format(branch))
        return
    detail = result.stderr.strip() or result.stdout.strip() or _("Unknown error")
    diagnosis = analyze_push_error(detail, branch)
    _log(bp, "red", diagnosis["diagnosis"])
    for solution in diagnosis["solutions"]:
        _log(bp, "white", f"• {solution}")
    raise RuntimeError(diagnosis["diagnosis"])


def execute_commit(bp, commit_message: str, target_branch: str | None = None) -> bool:
    """Stage, commit, integrate remote work, and push the selected branch."""
    branch = target_branch or GitUtils.get_current_branch()
    if not branch:
        raise RuntimeError(_("Could not determine branch name for push"))
    _stage_changes(bp)
    if not _create_commit(bp, commit_message):
        return True
    _sync_branch(bp, branch)
    _push_branch(bp, branch)
    _log(bp, "green", _("Changes published to {0} with git commit and git push").format(branch))
    return True
