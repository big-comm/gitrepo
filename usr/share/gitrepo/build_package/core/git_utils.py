#
# git_utils.py - Git repository utilities
#

import os
import re
import shutil
import stat
from urllib.parse import urlsplit

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from gitrepo.common.network_url import is_github_path_segment
from gitrepo.common.translation import _

from .git_status import STATUS_COMMAND, display_path, parse_status_records

# Only these hosts may be addressed as GitHub repositories.
GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
# SCP-style remote: [user@]host:path
_SCP_REMOTE = re.compile(r"^(?:(?P<user>[^@/]+)@)?(?P<host>[^:/]+):(?P<path>.+)$")


def _pkgbuild_directory(repo_path: str) -> str:
    """Return the owned PKGBUILD directory, preferring the repository root."""
    if not repo_path:
        return ""
    root = os.path.realpath(repo_path)
    for relative_directory in ("", "pkgbuild"):
        directory = os.path.join(repo_path, relative_directory)
        if relative_directory and os.path.islink(directory):
            continue
        candidate = os.path.join(directory, "PKGBUILD")
        try:
            info = os.lstat(candidate)
            inside_repository = os.path.commonpath([root, os.path.realpath(candidate)]) == root
        except (OSError, ValueError):
            continue
        if stat.S_ISREG(info.st_mode) and inside_repository:
            return os.path.normpath(directory)
    return ""


def _github_path_segments(path: str) -> tuple[str, str]:
    """Return (owner, repository) when *path* is exactly two valid segments."""
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if len(segments) != 2:
        return "", ""
    owner, repository = segments
    repository = repository.removesuffix(".git")
    if not all(is_github_path_segment(segment) for segment in (owner, repository)):
        return "", ""
    return owner, repository


def parse_github_remote(url: str) -> tuple[str, str, str]:
    """Return (host, owner, repository) for a GitHub remote, else empty strings."""
    url = (url or "").strip()
    if not url:
        return "", "", ""

    if "://" in url:
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http", "ssh", "git"}:
            return "", "", ""
        host = (parts.hostname or "").lower()
        path = parts.path
    else:
        match = _SCP_REMOTE.match(url)
        if not match:
            return "", "", ""
        host = match.group("host").lower()
        path = match.group("path")

    if host not in GITHUB_HOSTS:
        return "", "", ""
    owner, repository = _github_path_segments(path)
    if not owner:
        return "", "", ""
    return host, owner, repository


def _branch_names(*command: str) -> list[str]:
    result = subprocess.run_git(["git", *command], capture_output=True, text=True, check=True, intent="ordinary")
    return [
        line.strip().lstrip("* ").removeprefix("origin/")
        for line in result.stdout.splitlines()
        if line.strip() and "->" not in line
    ]


PROTECTED_BRANCHES = frozenset({"main", "master", "dev"})
# The bases a branch may already be merged into, most authoritative first.
MERGE_BASE_CANDIDATES = (
    "refs/remotes/origin/main",
    "refs/remotes/origin/master",
    "refs/heads/main",
    "refs/heads/master",
)


