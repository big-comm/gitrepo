"""Sync with main on real repositories: after a merged pull request, every copy reaches origin/main."""

import subprocess

import pytest

from gitrepo.build_package.core import main_sync

from .git_fixtures import create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    # The assertions read the English labels; gettext consults LANGUAGE on every call.
    monkeypatch.setenv("LANGUAGE", "en")


class _Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class _Menu:
    def __init__(self, answer=True):
        self.answer = answer
        self.questions = []

    def confirm(self, question, default_yes=True):
        self.questions.append(str(question))
        return self.answer


class _Bp:
    def __init__(self, answer=True):
        self.logger = _Logger()
        self.menu = _Menu(answer)


def _commit(repository, filename, content="x\n"):
    (repository / filename).write_text(content, encoding="utf-8")
    run_git(repository, "add", filename)
    run_git(repository, "commit", "-m", f"add {filename}")


def _sha(repository, ref):
    return run_git(repository, "rev-parse", ref).stdout.strip()


def _clone(tmp_path, remote, name="github"):
    other = tmp_path / name
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.name", "GitHub")
    run_git(other, "config", "user.email", "github@example.invalid")
    return other


def _merge_pull_request(tmp_path, remote, branch):
    """Do what GitHub does for a pull request merged with a merge commit."""
    github = _clone(tmp_path, remote, name=f"github-{branch}")
    run_git(github, "fetch", "origin", branch)
    run_git(github, "merge", "--no-ff", f"origin/{branch}", "-m", f"Merge {branch} into main")
    run_git(github, "push", "origin", "main")
    return _sha(github, "HEAD")


def _work_branch(repository, name="dev-me"):
    run_git(repository, "checkout", "-b", name)
    _commit(repository, "work.txt")
    run_git(repository, "push", "-u", "origin", name)


def test_merged_pull_request_brings_all_four_copies_to_origin_main(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    merge_commit = _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)

    # Before asking origin, the merge is invisible: the work still looks pending.
    assert main_sync.capture_sync_status().state == main_sync.WORK_PENDING

    bp = _Bp()
    assert main_sync.sync_with_main(bp)

    for ref in ("dev-me", "origin/dev-me", "main", "origin/main"):
        assert _sha(repository, ref) == merge_commit, ref
    status = main_sync.capture_sync_status()
    assert status.state == main_sync.SYNCED
    assert main_sync.verdict(status)[1] == "Everything is in sync"
    # Publishing dev-me was announced and confirmed before it ran.
    assert bp.menu.questions and "git push origin refs/heads/dev-me:refs/heads/dev-me" in bp.menu.questions[0]


def test_the_catch_up_verdict_explains_itself_after_a_fetch(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)
    run_git(repository, "fetch", "origin")

    status = main_sync.capture_sync_status()
    tone, title, description = main_sync.verdict(status)

    assert status.state == main_sync.CATCH_UP
    assert title == "Your work is already in main"
    assert "origin/main has everything from dev-me" in description
    labels = {ref.label: main_sync.describe_ref(ref)[1] for ref in status.refs}
    assert labels == {
        "dev-me": "1 behind origin/main",
        "origin/dev-me": "1 behind origin/main",
        "main": "2 behind origin/main",
        "origin/main": "Reference",
    }


def test_local_only_main_commits_are_kept_in_a_backup(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    # A merge made on this computer long ago and never published.
    run_git(repository, "checkout", "-b", "old-work")
    _commit(repository, "old.txt")
    run_git(repository, "checkout", "main")
    run_git(repository, "merge", "--no-ff", "old-work", "-m", "local merge never pushed")
    stray = _sha(repository, "main")
    run_git(repository, "checkout", "-b", "dev-me", "origin/main")
    _commit(repository, "work.txt")
    run_git(repository, "push", "-u", "origin", "dev-me")
    merge_commit = _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)

    bp = _Bp()
    assert main_sync.sync_with_main(bp)

    assert _sha(repository, "main") == merge_commit
    backups = run_git(repository, "branch", "--list", "backup/main-before-sync-*").stdout.split()
    assert len(backups) == 1 and _sha(repository, backups[0]) == stray
    assert "git branch -f main origin/main" in bp.menu.questions[0]


