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
    paths = "\n".join(f"• {path}" for path in conflicts)
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
            # NUL-separated records keep paths with spaces, quotes, and
            # non-UTF-8 bytes intact; porcelain v1 would quote and mangle them.
            result = subprocess.run_git(
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                intent="ordinary",
            )
            if result.returncode != 0:
                return []
            files = []
            records = result.stdout.split(b"\0")
            index = 0
            while index < len(records):
                record = records[index]
                index += 1
                if not record:
                    continue
                decoded = os.fsdecode(record)
                status = decoded[:2].strip()
                files.append((status, decoded[3:]))
                if "R" in status or "C" in status:
                    index += 1  # Skip the original path stored by porcelain -z.
            return files
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
        tracked = (
            subprocess.run_git(
                ["git", "ls-files", "--error-unmatch", "--", filepath],
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
        result = subprocess.run_git(command, capture_output=True, check=False, intent="ordinary")
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
            capture_output=True,
            check=False,
            intent="ordinary",
        )
        if result.returncode not in (0, 1):
            return _("Could not load the differences for this file.")
        return result.stdout.decode("utf-8", errors="replace")
