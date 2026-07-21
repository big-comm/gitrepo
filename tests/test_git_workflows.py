import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.branch_handler import switch_branch
from core.commit_operations import commit_and_push_v2
from core.git_utils import GitUtils
from core.package_operations import _merge_to_main
from core.pull_operations import pull_latest_v2
from gui.dialogs.conflict_dialog import _display_ref_name


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "checkout", "-b", "main")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-m", "base")
    git(repo, "push", "-u", "origin", "main")
    return repo, remote


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def format_branch_name(self, branch):
        return branch


class GTKMenu:
    def confirm(self, _message):
        return True


class Settings:
    def get_mode_config(self):
        return {
            "auto_switch_branches": True,
            "auto_merge": True,
            "auto_pull": True,
            "auto_resolve_conflicts": False,
            "show_preview": False,
        }

    def get(self, key, default=None):
        return {
            "operation_mode": "expert",
            "auto_fetch": False,
            "auto_version_bump": False,
        }.get(key, default)


class CancellingResolver:
    def __init__(self, repo: Path):
        self.repo = repo
        self.called = False
        self.current_branch = None
        self.incoming_branch = None

    def has_conflicts(self):
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())

    def resolve(self, current_branch, incoming_branch):
        self.called = True
        self.current_branch = current_branch
        self.incoming_branch = incoming_branch
        return False


def build_package(repo: Path, resolver=None):
    return SimpleNamespace(logger=Logger(), conflict_resolver=resolver)


def test_conflict_reference_names_remain_distinct():
    assert _display_ref_name("refs/heads/dev-tester") == "dev-tester"
    assert _display_ref_name("refs/remotes/origin/dev-tester") == "origin/dev-tester"
    assert _display_ref_name("origin/main") == "origin/main"


def test_stable_build_syncs_dev_and_fast_forwards_main(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    git(repo, "push", "-u", "origin", "dev-tester")

    git(repo, "checkout", "main")
    (repo / "main.txt").write_text("main update\n", encoding="utf-8")
    git(repo, "add", "main.txt")
    git(repo, "commit", "-m", "main update")
    git(repo, "push", "origin", "main")
    git(repo, "checkout", "dev-tester")

    monkeypatch.chdir(repo)
    assert _merge_to_main(build_package(repo), "dev-tester", {})

    assert git(repo, "branch", "--show-current") == "dev-tester"
    assert not git(repo, "status", "--porcelain")
    assert git(repo, "merge-base", "--is-ancestor", "origin/main", "dev-tester") == ""
    remote_main = git(remote, "rev-parse", "main")
    remote_dev = git(remote, "rev-parse", "dev-tester")
    assert remote_main == remote_dev


def test_cancelled_stable_merge_leaves_repository_clean(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    (repo / "base.txt").write_text("development\n", encoding="utf-8")
    git(repo, "commit", "-am", "development change")
    git(repo, "push", "-u", "origin", "dev-tester")
    dev_before = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "main")
    (repo / "base.txt").write_text("main\n", encoding="utf-8")
    git(repo, "commit", "-am", "main change")
    git(repo, "push", "origin", "main")
    remote_main_before = git(remote, "rev-parse", "main")
    git(repo, "checkout", "dev-tester")

    resolver = CancellingResolver(repo)
    monkeypatch.chdir(repo)
    assert not _merge_to_main(build_package(repo, resolver), "dev-tester", {})

    assert resolver.called
    assert resolver.current_branch == "dev-tester"
    assert resolver.incoming_branch == "origin/main"
    assert git(repo, "branch", "--show-current") == "dev-tester"
    assert git(repo, "rev-parse", "HEAD") == dev_before
    assert git(remote, "rev-parse", "main") == remote_main_before
    assert not git(repo, "status", "--porcelain")
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_branch_switch_restores_original_changes_when_stash_conflicts(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    (repo / "base.txt").write_text("development\n", encoding="utf-8")
    git(repo, "commit", "-am", "development change")
    git(repo, "checkout", "main")
    (repo / "base.txt").write_text("local work\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    result = switch_branch(build_package(repo), "dev-tester", stash_first=True)

    assert not result["success"]
    assert git(repo, "branch", "--show-current") == "main"
    assert (repo / "base.txt").read_text(encoding="utf-8") == "local work\n"
    assert git(repo, "status", "--porcelain") == "M base.txt"
    assert not git(repo, "diff", "--name-only", "--diff-filter=U")
    assert not git(repo, "stash", "list")


def test_failed_merge_pull_is_aborted(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    (peer / "base.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "commit", "-am", "remote change")
    git(peer, "push", "origin", "main")

    (repo / "base.txt").write_text("local\n", encoding="utf-8")
    git(repo, "commit", "-am", "local change")
    local_head = git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert not GitUtils.resolve_divergence("main", "merge", Logger())

    assert git(repo, "rev-parse", "HEAD") == local_head
    assert not git(repo, "status", "--porcelain")
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_stable_flow_has_no_force_or_destructive_fallbacks():
    source = Path(__file__).resolve().parents[1] / "usr/share/build-package/core/package_operations.py"
    content = source.read_text(encoding="utf-8")

    assert '"--force"' not in content
    assert '"reset", "--hard"' not in content


def test_pull_moves_changes_to_dev_once_without_leaving_stash(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    git(repo, "push", "-u", "origin", "dev-tester")
    git(repo, "checkout", "main")
    (repo / "local.txt").write_text("local work\n", encoding="utf-8")

    bp = SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=GTKMenu(),
        settings=Settings(),
        github_user_name="tester",
        conflict_resolver=CancellingResolver(repo),
        get_most_recent_branch=lambda: "dev-tester",
    )

    monkeypatch.chdir(repo)
    assert pull_latest_v2(bp)

    assert git(repo, "branch", "--show-current") == "dev-tester"
    assert (repo / "local.txt").read_text(encoding="utf-8") == "local work\n"
    assert git(repo, "status", "--porcelain") == "?? local.txt"
    assert not git(repo, "stash", "list")


def test_commit_moves_local_changes_to_dev_without_double_stash(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    git(repo, "push", "-u", "origin", "dev-tester")
    git(repo, "checkout", "main")
    (repo / "local.txt").write_text("local work\n", encoding="utf-8")

    bp = SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=GTKMenu(),
        settings=Settings(),
        github_user_name="tester",
        conflict_resolver=CancellingResolver(repo),
        args=SimpleNamespace(commit="fix: local work", commit_file=None),
        apply_auto_version_bump=lambda *_args: None,
        last_commit_type=None,
    )

    monkeypatch.chdir(repo)
    assert commit_and_push_v2(bp)

    assert git(repo, "branch", "--show-current") == "dev-tester"
    assert not git(repo, "status", "--porcelain")
    assert git(repo, "show", "HEAD:local.txt") == "local work"
    assert not git(repo, "stash", "list")