def merge_base_reference() -> str:
    """Return the ref that decides whether a branch is already merged."""
    for candidate in MERGE_BASE_CANDIDATES:
        result = subprocess.run_git(
            ["git", "rev-parse", "--verify", "--quiet", candidate],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode == 0 and result.stdout.strip():
            return candidate
    return ""


def merged_branches(base: str, *scope: str) -> set[str]:
    """Return the branches whose tip is already reachable from *base*.

    Reachability is Git's own answer, not a guess from the branch name: a
    branch that is not listed here still holds commits that exist nowhere else.
    """
    return set(_branch_names("branch", *scope, "--merged", base, "--format=%(refname:short)"))


def branch_tip(reference: str) -> str:
    """Return the short OID of *reference*, or an empty string."""
    result = subprocess.run_git(
        ["git", "rev-parse", "--short", reference], capture_output=True, text=True, check=False, intent="ordinary"
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _protected_branches(local: list[str], remote: list[str]) -> set[str]:
    protected = set(PROTECTED_BRANCHES)
    current = GitUtils.get_current_branch()
    if current:
        protected.add(current)
    development = sorted({branch for branch in local + remote if branch.startswith("dev-")}, reverse=True)
    if development:
        protected.add(development[0])
    return protected


def _obsolete_branches(
    local: list[str],
    remote: list[str],
    merged_local: set[str],
    merged_remote: set[str],
) -> tuple[list[str], list[str]]:
    """Return only the branches whose commits already live in the merge base."""
    protected = _protected_branches(local, remote)
    return (
        [branch for branch in local if branch not in protected and branch in merged_local],
        [branch for branch in remote if branch not in protected and branch in merged_remote],
    )


def _unmerged_branches(
    local: list[str],
    remote: list[str],
    merged_local: set[str],
    merged_remote: set[str],
) -> list[str]:
    """Return the branches kept because they still hold unreachable commits."""
    protected = _protected_branches(local, remote)
    kept = [branch for branch in local if branch not in protected and branch not in merged_local]
    kept.extend(f"origin/{branch}" for branch in remote if branch not in protected and branch not in merged_remote)
    return kept


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


def _conflicted_paths() -> list[str]:
    """Return the paths Git currently reports as unmerged."""
    result = subprocess.run_git(
        ["git", "diff", "--name-only", "--diff-filter=U", "-z"],
        capture_output=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode != 0:
        return []
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def _abort_merge() -> None:
    subprocess.run_git(["git", "merge", "--abort"], capture_output=True, check=False, intent="ordinary")


def _confirm_keeping_current(branch: str, incoming: str, conflicts: list[str], logger, menu) -> bool:
    """Name the files that lose their incoming version before anything is written."""
    paths = "\n".join(f"• {display_path(path)}" for path in conflicts)
    question = _(
        "Resolve the divergence keeping {0} where the two branches disagree?\n\n"
        "The conflicting lines from {1} are discarded in:\n{2}\n\n"
        "Every other change from {1} is merged, and the discarded version stays "
        "readable with: git diff HEAD^2 -- FILE"
    ).format(branch, incoming, paths)
    if menu is not None and menu.confirm(question, default_yes=False):
        return True
    _log_if(logger, "yellow", _("Automatic conflict resolution cancelled."))
    return False


def _commit_merge(logger) -> bool:
    """Finish a merge that is already staged, restoring the tree on failure."""
    result = subprocess.run_git(
        ["git", "commit", "--no-edit"], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode == 0:
        return True
    _abort_merge()
    _log_if(logger, "red", _("Could not finish merge: {0}").format(result.stderr.strip()))
    return False


def _merge_keeping_current(branch: str, logger, menu, resolver=None) -> bool:
    """Merge the remote branch, keeping this branch where the two disagree.

    The discard is announced before it happens: the user sees which files lose
    their incoming lines and how to read that version afterwards.
    """
    incoming = f"origin/{branch}"
    trial = subprocess.run_git(
        ["git", "merge", "--no-commit", "--no-ff", incoming],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    conflicts = _conflicted_paths()
    if trial.returncode == 0 and not conflicts:
        if not _commit_merge(logger):
            return False
        _log_if(logger, "green", _("Remote changes integrated with merge."))
        return True

    _abort_merge()
    if not conflicts:
        detail = trial.stderr.strip() or trial.stdout.strip() or _("Unknown Git error")
        _log_if(logger, "red", _("Merge failed: {0}").format(detail))
        return False
    if not _confirm_keeping_current(branch, incoming, conflicts, logger, menu):
        return False

    merge = subprocess.run_git(
        ["git", "merge", "--no-edit", "-X", "ours", incoming],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if merge.returncode != 0:
        # Add/add and delete/modify conflicts survive "-X ours"; the resolver
        # asks about those files before dropping their incoming version.
        if resolver is None or not resolver.resolve_keeping_current(
            branch, incoming, recovery_hint="git diff HEAD^2 -- FILE"
        ):
            _abort_merge()
            _log_if(logger, "red", _("Merge aborted; the repository was restored."))
            return False
        if not _commit_merge(logger):
            return False

    _log_if(
        logger,
        "yellow",
        _("Kept {0} in {1} file(s); the {2} version was discarded there: {3}").format(
            branch, len(conflicts), incoming, ", ".join(conflicts)
        ),
    )
    _log_if(logger, "cyan", _("Read the discarded version with: git diff HEAD^2 -- FILE"))
    return True


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
    def get_origin_url() -> str:
        """Return the configured origin URL, or an empty string."""
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
        except Exception:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def get_github_remote() -> tuple[str, str, str]:
        """Return (host, owner, repository) when origin is on GitHub.

        Every GitHub request is addressed by this value, so a remote hosted
        anywhere else must resolve to nothing rather than to a same-named
        repository the token happens to reach.
        """
        return parse_github_remote(GitUtils.get_origin_url())

    @staticmethod
    def get_repo_name() -> str:
        """Return the validated GitHub ``owner/repository``, or an empty string."""
        _host, owner, repository = GitUtils.get_github_remote()
        return f"{owner}/{repository}" if owner and repository else ""

    @staticmethod
    def get_canonical_repository() -> str:
        """Return ``host/owner/repository`` for confirmations, or an empty string."""
        host, owner, repository = GitUtils.get_github_remote()
        return f"{host}/{owner}/{repository}" if owner and repository else ""

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
        match = re.fullmatch(r"(?:\d+\+)?([^@]+)@users\.noreply\.github\.com", email)
        return match.group(1) if match else "unknown"

    @staticmethod
    def is_valid_branch_name(branch: str) -> bool:
        """Return whether *branch* is accepted by Git."""
        if not branch:
            return False
        result = subprocess.run_git(
            ["git", "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        return result.returncode == 0

    @staticmethod
    def get_configured_personal_branch(repo_path: str | None = None) -> str:
        """Return the valid repository-local personal branch override."""
        root = repo_path or GitUtils.get_repo_root_path()
        result = subprocess.run_git(
            ["git", "config", "--local", "--get", "gitrepo.personalBranch"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        branch = result.stdout.strip() if result.returncode == 0 else ""
        return branch if GitUtils.is_valid_branch_name(branch) else ""

    @staticmethod
    def set_personal_branch(branch: str, repo_path: str | None = None) -> bool:
        """Store or clear the repository-local personal branch override."""
        branch = (branch or "").strip()
        if branch and not GitUtils.is_valid_branch_name(branch):
            return False
        command = (
            ["git", "config", "--local", "gitrepo.personalBranch", branch]
            if branch
            else ["git", "config", "--local", "--unset-all", "gitrepo.personalBranch"]
        )
        result = subprocess.run_git(
            command,
            cwd=repo_path or GitUtils.get_repo_root_path(),
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        return result.returncode == 0 or (not branch and result.returncode == 5)

    @staticmethod
    def get_personal_branch(username: str | None = None, repo_path: str | None = None) -> str:
        """Resolve the branch used for this repository's personal work."""
        configured = GitUtils.get_configured_personal_branch(repo_path)
        if configured:
            return configured

        current = GitUtils.get_current_branch(repo_path)
        if current.startswith("dev-") and GitUtils.is_valid_branch_name(current):
            return current

        username = (username or GitUtils.get_github_username() or "unknown").strip()
        if username == "unknown":
            result = subprocess.run_git(
                [
                    "git",
                    "for-each-ref",
                    "--sort=-committerdate",
                    "--format=%(refname)",
                    "refs/heads",
                    "refs/remotes/origin",
                ],
                cwd=repo_path or GitUtils.get_repo_root_path(),
                capture_output=True,
                text=True,
                check=False,
                intent="ordinary",
            )
            if result.returncode == 0:
                for reference in result.stdout.splitlines():
                    branch = reference.removeprefix("refs/heads/").removeprefix("refs/remotes/origin/")
                    if branch.startswith("dev-") and GitUtils.is_valid_branch_name(branch):
                        return branch

        inferred = f"dev-{username}"
        return inferred if GitUtils.is_valid_branch_name(inferred) else "dev-unknown"

    @staticmethod
    def list_version_candidates(repo_path: str) -> list[str] | None:
        """List tracked and non-ignored untracked files, or None outside Git."""
        result = subprocess.run_git(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_path,
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode != 0:
            return None
        separator = "\0" if isinstance(result.stdout, str) else b"\0"
        paths = [os.fsdecode(path) for path in result.stdout.split(separator) if path]
        return sorted(path for path in paths if not os.path.isabs(path) and not path.startswith("../"))

    @staticmethod
    def has_changes() -> bool:
        """Report whether the working tree holds anything uncommitted.

        Every caller uses this as a guard before touching the repository, so an
        unreadable status must answer "yes, there is work here". Reporting a
        clean tree on failure is what lets a rewrite run over real changes.
        """
        try:
            result = subprocess.run_git(
                list(STATUS_COMMAND),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                intent="ordinary",
            )
        except Exception:
            return True
        if result.returncode != 0:
            return True
        return bool(parse_status_records(result.stdout))

    @staticmethod
    def get_package_name() -> str:
        """Read the first package name from makepkg's authoritative metadata."""
        repo_path = GitUtils.get_repo_root_path()
        pkgbuild_directory = _pkgbuild_directory(repo_path)
        if not pkgbuild_directory or shutil.which("makepkg") is None:
            return ""
        try:
            result = subprocess.run(
                ["makepkg", "--printsrcinfo"],
                cwd=pkgbuild_directory,
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
            base = merge_base_reference()
            if not base:
                logger.log("red", _("No main or master branch to compare against."))
                logger.log("cyan", _("Without a base, no branch can be proven merged, so none is offered."))
                return False
            local = _branch_names("branch", "--format=%(refname:short)")
            remote = _branch_names("branch", "-r", "--format=%(refname:short)")
            merged_local = merged_branches(base)
            merged_remote = merged_branches(base, "-r")
            local_to_remove, remote_to_remove = _obsolete_branches(local, remote, merged_local, merged_remote)
            kept = _unmerged_branches(local, remote, merged_local, merged_remote)
        except subprocess.SubprocessError as error:
            logger.log("red", _("Could not inventory branches: {0}").format(error))
            return False

        if kept:
            logger.log(
                "cyan",
                _("Kept {0} branch(es) whose commits are not in {1}: {2}").format(len(kept), base, ", ".join(kept)),
            )
        candidates = [
            *(f"local: {branch} ({branch_tip(branch)})" for branch in local_to_remove),
            *(f"origin/{branch} ({branch_tip(f'refs/remotes/origin/{branch}')})" for branch in remote_to_remove),
        ]
        if not candidates:
            logger.log("green", _("No obsolete branches found."))
            return True
        preview = "\n".join(f"• {candidate}" for candidate in candidates)
        if not menu.confirm(
            _("Permanently delete these branches?\nEvery one is already merged into {0}.\n{1}").format(base, preview),
            default_yes=False,
        ):
            logger.log("yellow", _("Branch cleanup cancelled."))
            return False

        with authorize_destructive_git():
            _delete_local_branches(local_to_remove, local, logger)
            _delete_remote_branches(remote_to_remove, logger)
        logger.log("green", _("Branch cleanup completed."))
        return True

    @staticmethod
    def get_current_branch(repo_path: str | None = None) -> str:
        """Gets the name of the current branch"""
        if not repo_path and not GitUtils.is_git_repo():
            return ""

        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
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
    def resolve_divergence(branch: str, method: str, logger=None, menu=None, resolver=None) -> bool:
        """Resolve divergence through an explicit, bounded strategy."""
        if not GitUtils.is_git_repo():
            _log_if(logger, "red", _("Not a Git repository"))
            return False
        if method in {"rebase", "merge"}:
            return _integrate_remote(branch, method, logger)
        if method == "merge-keep-current":
            return _merge_keeping_current(branch, logger, menu, resolver)
        if method == "force_push":
            return _force_push_with_confirmation(branch, logger, menu)
        _log_if(logger, "red", _("Unknown resolution method: {0}").format(method))
        return False

    @staticmethod
    def get_changed_files() -> list:
        """Return a list of (status, filepath) tuples for changed files."""
        try:
            result = subprocess.run_git(
                list(STATUS_COMMAND),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                intent="ordinary",
            )
            if result.returncode != 0:
                return []
            return list(parse_status_records(result.stdout))
        except Exception:
            return []

    @staticmethod
    def ref_exists(ref: str) -> bool:
        """Return whether a local or remote-tracking ref is available."""
        if not ref:
            return False
        result = subprocess.run_git(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        return result.returncode == 0

    @staticmethod
    def get_head_sha() -> str:
        """Return the current HEAD revision, or an empty string outside a repo."""
        result = subprocess.run_git(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, intent="ordinary"
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def get_worktree_file_diff(filepath: str) -> str:
        """Return the staged and unstaged diff of one working-tree file."""
        repo_root = GitUtils.get_repo_root_path()
        tracked = (
            subprocess.run_git(
                ["git", "ls-files", "--error-unmatch", "--", filepath],
                cwd=repo_root,
                capture_output=True,
                check=False,
                intent="ordinary",
            ).returncode
            == 0
        )
        command = (
            ["git", "diff", "--no-ext-diff", "HEAD", "--", filepath]
            if tracked
            else ["git", "diff", "--no-ext-diff", "--no-index", "--", os.devnull, filepath]
        )
        result = subprocess.run_git(
            command,
            cwd=repo_root,
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        # git diff exits 1 when differences exist; only other codes are failures.
        if result.returncode not in (0, 1):
            return _("Could not load the differences for this file.")
        return result.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def get_revision_changes(before: str, after: str) -> list:
        """Return (status, path) entries changed between two revisions."""
        if not before or not after or before == after:
            return []
        result = subprocess.run_git(
            ["git", "diff", "--name-status", "--no-renames", "-z", before, after],
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode != 0:
            return []
        fields = [os.fsdecode(field) for field in result.stdout.split(b"\0") if field]
        return [(fields[index], fields[index + 1]) for index in range(0, len(fields) - 1, 2)]

    @staticmethod
    def get_revision_file_diff(before: str, after: str, filepath: str) -> str:
        """Return a unified diff for one file between two revisions."""
        result = subprocess.run_git(
            ["git", "diff", "--no-ext-diff", "--unified=5", before, after, "--", filepath],
            cwd=GitUtils.get_repo_root_path(),
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode not in (0, 1):
            return _("Could not load the differences for this file.")
        return result.stdout.decode("utf-8", errors="replace")
