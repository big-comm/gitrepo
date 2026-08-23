"""One non-UI repository probe shared by the Build Package surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from gitrepo.common import child_process as subprocess

from .git_status import STATUS_COMMAND, parse_status_records
from .git_utils import GitUtils


@dataclass(frozen=True)
class RepositorySnapshot:
    is_repository: bool
    repository_name: str = ""
    branch: str = ""
    is_detached: bool = False
    changed_files: tuple[tuple[str, str], ...] = ()
    status_error: str = ""
    commit_count: int | None = None
    last_commit: str = ""
    can_undo_last_commit: bool = False
    local_branches: tuple[str, ...] = ()
    remote_branches: tuple[str, ...] = ()
    most_recent_branch: str = ""
    package_name: str = ""
    recent_commits: tuple[tuple[str, str, str, str], ...] = ()
    unpushed_commits: int = 0
    remote_branch_exists: bool = False

    @property
    def has_changes(self) -> bool | None:
        return None if self.status_error else bool(self.changed_files)

    @classmethod
    def capture(cls) -> "RepositorySnapshot":
        if not _succeeds(["git", "rev-parse", "--is-inside-work-tree"]):
            return cls(is_repository=False)
        status = _run_bytes(list(STATUS_COMMAND))
        branch_result = _run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"])
        is_detached = branch_result.returncode != 0
        branch = branch_result.stdout.strip() if not is_detached else _output(["git", "rev-parse", "--short", "HEAD"])
        local_branches = _lines(["git", "for-each-ref", "refs/heads", "--format=%(refname:short)"])
        remote_branches = tuple(
            branch_name
            for branch_name in _lines(["git", "for-each-ref", "refs/remotes/origin", "--format=%(refname:strip=3)"])
            if branch_name != "HEAD"
        )
        commit_count_text = _output(["git", "rev-list", "--count", "HEAD"])
        commit_count = int(commit_count_text) if commit_count_text.isdigit() else 0
        remote_branch_exists = (
            not is_detached
            and bool(branch)
            and _succeeds(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"])
        )
        return cls(
            is_repository=True,
            repository_name=GitUtils.get_repo_name(),
            branch=branch,
            is_detached=is_detached,
            changed_files=parse_status_records(status.stdout) if status.returncode == 0 else (),
            status_error=(status.stderr.decode(errors="replace").strip() or "git status failed")
            if status.returncode != 0
            else "",
            commit_count=commit_count,
            last_commit=_output(["git", "log", "-1", "--pretty=format:%h|%s"]),
            can_undo_last_commit=_can_undo(branch, is_detached),
            unpushed_commits=_unpushed_commits(branch, is_detached, remote_branch_exists, commit_count),
            remote_branch_exists=remote_branch_exists,
            local_branches=local_branches,
            remote_branches=remote_branches,
            most_recent_branch=_most_recent_remote_branch(),
            package_name=GitUtils.read_package_name(),
            recent_commits=_recent_commits(),
        )


def _run(command: list[str]):
    return subprocess.run_git(command, capture_output=True, text=True, check=False, intent="ordinary")


def _run_bytes(command: list[str]):
    """Run a Git command whose output carries raw path bytes."""
    return subprocess.run_git(command, capture_output=True, check=False, intent="ordinary")


def _succeeds(command: list[str]) -> bool:
    return _run(command).returncode == 0


def _output(command: list[str]) -> str:
    result = _run(command)
    return result.stdout.strip() if result.returncode == 0 else ""


def _lines(command: list[str]) -> tuple[str, ...]:
    return tuple(line for line in _output(command).splitlines() if line)


def _can_undo(branch: str, is_detached: bool) -> bool:
    if not branch or is_detached:
        return False
    count = _output(["git", "rev-list", "--count", f"origin/{branch}..HEAD"])
    return count.isdigit() and int(count) > 0


def _unpushed_commits(branch: str, is_detached: bool, remote_branch_exists: bool, commit_count: int) -> int:
    """Count commits this branch holds that origin has never seen.

    A branch with no counterpart on origin has published nothing, so every
    commit on it is unpushed — ``origin/BRANCH..HEAD`` cannot say that because
    the left side does not resolve.
    """
    if not branch or is_detached:
        return 0
    if not remote_branch_exists:
        return commit_count
    count = _output(["git", "rev-list", "--count", f"origin/{branch}..HEAD"])
    return int(count) if count.isdigit() else 0


def _most_recent_remote_branch() -> str:
    branches = _lines(
        ["git", "for-each-ref", "--sort=-committerdate", "refs/remotes/origin", "--format=%(refname:strip=3)"]
    )
    return next((branch for branch in branches if branch == "dev" or branch.startswith("dev-")), "")


def _recent_commits() -> tuple[tuple[str, str, str, str], ...]:
    output = _output(["git", "log", "-10", "--pretty=format:%H|%an|%ad|%s", "--date=format-local:%Y-%m-%d %H:%M"])
    commits = []
    for line in output.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append(tuple(parts))
    return tuple(commits)
