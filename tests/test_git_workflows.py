import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.branch_handler import rename_branch, switch_branch
from core.build_package import BuildPackage
from core.commit_operations import commit_and_push_v2
from core.conflict_resolver import ConflictResolver
from core.git_utils import GitUtils
from core.github_api import GitHubAPI
import core.package_operations as package_operations
from core.package_operations import _merge_to_main
from core.pull_operations import pull_latest_v2
from core.version_bumper import _locate_app_version_entry
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


def git_with_timestamp(repo: Path, timestamp: int, *args: str) -> str:
    env = os.environ.copy()
    date = f"{timestamp} +0000"
    env["GIT_AUTHOR_DATE"] = date
    env["GIT_COMMITTER_DATE"] = date
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
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


class CancelMenu:
    def show_menu(self, _title, _options):
        return 1, None


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
    assert git(repo, "rev-parse", "main") == remote_main
    assert not git(repo, "branch", "--list", "backup/main-before-stable-*")


def test_stable_build_backs_up_diverged_local_main(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    git(repo, "push", "-u", "origin", "dev-tester")

    git(repo, "checkout", "main")
    (repo / "local-main.txt").write_text("unpublished\n", encoding="utf-8")
    git(repo, "add", "local-main.txt")
    git(repo, "commit", "-m", "unpublished main work")
    local_main = git(repo, "rev-parse", "HEAD")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")
    (peer / "remote-main.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "add", "remote-main.txt")
    git(peer, "commit", "-m", "remote main work")
    git(peer, "push", "origin", "main")

    git(repo, "checkout", "dev-tester")
    bp = build_package(repo)
    monkeypatch.chdir(repo)
    assert _merge_to_main(bp, "dev-tester", {})

    backup_branches = git(
        repo, "branch", "--format=%(refname:short)", "--list",
        "backup/main-before-stable-*",
    ).splitlines()
    assert len(backup_branches) == 1
    assert git(repo, "rev-parse", backup_branches[0]) == local_main
    assert git(repo, "branch", "--show-current") == "dev-tester"
    assert git(repo, "rev-parse", "main") == git(repo, "rev-parse", "origin/main")
    assert git(remote, "rev-parse", "main") == git(remote, "rev-parse", "dev-tester")
    assert not (repo / "local-main.txt").exists()
    assert (repo / "remote-main.txt").read_text(encoding="utf-8") == "remote\n"
    assert any("backup/main-before-stable-" in message for _style, message in bp.logger.messages)


def test_stable_build_retries_when_remote_main_moves(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    git(repo, "push", "-u", "origin", "dev-tester")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    original_run = subprocess.run
    race_injected = False

    def run_with_remote_race(args, *positional, **kwargs):
        nonlocal race_injected
        promotion = [
            "git",
            "push",
            "--atomic",
            "origin",
            "dev-tester:dev-tester",
            "dev-tester:main",
        ]
        if args == promotion and not race_injected:
            race_injected = True
            (peer / "race.txt").write_text("remote race\n", encoding="utf-8")
            original_run(
                ["git", "add", "race.txt"],
                cwd=peer,
                check=True,
                capture_output=True,
            )
            original_run(
                ["git", "commit", "-m", "concurrent main update"],
                cwd=peer,
                check=True,
                capture_output=True,
            )
            original_run(
                ["git", "push", "origin", "main"],
                cwd=peer,
                check=True,
                capture_output=True,
            )
        return original_run(args, *positional, **kwargs)

    monkeypatch.setattr(package_operations.subprocess, "run", run_with_remote_race)
    monkeypatch.chdir(repo)
    bp = build_package(repo)
    assert _merge_to_main(bp, "dev-tester", {})

    assert race_injected
    assert (repo / "race.txt").read_text(encoding="utf-8") == "remote race\n"
    assert git(remote, "rev-parse", "main") == git(remote, "rev-parse", "dev-tester")
    assert git(repo, "rev-parse", "main") == git(repo, "rev-parse", "origin/main")


def test_stable_workflow_uses_main_after_original_branch_is_restored(monkeypatch):
    posted = {}

    class Response:
        status_code = 204

    def post(url, headers, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return Response()

    monkeypatch.setattr(GitUtils, "get_repo_name", staticmethod(lambda: "big-comm/gitrepo"))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: "dev-talesam"))
    monkeypatch.setattr("core.github_api.requests.post", post)

    api = GitHubAPI("token", "big-comm")
    assert api.trigger_workflow("gitrepo", "stable", "", False, False, Logger())

    payload = posted["json"]["client_payload"]
    assert payload["branch"] == "main"
    assert "new_branch" not in payload


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


def test_rebase_conflict_falls_back_to_merge_and_keeps_current_change(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    (peer / "base.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "commit", "-am", "remote change")
    git(peer, "push", "origin", "main")
    remote_head = git(remote, "rev-parse", "main")

    (repo / "base.txt").write_text("local\n", encoding="utf-8")
    git(repo, "commit", "-am", "local change")
    local_head = git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert GitUtils.resolve_divergence("main", "rebase", Logger())

    assert (repo / "base.txt").read_text(encoding="utf-8") == "local\n"
    git(repo, "merge-base", "--is-ancestor", local_head, "HEAD")
    git(repo, "merge-base", "--is-ancestor", remote_head, "HEAD")
    assert not git(repo, "status", "--porcelain")
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_modify_delete_conflict_keeps_current_file_automatically(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    git(peer, "rm", "base.txt")
    git(peer, "commit", "-m", "remove remote file")
    git(peer, "push", "origin", "main")
    remote_head = git(remote, "rev-parse", "main")

    (repo / "base.txt").write_text("keep local file\n", encoding="utf-8")
    git(repo, "commit", "-am", "keep local file")
    local_head = git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert GitUtils.resolve_divergence("main", "rebase", Logger(), CancelMenu())

    assert (repo / "base.txt").read_text(encoding="utf-8") == "keep local file\n"
    git(repo, "merge-base", "--is-ancestor", local_head, "HEAD")
    git(repo, "merge-base", "--is-ancestor", remote_head, "HEAD")
    assert not git(repo, "status", "--porcelain")
    assert not (repo / ".git" / "rebase-merge").exists()
    assert not (repo / ".git" / "rebase-apply").exists()


def test_add_add_conflict_keeps_current_file_automatically(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    (peer / "same name.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "add", ".")
    git(peer, "commit", "-m", "add remote file")
    git(peer, "push", "origin", "main")
    remote_head = git(remote, "rev-parse", "main")

    (repo / "same name.txt").write_text("local\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add local file")
    local_head = git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert GitUtils.resolve_divergence("main", "rebase", Logger())

    assert (repo / "same name.txt").read_text(encoding="utf-8") == "local\n"
    git(repo, "merge-base", "--is-ancestor", local_head, "HEAD")
    git(repo, "merge-base", "--is-ancestor", remote_head, "HEAD")
    assert not git(repo, "status", "--porcelain")


def test_binary_conflict_keeps_current_file_automatically(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    binary = repo / "asset.bin"
    binary.write_bytes(b"\x00base\xff")
    git(repo, "add", "asset.bin")
    git(repo, "commit", "-m", "add binary")
    git(repo, "push", "origin", "main")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")
    (peer / "asset.bin").write_bytes(b"\x00remote\xfe")
    git(peer, "commit", "-am", "change remote binary")
    git(peer, "push", "origin", "main")

    binary.write_bytes(b"\x00local\xfd")
    git(repo, "commit", "-am", "change local binary")

    monkeypatch.chdir(repo)
    assert GitUtils.resolve_divergence("main", "rebase", Logger())

    assert binary.read_bytes() == b"\x00local\xfd"
    assert not git(repo, "status", "--porcelain")


def test_rename_delete_conflict_keeps_current_rename_automatically(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "main")

    git(peer, "rm", "base.txt")
    git(peer, "commit", "-m", "remove remote file")
    git(peer, "push", "origin", "main")

    git(repo, "mv", "base.txt", "renamed locally.txt")
    git(repo, "commit", "-m", "rename local file")

    monkeypatch.chdir(repo)
    assert GitUtils.resolve_divergence("main", "rebase", Logger())

    assert (repo / "renamed locally.txt").read_text(encoding="utf-8") == "base\n"
    assert not (repo / "base.txt").exists()
    assert not git(repo, "status", "--porcelain")


def test_stable_flow_has_no_force_or_destructive_fallbacks():
    source = Path(__file__).resolve().parents[1] / "usr/share/build-package/core/package_operations.py"
    content = source.read_text(encoding="utf-8")

    assert '"--force"' not in content
    assert '"reset", "--hard"' not in content


def test_normal_commit_flow_has_no_force_push_fallbacks():
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "usr/share/build-package/core/commit_operations.py",
        "usr/share/build-package/core/git_utils.py",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "force_push" not in content
        assert "--force-with-lease" not in content


def test_version_lookup_skips_ignored_reports(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    (repo / ".gitignore").write_text(".audit/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore audit")
    audit = repo / ".audit"
    audit.mkdir()
    (audit / "ruff_check.txt").write_text(
        'APP_VERSION = "25.8.0"\n', encoding="utf-8"
    )
    source = repo / "config.py"
    source.write_text('APP_VERSION = "3.1.5"\n', encoding="utf-8")

    bp = SimpleNamespace(repo_path=str(repo), _app_version_cache=None)
    monkeypatch.chdir(repo)
    file_path, _content, match = _locate_app_version_entry(bp)

    assert Path(file_path) == source
    assert match.group(3) == "3.1.5"


def test_version_lookup_prefers_app_matching_repository_name(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    (repo / "pkgbuild").mkdir()
    (repo / "pkgbuild" / "PKGBUILD").write_text("pkgname=sample-app\n", encoding="utf-8")
    bundled = repo / "usr" / "share" / "bundled"
    bundled.mkdir(parents=True)
    (bundled / "config.py").write_text(
        'APP_VERSION = "9.9.9"\nAPP_NAME = "Bundled Tool"\n',
        encoding="utf-8",
    )
    application = repo / "src" / "config.py"
    application.parent.mkdir()
    application.write_text(
        'APP_VERSION = "3.1.5"\nAPP_NAME = "Sample App"\n',
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add application versions")

    bp = SimpleNamespace(repo_path=str(repo), _app_version_cache=None)
    monkeypatch.chdir(repo)
    file_path, _content, match = _locate_app_version_entry(bp)

    assert Path(file_path) == application
    assert match.group(3) == "3.1.5"


def test_worktree_and_revision_diffs_are_available_per_file(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    (repo / "base.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new.txt").write_text("new file\n", encoding="utf-8")

    # The GUI can be launched from a directory other than the selected repository.
    monkeypatch.chdir(tmp_path)
    pending = {
        filepath: status
        for status, filepath in GitUtils.get_changed_files(str(repo))
    }
    assert pending["base.txt"] == "M"
    assert pending["new.txt"] == "??"
    assert "-base" in GitUtils.get_worktree_file_diff("base.txt", str(repo))
    assert "+changed" in GitUtils.get_worktree_file_diff("base.txt", str(repo))
    assert "+new file" in GitUtils.get_worktree_file_diff("new.txt", str(repo))

    git(repo, "add", ".")
    git(repo, "commit", "-m", "change files")
    after = git(repo, "rev-parse", "HEAD")
    changes = GitUtils.get_revision_changes(before, after, str(repo))

    assert ("M", "base.txt") in changes
    assert ("A", "new.txt") in changes
    assert "+changed" in GitUtils.get_revision_file_diff(
        before,
        after,
        "base.txt",
        str(repo),
    )


def test_changed_files_handles_spaces_and_renames(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    original = repo / "file with spaces.txt"
    original.write_text("content\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add spaced file")
    git(repo, "mv", "file with spaces.txt", "renamed file.txt")

    monkeypatch.chdir(repo)
    changes = GitUtils.get_changed_files()

    assert changes == [("R", "renamed file.txt")]


def test_changed_files_expands_untracked_directories(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    directory = repo / "new folder"
    directory.mkdir()
    (directory / "one.txt").write_text("one\n", encoding="utf-8")
    (directory / "two.txt").write_text("two\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    changes = GitUtils.get_changed_files()

    assert changes == [
        ("??", "new folder/one.txt"),
        ("??", "new folder/two.txt"),
    ]


def test_remote_branch_summaries_show_latest_and_divergence(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-friend")
    (repo / "friend.txt").write_text("friend\n", encoding="utf-8")
    git(repo, "add", ".")
    git_with_timestamp(repo, 2_000_000_100, "commit", "-m", "friend work")
    git(repo, "push", "-u", "origin", "dev-friend")

    git(repo, "checkout", "main")
    git(repo, "checkout", "-b", "dev-talesam")
    (repo / "latest.txt").write_text("latest\n", encoding="utf-8")
    git(repo, "add", ".")
    git_with_timestamp(repo, 2_000_000_200, "commit", "-m", "latest work")
    git(repo, "push", "-u", "origin", "dev-talesam")
    git(repo, "checkout", "dev-friend")

    monkeypatch.chdir(repo)
    summaries = GitUtils.get_remote_branch_summaries(str(repo), fetch=True)
    by_name = {item["branch"]: item for item in summaries}

    assert {"main", "dev-friend", "dev-talesam"} <= set(by_name)
    assert by_name["dev-talesam"]["is_latest"]
    assert by_name["dev-talesam"]["is_recommended"]
    assert by_name["dev-talesam"]["relation"] == "diverged"
    assert by_name["dev-talesam"]["incoming"] == 1
    assert by_name["dev-talesam"]["local_only"] == 1
    assert GitUtils.get_incoming_changes("dev-talesam", str(repo)) == [
        ("A", "latest.txt")
    ]


def test_pull_uses_explicit_remote_branch_instead_of_automatic_choice(
    tmp_path,
    monkeypatch,
):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-friend")
    git(repo, "push", "-u", "origin", "dev-friend")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "-b", "dev-talesam", "origin/main")
    (peer / "selected.txt").write_text("selected source\n", encoding="utf-8")
    git(peer, "add", ".")
    git(peer, "commit", "-m", "selected source")
    git(peer, "push", "-u", "origin", "dev-talesam")

    logger = Logger()
    menu = GTKMenu()
    bp = SimpleNamespace(
        is_git_repo=True,
        logger=logger,
        menu=menu,
        settings=Settings(),
        github_user_name="friend",
        conflict_resolver=ConflictResolver(logger, menu),
        get_most_recent_branch=lambda: "dev-friend",
    )

    monkeypatch.chdir(repo)
    bp.conflict_resolver.repo_root = str(repo)
    assert pull_latest_v2(bp, source_branch="dev-talesam")

    assert git(repo, "branch", "--show-current") == "dev-friend"
    assert (repo / "selected.txt").read_text(encoding="utf-8") == "selected source\n"


def test_personal_branch_override_is_repository_specific(tmp_path, monkeypatch):
    repo, _remote = create_repository(tmp_path)
    monkeypatch.chdir(repo)
    bp = BuildPackage.__new__(BuildPackage)
    bp.repo_path = str(repo)
    bp.settings = SimpleNamespace(
        get=lambda key, default=None: {"github_username": ""}.get(key, default)
    )
    bp.github_user_name = "unknown"

    assert BuildPackage.set_personal_branch(bp, "dev-friend")
    assert BuildPackage.get_personal_branch(bp) == "dev-friend"
    assert git(repo, "config", "--local", "--get", "gitrepo.personalBranch") == (
        "dev-friend"
    )

    assert BuildPackage.set_personal_branch(bp, "")
    assert BuildPackage.get_personal_branch(bp) == "dev-unknown"


def test_rename_branch_publishes_new_name_and_preserves_old_remote(
    tmp_path,
    monkeypatch,
):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-unknown")
    git(repo, "push", "-u", "origin", "dev-unknown")

    monkeypatch.chdir(repo)
    result = rename_branch(
        build_package(repo),
        "dev-unknown",
        "dev-friend",
        delete_old_remote=False,
    )

    assert result["success"]
    assert git(repo, "branch", "--show-current") == "dev-friend"
    assert git(remote, "rev-parse", "dev-friend")
    assert git(remote, "rev-parse", "dev-unknown")
    assert git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/dev-friend"

    deleted = rename_branch(
        build_package(repo),
        "dev-friend",
        "dev-final",
        delete_old_remote=True,
    )
    assert deleted["success"]
    assert deleted["old_remote_deleted"]
    assert git(remote, "rev-parse", "dev-final")
    old_remote = subprocess.run(
        ["git", "rev-parse", "--verify", "dev-friend"],
        cwd=remote,
        capture_output=True,
        check=False,
    )
    assert old_remote.returncode != 0


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


def test_pull_preserves_uncommitted_local_change_after_stash_conflict(
    tmp_path, monkeypatch
):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    git(repo, "push", "-u", "origin", "dev-tester")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "-b", "dev-tester", "origin/dev-tester")
    (peer / "base.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "commit", "-am", "remote change")
    git(peer, "push", "origin", "dev-tester")
    remote_head = git(remote, "rev-parse", "dev-tester")

    (repo / "base.txt").write_text("uncommitted local work\n", encoding="utf-8")
    logger = Logger()
    menu = GTKMenu()
    bp = SimpleNamespace(
        is_git_repo=True,
        logger=logger,
        menu=menu,
        settings=Settings(),
        github_user_name="tester",
        conflict_resolver=ConflictResolver(logger, menu),
        get_most_recent_branch=lambda: "dev-tester",
    )

    monkeypatch.chdir(repo)
    bp.conflict_resolver.repo_root = str(repo)
    assert pull_latest_v2(bp)

    assert git(repo, "rev-parse", "HEAD") == remote_head
    assert (repo / "base.txt").read_text(encoding="utf-8") == "uncommitted local work\n"
    assert git(repo, "status", "--porcelain") == "M base.txt"
    assert not git(repo, "stash", "list")


def test_pull_resolves_diverged_commit_conflict_automatically(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    git(repo, "push", "-u", "origin", "dev-tester")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "-b", "dev-tester", "origin/dev-tester")
    (peer / "base.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "commit", "-am", "remote change")
    git(peer, "push", "origin", "dev-tester")
    remote_head = git(remote, "rev-parse", "dev-tester")

    (repo / "base.txt").write_text("committed local work\n", encoding="utf-8")
    git(repo, "commit", "-am", "local change")
    local_head = git(repo, "rev-parse", "HEAD")
    logger = Logger()
    menu = GTKMenu()
    bp = SimpleNamespace(
        is_git_repo=True,
        logger=logger,
        menu=menu,
        settings=Settings(),
        github_user_name="tester",
        conflict_resolver=ConflictResolver(logger, menu),
        get_most_recent_branch=lambda: "dev-tester",
    )

    monkeypatch.chdir(repo)
    bp.conflict_resolver.repo_root = str(repo)
    assert pull_latest_v2(bp)

    assert (repo / "base.txt").read_text(encoding="utf-8") == "committed local work\n"
    git(repo, "merge-base", "--is-ancestor", local_head, "HEAD")
    git(repo, "merge-base", "--is-ancestor", remote_head, "HEAD")
    assert not git(repo, "status", "--porcelain")


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


def test_commit_flow_resolves_remote_conflict_and_pushes(tmp_path, monkeypatch):
    repo, remote = create_repository(tmp_path)
    git(repo, "checkout", "-b", "dev-tester")
    git(repo, "push", "-u", "origin", "dev-tester")

    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer User")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "-b", "dev-tester", "origin/dev-tester")
    (peer / "base.txt").write_text("remote translation\n", encoding="utf-8")
    git(peer, "commit", "-am", "remote translation")
    git(peer, "push", "origin", "dev-tester")
    remote_change = git(remote, "rev-parse", "dev-tester")

    (repo / "base.txt").write_text("current branch work\n", encoding="utf-8")
    bp = SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=GTKMenu(),
        settings=Settings(),
        github_user_name="tester",
        conflict_resolver=CancellingResolver(repo),
        args=SimpleNamespace(commit="fix: preserve current work", commit_file=None),
        apply_auto_version_bump=lambda *_args: None,
        last_commit_type=None,
    )

    monkeypatch.chdir(repo)
    assert commit_and_push_v2(bp)

    assert (repo / "base.txt").read_text(encoding="utf-8") == "current branch work\n"
    git(repo, "merge-base", "--is-ancestor", remote_change, "HEAD")
    assert git(remote, "rev-parse", "dev-tester") == git(repo, "rev-parse", "HEAD")
    assert not git(repo, "status", "--porcelain")