def test_declining_the_confirmation_moves_nothing(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    before = _sha(repository, "dev-me")
    _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)

    bp = _Bp(answer=False)
    assert not main_sync.sync_with_main(bp)

    assert _sha(repository, "dev-me") == before
    assert _sha(repository, "main") != _sha(repository, "origin/main")
    assert "only git fetch ran" in bp.logger.text()


def test_unpublished_work_is_neither_pushed_nor_moved(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    run_git(repository, "push", "-u", "origin", "dev-me")
    _commit(repository, "draft.txt")
    draft = _sha(repository, "dev-me")
    github = _clone(tmp_path, remote)
    _commit(github, "elsewhere.txt")
    run_git(github, "push", "origin", "main")
    monkeypatch.chdir(repository)

    bp = _Bp()
    assert main_sync.sync_with_main(bp)

    assert _sha(repository, "dev-me") == draft
    assert _sha(repository, "origin/dev-me") != draft
    # The local main still catches up: that never needs a confirmation.
    assert _sha(repository, "main") == _sha(repository, "origin/main")
    assert bp.menu.questions == []
    status = main_sync.capture_sync_status()
    assert status.state == main_sync.WORK_PENDING and status.unpushed == 1
    assert "publish your changes first" in main_sync.verdict(status)[2]


def test_a_colleague_push_on_the_branch_is_brought_in_before_main(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    colleague = _clone(tmp_path, remote, name="colleague")
    run_git(colleague, "checkout", "dev-me")
    _commit(colleague, "colleague.txt")
    run_git(colleague, "push", "origin", "dev-me")
    merge_commit = _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)

    assert main_sync.sync_with_main(_Bp())

    assert _sha(repository, "dev-me") == merge_commit
    assert (repository / "colleague.txt").exists()


def test_uncommitted_edit_in_the_way_stops_without_touching_it(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    before = _sha(repository, "dev-me")
    github = _clone(tmp_path, remote)
    run_git(github, "fetch", "origin", "dev-me")
    run_git(github, "merge", "--no-ff", "origin/dev-me", "-m", "Merge dev-me")
    (github / "tracked.txt").write_text("changed by the pull request\n", encoding="utf-8")
    run_git(github, "commit", "-am", "edit tracked")
    run_git(github, "push", "origin", "main")
    (repository / "tracked.txt").write_text("my unsaved edit\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    bp = _Bp()
    assert not main_sync.sync_with_main(bp)

    assert _sha(repository, "dev-me") == before
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "my unsaved edit\n"
    assert "commit or stash them" in bp.logger.text()


def test_uncommitted_edit_elsewhere_survives_the_sync(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    merge_commit = _merge_pull_request(tmp_path, remote, "dev-me")
    (repository / "notes.txt").write_text("untracked notes\n", encoding="utf-8")
    (repository / "work.txt").write_text("unsaved\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    assert main_sync.sync_with_main(_Bp())

    assert _sha(repository, "dev-me") == merge_commit
    assert (repository / "work.txt").read_text(encoding="utf-8") == "unsaved\n"
    assert (repository / "notes.txt").exists()


def test_on_main_itself_only_main_moves(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    github = _clone(tmp_path, remote)
    _commit(github, "a.txt")
    run_git(github, "push", "origin", "main")
    monkeypatch.chdir(repository)

    assert main_sync.sync_with_main(_Bp())

    assert _sha(repository, "main") == _sha(repository, "origin/main")
    status = main_sync.capture_sync_status()
    assert [ref.label for ref in status.refs] == ["main", "origin/main"]
    assert main_sync.verdict(status)[2].startswith("main and origin/main are on the same commit")


def test_running_it_twice_is_harmless(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    _merge_pull_request(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)
    assert main_sync.sync_with_main(_Bp())

    again = _Bp()
    assert main_sync.sync_with_main(again)

    assert again.menu.questions == []
    assert "Everything is in sync" in again.logger.text()


def test_fetch_failure_stops_before_anything_moves(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    monkeypatch.chdir(repository)

    bp = _Bp()
    assert not main_sync.sync_with_main(bp)
    assert "git fetch failed" in bp.logger.text()


def test_without_origin_main_there_is_nothing_to_compare(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "update-ref", "-d", "refs/remotes/origin/main")
    monkeypatch.chdir(repository)

    status = main_sync.capture_sync_status()

    assert status.state == main_sync.UNAVAILABLE
    assert main_sync.plan_sync(status) == []


class _FakeGitHub:
    """Merges the pull request on the test remote, as GitHub's merge button would."""

    def __init__(self, tmp_path, remote, auto_merged=True):
        self.tmp_path, self.remote, self.auto_merged = tmp_path, remote, auto_merged
        self.token = "token"

    def ensure_github_token(self, logger):
        return True

    def create_pull_request(self, source_branch, target_branch="main", auto_merge=False, logger=None):
        if not self.auto_merged:
            return {"number": 7, "auto_merged": False}
        _merge_pull_request(self.tmp_path, self.remote, source_branch)
        return {"number": 7, "auto_merged": True}


class _CliMenu(_Menu):
    def __init__(self, picks):
        super().__init__(True)
        self.picks = list(picks)

    def show_menu(self, title, options, default_index=0, additional_content=None):
        pick = self.picks.pop(0)
        return pick, options[pick]


class _CliLogger(_Logger):
    def display_summary(self, title, data):
        self.messages.append(("summary", title))


def _cli_pull_request(tmp_path, monkeypatch, auto_merged):
    from gitrepo.build_package.core.build_package import BuildPackage

    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    monkeypatch.chdir(repository)
    fake = type("Bp", (), {})()
    fake.is_git_repo = True
    fake.logger = _CliLogger()
    # Branch dev-me, then "Create PR and auto-merge".
    fake.menu = _CliMenu([0, 1])
    fake.github_api = _FakeGitHub(tmp_path, remote, auto_merged)
    BuildPackage.merge_branch_menu(fake)
    return repository


def test_cli_auto_merged_pull_request_synchronizes_this_computer(tmp_path, monkeypatch):
    repository = _cli_pull_request(tmp_path, monkeypatch, auto_merged=True)

    for ref in ("dev-me", "origin/dev-me", "main"):
        assert _sha(repository, ref) == _sha(repository, "origin/main"), ref


def test_cli_pull_request_left_for_review_moves_nothing(tmp_path, monkeypatch):
    repository = _cli_pull_request(tmp_path, monkeypatch, auto_merged=False)

    assert _sha(repository, "main") == _sha(repository, "origin/main")
    assert _sha(repository, "dev-me") != _sha(repository, "main")


def test_gui_auto_merged_pull_request_synchronizes_this_computer(tmp_path, monkeypatch):
    from gitrepo.build_package.gui.branch_actions import BranchActionsMixin

    repository, remote = create_repository_with_remote(tmp_path)
    _work_branch(repository)
    monkeypatch.chdir(repository)
    window = type("Window", (BranchActionsMixin,), {})()
    window.build_package = _Bp()
    window.build_package.github_api = _FakeGitHub(tmp_path, remote)
    operations = []
    window._ensure_token_and_run = lambda operation, title, description: operations.append(operation)

    window._on_merge_confirm_response(None, "create", "dev-me", "main", True)
    assert operations[0]()["auto_merged"]

    for ref in ("dev-me", "origin/dev-me", "main"):
        assert _sha(repository, ref) == _sha(repository, "origin/main"), ref
