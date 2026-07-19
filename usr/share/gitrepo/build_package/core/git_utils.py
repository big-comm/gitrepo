#
# git_utils.py - Git repository utilities
#

import os
import re
import shutil

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from gitrepo.common.translation import _


def _branch_names(*command: str) -> list[str]:
    result = subprocess.run_git(["git", *command], capture_output=True, text=True, check=True, intent="ordinary")
    return [
        line.strip().lstrip("* ").removeprefix("origin/")
        for line in result.stdout.splitlines()
        if line.strip() and "->" not in line
    ]


def _obsolete_branches(local: list[str], remote: list[str]) -> tuple[list[str], list[str]]:
    protected = {"main", "master", "dev"}
    development = sorted({branch for branch in local + remote if branch.startswith("dev-")}, reverse=True)
    if development:
        protected.add(development[0])
    return (
        [branch for branch in local if branch not in protected],
        [branch for branch in remote if branch not in protected],
    )


def _delete_local_branches(branches: list[str], available: list[str], logger) -> None:
    current = GitUtils.get_current_branch()
    fallback = "main" if "main" in available else "master" if "master" in available else ""
    for branch in branches:
        try:
            if current == branch and fallback:
                subprocess.run_git(["git", "checkout", fallback], check=True, intent="ordinary")
                current = fallback
            subprocess.run_git(["git", "branch", "-D", branch], check=True, intent="destructive")
        except subprocess.CalledProcessError as error:
            logger.log("red", _("Could not delete local branch {0}: {1}").format(branch, error))


def _delete_remote_branches(branches: list[str], logger) -> None:
    for branch in branches:
        try:
            subprocess.run_git(
                ["git", "push", "origin", "--delete", f"refs/heads/{branch}"],
                check=True,
                intent="destructive",
            )
        except subprocess.CalledProcessError as error:
            logger.log("red", _("Could not delete origin/{0}: {1}").format(branch, error))


def _empty_divergence() -> dict:
    return {
        "diverged": False,
        "ahead": 0,
        "behind": 0,
        "local_commits": [],
        "remote_commits": [],
        "error": None,
    }


def _revision_count(revision_range: str) -> int:
    result = subprocess.run_git(
        ["git", "rev-list", "--count", revision_range], capture_output=True, text=True, check=False, intent="ordinary"
    )
    return int(result.stdout.strip() or "0") if result.returncode == 0 else 0


