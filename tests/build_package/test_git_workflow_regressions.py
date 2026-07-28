"""Regressions for personal branches, stash recovery, and version discovery."""

import builtins
import os
import subprocess
from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import (
    branch_handler,
    commit_handler,
    commit_operations,
    git_utils,
    pull_operations,
    version_bumper,
)
from gitrepo.build_package.core.conflict_resolver import ConflictResolver
from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.build_package.gui.gtk_adapters import GTKConflictResolver

from .git_fixtures import AlwaysConfirm, Logger, create_repository_with_remote, run_git


class NoConflicts:
    def has_conflicts(self):
        return False

    def resolve(self, *_args):
        return False


class RecordingMenu:
    def __init__(self, answer=True):
        self.answer = answer
        self.question = ""
        self.questions = []
        self.defaults = []

    def confirm(self, question, default_yes=True):
        self.question = question
        self.questions.append(question)
        self.defaults.append(default_yes)
        return self.answer


def _bp(menu=None):
    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu or AlwaysConfirm(),
        conflict_resolver=NoConflicts(),
        dry_run_mode=False,
    )


@pytest.mark.parametrize(
    ("email", "username"),
    [
        ("123456+talesam@users.noreply.github.com", "talesam"),
        ("bigbruno@users.noreply.github.com", "bigbruno"),
    ],
)
def test_github_username_accepts_noreply_addresses(monkeypatch, email, username):
    def fake_run(command, **_kwargs):
        if command == ["git", "config", "github.user"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        if command == ["git", "config", "user.email"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{email}\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(git_utils.subprocess, "run_git", fake_run)

    assert GitUtils.get_github_username() == username


def test_personal_branch_is_repository_specific_and_prefers_current_dev(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    assert GitUtils.set_personal_branch("dev-configured", str(repository))
    assert GitUtils.get_personal_branch("friend", str(repository)) == "dev-configured"
    assert run_git(repository, "config", "--local", "--get", "gitrepo.personalBranch").stdout.strip() == (
        "dev-configured"
    )

    assert GitUtils.set_personal_branch("", str(repository))
    run_git(repository, "checkout", "-b", "dev-current")
    assert GitUtils.get_personal_branch("friend", str(repository)) == "dev-current"

    run_git(repository, "checkout", "main")
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "invalid branch")
    assert GitUtils.get_personal_branch("friend", str(repository)) == "dev-friend"


def test_personal_branch_uses_existing_dev_when_github_user_is_unknown(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-personal")
    run_git(repository, "checkout", "main")
    monkeypatch.chdir(tmp_path)

    assert GitUtils.get_personal_branch("unknown", str(repository)) == "dev-personal"


def _stage_and_modify(repository):
    tracked = repository / "tracked.txt"
    tracked.write_text("staged\n", encoding="utf-8")
    run_git(repository, "add", "tracked.txt")
    tracked.write_text("staged\nunstaged\n", encoding="utf-8")
    return tracked


def _assert_index_and_worktree_restored(repository, tracked):
    assert run_git(repository, "show", ":tracked.txt").stdout == "staged\n"
    assert tracked.read_text(encoding="utf-8") == "staged\nunstaged\n"
    assert run_git(repository, "diff", "--cached", "--name-only").stdout.strip() == "tracked.txt"
    assert run_git(repository, "diff", "--name-only").stdout.strip() == "tracked.txt"
    assert run_git(repository, "stash", "list").stdout.strip() == ""


def test_switch_and_commit_restores_index_before_committing(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "dev-target")
    tracked = _stage_and_modify(repository)
    monkeypatch.chdir(repository)

    def inspect_commit(_bp, _message, target_branch):
        assert target_branch == "dev-target"
        assert run_git(repository, "branch", "--show-current").stdout.strip() == target_branch
        _assert_index_and_worktree_restored(repository, tracked)
        return True

    monkeypatch.setattr(commit_handler, "execute_commit", inspect_commit)

    assert branch_handler.switch_and_commit(_bp(), "dev-target", "fix: preserve index")


def test_failed_checkout_restores_stashed_work_on_original_branch(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    tracked = _stage_and_modify(repository)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(branch_handler, "_checkout_branch", lambda _branch: False)

    assert not branch_handler.switch_and_commit(_bp(), "dev-target", "fix: preserve work")
    assert run_git(repository, "branch", "--show-current").stdout.strip() == "main"
    _assert_index_and_worktree_restored(repository, tracked)


def test_switch_and_commit_treats_stashed_work_as_the_local_version(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "dev-source")
    (repository / "tracked.txt").write_text("target branch\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "target change")
    run_git(repository, "checkout", "dev-source")
    (repository / "tracked.txt").write_text("saved local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    logger = Logger()
    menu = RecordingMenu(answer=True)
    resolver = ConflictResolver(logger, menu, "auto-ours")
    bp = SimpleNamespace(logger=logger, menu=menu, conflict_resolver=resolver)

    def inspect_commit(_bp, _message, target_branch):
        assert target_branch == "main"
        assert run_git(repository, "branch", "--show-current").stdout.strip() == "main"
        assert (repository / "tracked.txt").read_text(encoding="utf-8") == "saved local work\n"
        assert "gitrepo-switch-main" in run_git(repository, "stash", "list").stdout
        return True

    monkeypatch.setattr(commit_handler, "execute_commit", inspect_commit)

    assert branch_handler.switch_and_commit(bp, "main", "fix: keep saved work")
    assert all(value in menu.question for value in ("tracked.txt", "dev-source", "main"))


def test_gtk_stash_conflict_maps_saved_work_to_git_theirs():
    captured = {}
    resolver = SimpleNamespace(
        _show_conflict_dialog=lambda files, source, target, local_side: (
            captured.update(
                files=files,
                source=source,
                target=target,
                local_side=local_side,
            )
            or True
        )
    )

    assert GTKConflictResolver._resolve_interactive_stash(resolver, ["tracked.txt"], "dev-source", "main")
    assert captured == {
        "files": ["tracked.txt"],
        "source": "dev-source",
        "target": "main",
        "local_side": "theirs",
    }


def test_commit_uses_the_configured_personal_branch(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    assert GitUtils.set_personal_branch("dev-personal", str(repository))
    tracked = _stage_and_modify(repository)
    monkeypatch.chdir(repository)
    menu = RecordingMenu()
    bp = SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu,
        conflict_resolver=None,
        dry_run_mode=False,
        args=SimpleNamespace(commit_file="", commit="fix: preserve personal branch"),
        settings={"auto_version_bump": False},
        repo_path=str(repository),
        github_user_name="wrong-user",
        last_commit_type=None,
    )

    def inspect_commit(_bp, _message, target_branch):
        assert target_branch == "dev-personal"
        assert run_git(repository, "branch", "--show-current").stdout.strip() == target_branch
        _assert_index_and_worktree_restored(repository, tracked)
        return True

    monkeypatch.setattr(commit_handler, "execute_commit", inspect_commit)

    assert commit_operations.commit_and_push(bp)
    assert "dev-personal" in menu.question


def test_commit_gui_suggests_the_configured_personal_branch(tmp_path, monkeypatch):
    from gitrepo.build_package.gui.repository_actions import RepositoryActionsMixin

    repository, _remote = create_repository_with_remote(tmp_path)
    assert GitUtils.set_personal_branch("dev-personal", str(repository))
    monkeypatch.chdir(repository)
    shown = {}
    window = SimpleNamespace(
        build_package=SimpleNamespace(github_user_name="wrong-user", repo_path=str(repository)),
        _show_commit_branch_dialog=lambda current, personal, protected: shown.update(
            current=current,
            personal=personal,
            protected=protected,
        ),
    )

    RepositoryActionsMixin.on_commit_requested(window, None, "fix: choose branch")

    assert shown == {"current": "main", "personal": "dev-personal", "protected": True}
    assert window._pending_commit_message == "fix: choose branch"


def test_pull_request_creation_routes_through_the_token_gate():
    from gitrepo.build_package.gui.branch_actions import BranchActionsMixin

    captured = {}

    class API:
        def create_pull_request(self, source, target, auto_merge, logger):
            captured["request"] = (source, target, auto_merge, logger)
            return {"number": 42}

    logger = Logger()

    def ensure_token(operation, title, description):
        captured["gate"] = (title, description)
        captured["result"] = operation()

    window = SimpleNamespace(
        build_package=SimpleNamespace(github_api=API(), logger=logger),
        _ensure_token_and_run=ensure_token,
    )

    BranchActionsMixin._on_merge_confirm_response(
        window,
        None,
        "create",
        "dev-personal",
        "main",
        True,
    )

    assert captured["request"] == ("dev-personal", "main", True, logger)
    assert captured["result"] == {"number": 42}
    assert "gate" in captured


def _commit_context(repository, menu):
    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu,
        conflict_resolver=None,
        dry_run_mode=False,
        args=SimpleNamespace(commit_file="", commit="fix: publish retry"),
        settings={"auto_version_bump": False},
        repo_path=str(repository),
        github_user_name="tester",
        last_commit_type=None,
    )


def _fail_pushes(monkeypatch, count):
    original_run = commit_handler.subprocess.run_git
    state = {"attempts": 0}

    def flaky_run(command, **kwargs):
        if command[:2] == ["git", "push"]:
            state["attempts"] += 1
            if state["attempts"] <= count:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="network unavailable")
        return original_run(command, **kwargs)

    monkeypatch.setattr(commit_handler.subprocess, "run_git", flaky_run)
    return state


def test_failed_commit_push_records_exact_recovery_details(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    remote_before = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    (repository / "tracked.txt").write_text("local commit\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    _fail_pushes(monkeypatch, count=1)
    bp = _commit_context(repository, RecordingMenu())

    assert not commit_operations.commit_and_push(bp)

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert bp.last_operation_details == {
        "local_commit_created": local_head,
        "current_branch": "main",
        "remote_unchanged": True,
        "retry_command": "git push -u origin refs/heads/main:refs/heads/main",
    }
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_before
    assert any("git push -u origin refs/heads/main:refs/heads/main" in message for _, message in bp.logger.messages)


def test_sync_failure_keeps_and_records_the_created_commit(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    remote_before = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    (repository / "tracked.txt").write_text("local commit\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        commit_handler,
        "_sync_branch",
        lambda _bp, _branch: (_ for _ in ()).throw(RuntimeError("sync failed")),
    )
    monkeypatch.setattr(
        commit_handler,
        "_push_branch",
        lambda _bp, _branch: pytest.fail("push must not run after failed synchronization"),
    )
    bp = _commit_context(repository, RecordingMenu())

    assert not commit_operations.commit_and_push(bp)

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert bp.last_operation_details == {
        "local_commit_created": local_head,
        "current_branch": "main",
        "remote_unchanged": True,
        "retry_command": "git push -u origin refs/heads/main:refs/heads/main",
    }
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_before


def test_clean_second_commit_request_retries_without_creating_a_commit(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local commit\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(commit_operations, "_", lambda message: message)
    attempts = _fail_pushes(monkeypatch, count=1)
    menu = RecordingMenu()
    bp = _commit_context(repository, menu)

    assert not commit_operations.commit_and_push(bp)
    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert commit_operations.commit_and_push(bp)

    assert attempts["attempts"] == 2
    assert run_git(repository, "rev-list", "--count", "HEAD^..HEAD").stdout.strip() == "1"
    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == local_head
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == local_head
    assert "No new commit will be created." in menu.questions[-1]
    assert "git push -u origin refs/heads/main:refs/heads/main" in menu.questions[-1]
    assert menu.defaults[-1] is False
    assert bp.last_operation_details == {}


def test_clean_restart_detects_branch_ahead_and_retries_push(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local commit\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(commit_operations, "_", lambda message: message)
    attempts = _fail_pushes(monkeypatch, count=1)

    assert not commit_operations.commit_and_push(_commit_context(repository, RecordingMenu()))
    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    restarted_menu = RecordingMenu()
    restarted = _commit_context(repository, restarted_menu)

    assert commit_operations.commit_and_push(restarted)

    assert attempts["attempts"] == 2
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == local_head
    assert "Local commits not on origin: 1" in restarted_menu.question
    assert restarted_menu.defaults[-1] is False


def test_pull_restores_staged_and_unstaged_state(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    tracked = _stage_and_modify(repository)
    monkeypatch.chdir(repository)

    assert pull_operations.pull_latest(_bp())
    _assert_index_and_worktree_restored(repository, tracked)


def test_pull_drops_resolved_conflicting_stash(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0 if command[2] == "drop" else 1, stdout="", stderr="conflict")

    resolver = SimpleNamespace(
        has_conflicts=lambda: True,
        resolve=lambda branch, incoming: branch == "main" and bool(incoming),
    )
    bp = SimpleNamespace(logger=Logger(), conflict_resolver=resolver)
    monkeypatch.setattr(pull_operations.subprocess, "run_git", fake_run)

    assert pull_operations._restore_stash(bp, "main")
    assert calls == [
        ["git", "stash", "pop", "--index"],
        ["git", "stash", "drop", "stash@{0}"],
    ]


def _version_context(repository, cache=None):
    return SimpleNamespace(
        repo_path=str(repository),
        _app_version_cache=str(cache) if cache else None,
        _app_version_warning_shown=False,
        logger=Logger(),
    )


def test_version_discovery_excludes_ignored_files_even_when_cached(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    (repository / ".gitignore").write_text(".audit/\n", encoding="utf-8")
    run_git(repository, "add", ".gitignore")
    run_git(repository, "commit", "-m", "ignore audit")
    (repository / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    source = repository / "widgets.py"
    source.write_text('APP_VERSION = "1.2.3"\nAPP_NAME = _("Widgets")\n', encoding="utf-8")
    audit = repository / ".audit"
    audit.mkdir()
    ignored = audit / "ruff_check.txt"
    ignored.write_text('APP_VERSION = "99.0.0"\nAPP_NAME = _("Widgets")\n', encoding="utf-8")
    monkeypatch.chdir(repository)

    file_path, _content, match = version_bumper._locate_app_version_entry(_version_context(repository, ignored))

    assert file_path == str(source)
    assert match.group(3) == "1.2.3"
    assert ".audit/ruff_check.txt" not in GitUtils.list_version_candidates(str(repository))


def test_version_discovery_does_not_follow_symlink_candidates(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    (repository / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text('APP_VERSION = "9.9.9"\nAPP_NAME = _("Widgets")\n', encoding="utf-8")
    link = repository / "widgets.py"
    link.symlink_to(outside)
    run_git(repository, "add", "widgets.py")
    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and os.path.realpath(path) == str(outside):
            pytest.fail("version discovery followed a symlink candidate")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.chdir(repository)

    assert version_bumper.plan_version_bump(_version_context(repository), "fix: safety") is None


def test_version_discovery_rejects_one_unmatched_application(tmp_path):
    (tmp_path / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    (tmp_path / "other.py").write_text(
        'APP_VERSION = "1.2.3"\nAPP_NAME = _("Other Application")\n',
        encoding="utf-8",
    )

    assert version_bumper._locate_app_version_entry(_version_context(tmp_path)) == (None, None, None)