def _revision_summaries(revision_range: str) -> list[tuple[str, str]]:
    result = subprocess.run_git(
        ["git", "log", "--format=%H%x00%s", revision_range],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    summaries = []
    for line in result.stdout.splitlines() if result.returncode == 0 else []:
        commit, _, summary = line.partition("\0")
        if commit:
            summaries.append((commit, summary))
    return summaries


def _log_if(logger, style: str, message: str) -> None:
    if logger:
        logger.log(style, message)


def _integrate_remote(branch: str, method: str, logger) -> bool:
    option = "--rebase" if method == "rebase" else "--no-rebase"
    result = subprocess.run_git(
        ["git", "pull", option, "origin", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode == 0:
        _log_if(logger, "green", _("Remote changes integrated with {0}.").format(method))
        return True
    abort_verb = "rebase" if method == "rebase" else "merge"
    subprocess.run_git(["git", abort_verb, "--abort"], capture_output=True, check=False, intent="ordinary")
    detail = result.stderr.strip() or result.stdout.strip() or _("Unknown Git error")
    _log_if(logger, "red", _("{0} failed: {1}").format(method.title(), detail))
    return False


def _force_push_with_confirmation(branch: str, logger, menu) -> bool:
    command = [
        "git",
        "push",
        "--force-with-lease",
        "origin",
        f"refs/heads/{branch}:refs/heads/{branch}",
    ]
    question = _("Rewrite origin/{0}?\n{1}").format(branch, " ".join(command))
    if menu is None or not menu.confirm(question, default_yes=False):
        _log_if(logger, "yellow", _("Force push cancelled."))
        return False
    with authorize_destructive_git():
        result = subprocess.run_git(command, capture_output=True, text=True, check=False, intent="destructive")
    if result.returncode == 0:
        _log_if(logger, "green", _("Force push completed."))
        return True
    _log_if(logger, "red", _("Force push failed: {0}").format(result.stderr.strip()))
    return False


class GitUtils:
    """Utilities for Git repository operations"""

    @staticmethod
    def is_git_repo() -> bool:
        """Checks if the current directory is a Git repository"""
        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--is-inside-work-tree"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def has_commits() -> bool:
        """Checks if the repository has at least one commit.

        Returns False for newly created/cloned empty repositories.
        """
        if not GitUtils.is_git_repo():
            return False

        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def get_repo_name() -> str:
        """Gets the repository name"""
        if not GitUtils.is_git_repo():
            return ""

        try:
            result = subprocess.run_git(
                ["git", "config", "--get", "remote.origin.url"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode != 0:
                return ""

            url = result.stdout.strip()

            # Pattern for https or git URLs - handle repo names with dots
            # First, remove .git suffix if present
            if url.endswith(".git"):
                url = url[:-4]

            # Match owner/repo pattern after : or /
            match = re.search(r"[:/]([^/]+/[^/:]+)$", url)
            if match:
                return match.group(1)
            return ""
        except Exception:
            return ""

    @staticmethod
    def get_repo_root_path() -> str:
        """Gets the root path of the Git repository"""
        if not GitUtils.is_git_repo():
            return os.getcwd()

        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--show-toplevel"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode == 0:
                return result.stdout.strip()
            return os.getcwd()
        except Exception:
            return os.getcwd()

    @staticmethod
    def get_github_username() -> str:
        """Resolve a GitHub username from local Git configuration only."""
        configured = subprocess.run_git(
            ["git", "config", "github.user"], capture_output=True, text=True, check=False, intent="ordinary"
        )
        if configured.returncode == 0 and configured.stdout.strip():
            return configured.stdout.strip()
        email_result = subprocess.run_git(
            ["git", "config", "user.email"], capture_output=True, text=True, check=False, intent="ordinary"
        )
        email = email_result.stdout.strip() if email_result.returncode == 0 else ""
        match = re.fullmatch(r"(?:\\d+\\+)?([^@]+)@users\\.noreply\\.github\\.com", email)
        return match.group(1) if match else "unknown"

    @staticmethod
    def has_changes() -> bool:
        """Checks if there are changes in the repository"""
        try:
            # Check if there are changes to commit - simplified and more reliable
            status = subprocess.run_git(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                intent="ordinary",
            ).stdout.strip()

            return bool(status)
        except Exception:
            return False

    @staticmethod
    def get_package_name() -> str:
        """Read the first package name from makepkg's authoritative metadata."""
        repo_path = GitUtils.get_repo_root_path()
        if not os.path.isfile(os.path.join(repo_path, "PKGBUILD")) or shutil.which("makepkg") is None:
            return ""
        try:
            result = subprocess.run(
                ["makepkg", "--printsrcinfo"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode != 0:
            return ""
        for line in result.stdout.splitlines():
            key, separator, value = line.strip().partition(" = ")
            if separator and key == "pkgname":
                return value
        return ""

    @staticmethod
    def cleanup_old_branches(logger, menu) -> bool:
        """Inventory, preview, and delete only confirmed obsolete branches."""
        if not GitUtils.is_git_repo():
            logger.log("red", _("This operation is only available in Git repositories."))
            return False
        try:
            subprocess.run_git(["git", "fetch", "--all", "--prune"], check=True, intent="ordinary")
            local = _branch_names("branch", "--format=%(refname:short)")
            remote = _branch_names("branch", "-r", "--format=%(refname:short)")
            local_to_remove, remote_to_remove = _obsolete_branches(local, remote)
        except subprocess.SubprocessError as error:
            logger.log("red", _("Could not inventory branches: {0}").format(error))
            return False

        candidates = [
            *(f"local: {branch}" for branch in local_to_remove),
            *(f"origin/{branch}" for branch in remote_to_remove),
        ]
        if not candidates:
            logger.log("green", _("No obsolete branches found."))
            return True
        preview = "\\n".join(f"• {candidate}" for candidate in candidates)
        if not menu.confirm(_("Permanently delete these branches?\\n{0}").format(preview), default_yes=False):
            logger.log("yellow", _("Branch cleanup cancelled."))
            return False

        with authorize_destructive_git():
            _delete_local_branches(local_to_remove, local, logger)
            _delete_remote_branches(remote_to_remove, logger)
        logger.log("green", _("Branch cleanup completed."))
        return True

    @staticmethod
    def get_current_branch() -> str:
        """Gets the name of the current branch"""
        if not GitUtils.is_git_repo():
            return ""

        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except Exception:
            return ""

    @staticmethod
    def check_branch_divergence(branch: str | None = None) -> dict:
        """Compare local HEAD with its matching origin branch."""
        state = _empty_divergence()
        if not GitUtils.is_git_repo():
            state["error"] = _("Not a Git repository")
            return state
        branch = branch or GitUtils.get_current_branch()
        if not branch:
            state["error"] = _("Could not determine current branch")
            return state
        if not GitUtils.has_commits():
            return state
        try:
            subprocess.run_git(
                ["git", "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
                capture_output=True,
                check=False,
                intent="ordinary",
            )
            remote = subprocess.run_git(
                ["git", "rev-parse", "--verify", f"origin/{branch}"],
                capture_output=True,
                check=False,
                intent="ordinary",
            )
            if remote.returncode != 0:
                state["ahead"] = 1
                return state
            state["ahead"] = _revision_count(f"origin/{branch}..HEAD")
            state["behind"] = _revision_count(f"HEAD..origin/{branch}")
            state["diverged"] = state["ahead"] > 0 and state["behind"] > 0
            if state["diverged"]:
                state["local_commits"] = _revision_summaries(f"origin/{branch}..HEAD")
                state["remote_commits"] = _revision_summaries(f"HEAD..origin/{branch}")
            return state
        except (subprocess.SubprocessError, ValueError) as error:
            state["error"] = str(error)
            return state

    @staticmethod
    def resolve_divergence(branch: str, method: str, logger=None, menu=None) -> bool:
        """Resolve divergence through an explicit, bounded strategy."""
        if not GitUtils.is_git_repo():
            _log_if(logger, "red", _("Not a Git repository"))
            return False
        if method in {"rebase", "merge"}:
            return _integrate_remote(branch, method, logger)
        if method == "force_push":
            return _force_push_with_confirmation(branch, logger, menu)
        _log_if(logger, "red", _("Unknown resolution method: {0}").format(method))
        return False

    @staticmethod
    def get_changed_files() -> list:
        """Return a list of (status, filepath) tuples for changed files."""
        try:
            result = subprocess.run_git(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                intent="ordinary",
            )
            if result.returncode != 0:
                return []
            files = []
            for line in result.stdout.splitlines():
                if line.strip():
                    status = line[:2].strip()
                    filepath = line[3:]
                    files.append((status, filepath))
            return files
        except Exception:
            return []
