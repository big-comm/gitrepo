"""Go back to a commit, and undo: on real repositories, here and on origin."""

import subprocess

import pytest

from gitrepo.build_package.core import history, main_sync

from .git_fixtures import create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")


class _Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class _Bp:
    def __init__(self, answer=True):
        self.logger = _Logger()
        self.menu = type("Menu", (), {"confirm": lambda _self, question, default_yes=True: answer})()


def _sha(repository, ref):
    return run_git(repository, "rev-parse", ref).stdout.strip()


def _commit(repository, filename, content="x\n", remove=None):
    if remove:
        run_git(repository, "rm", "-q", remove)
    else:
        (repository / filename).write_text(content, encoding="utf-8")
        run_git(repository, "add", filename)
    run_git(repository, "commit", "-m", f"change {remove or filename}")
    return _sha(repository, "HEAD")


def _work_branch(tmp_path, monkeypatch):
    """dev-me with three published commits on top of main: one, two, three."""
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    one = _commit(repository, "one.txt")
    two = _commit(repository, "two.txt")
    three = _commit(repository, "three.txt")
    run_git(repository, "push", "-u", "origin", "dev-me")
    monkeypatch.chdir(repository)
    return repository, remote, (one, two, three)


def test_go_back_previews_what_leaves_and_moves_branch_and_origin(tmp_path, monkeypatch):
    repository, _remote, (one, _two, three) = _work_branch(tmp_path, monkeypatch)

    preview = history.preview_go_back(one)

    assert {change.path for change in preview.files} == {"two.txt", "three.txt"}
    assert all(change.status == "D" for change in preview.files)
    assert any(tone == "warning" and "2 file(s) will be deleted" in text for tone, text in preview.notices)
    assert len([step for step in preview.steps if step.text.startswith("Leaves dev-me")]) == 2
    assert preview.remote_steps, "the branch is published, so GitHub can follow"

    assert history.go_back(_Bp(), one, include_remote=True)

    assert _sha(repository, "dev-me") == one
    run_git(repository, "fetch", "-q", "origin")
    assert _sha(repository, "origin/dev-me") == one
    checkpoint, _reason = history.latest_checkpoint()
    assert checkpoint.pushes and checkpoint.pushes[0].before == three


def test_undo_brings_the_commits_back_here_and_on_origin(tmp_path, monkeypatch):
    repository, _remote, (one, _two, three) = _work_branch(tmp_path, monkeypatch)
    history.go_back(_Bp(), one, include_remote=True)
    checkpoint, _reason = history.latest_checkpoint()

    preview = history.preview_undo(checkpoint)
    assert {change.path for change in preview.files} == {"two.txt", "three.txt"}
    assert all(change.status == "A" for change in preview.files)

    assert history.undo(_Bp(), checkpoint, include_remote=True)

    assert _sha(repository, "dev-me") == three
    run_git(repository, "fetch", "-q", "origin")
    assert _sha(repository, "origin/dev-me") == three
    assert history.latest_checkpoint()[0] is None


def test_undo_only_here_leaves_github_alone(tmp_path, monkeypatch):
    repository, _remote, (one, _two, three) = _work_branch(tmp_path, monkeypatch)
    history.go_back(_Bp(), one, include_remote=True)

    assert history.undo(_Bp(), history.latest_checkpoint()[0], include_remote=False)

    assert _sha(repository, "dev-me") == three
    run_git(repository, "fetch", "-q", "origin")
    assert _sha(repository, "origin/dev-me") == one


def test_undo_refuses_once_the_branch_moved_again(tmp_path, monkeypatch):
    repository, _remote, (one, _two, _three) = _work_branch(tmp_path, monkeypatch)
    history.go_back(_Bp(), one, include_remote=False)
    _commit(repository, "later.txt")

    checkpoint, reason = history.latest_checkpoint()

    assert checkpoint is None
    assert "dev-me changed after" in reason


def test_uncommitted_work_survives_and_a_conflict_stops_the_move(tmp_path, monkeypatch):
    repository, _remote, (one, two, _three) = _work_branch(tmp_path, monkeypatch)
    (repository / "notes.txt").write_text("unsaved\n", encoding="utf-8")

    assert history.go_back(_Bp(), two, include_remote=False)
    assert (repository / "notes.txt").read_text(encoding="utf-8") == "unsaved\n"

    (repository / "two.txt").write_text("edited, not committed\n", encoding="utf-8")
    bp = _Bp()
    assert not history.go_back(bp, one, include_remote=False)
    assert _sha(repository, "dev-me") == two
    assert (repository / "two.txt").read_text(encoding="utf-8") == "edited, not committed\n"
    assert "commit or stash them" in bp.logger.text()


def test_main_is_never_moved_back(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    base = _sha(repository, "HEAD")
    _commit(repository, "more.txt")
    monkeypatch.chdir(repository)

    allowed, reason = history.can_go_back("main")
    bp = _Bp()

    assert not allowed and "shared" in reason
    assert not history.go_back(bp, base, include_remote=False)
    assert _sha(repository, "main") != base


def test_github_is_not_rewritten_over_someone_elses_push(tmp_path, monkeypatch):
    repository, remote, (one, _two, _three) = _work_branch(tmp_path, monkeypatch)
    history.go_back(_Bp(), one, include_remote=True)
    other = tmp_path / "colleague"
    subprocess.run(["git", "clone", "-q", "-b", "dev-me", str(remote), str(other)], check=True)
    run_git(other, "config", "user.name", "Colleague")
    run_git(other, "config", "user.email", "c@example.invalid")
    colleague = _commit(other, "theirs.txt")
    run_git(other, "push", "-q", "origin", "dev-me")

    bp = _Bp()
    assert not history.undo(bp, history.latest_checkpoint()[0], include_remote=True)

    assert "GitHub was not changed" in bp.logger.text()
    assert run_git(other, "ls-remote", "origin", "refs/heads/dev-me").stdout.split()[0] == colleague


def _merge_that_drops_files(tmp_path, monkeypatch):
    """The big-multimedia case: main merged dev-me but kept main's layout."""
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    for player in ("audio", "video"):
        (repository / player).mkdir()
        _commit(repository, f"{player}/PKGBUILD", f"{player}\n")
    run_git(repository, "push", "-q", "-u", "origin", "dev-me")
    mine = _sha(repository, "dev-me")
    run_git(repository, "checkout", "-q", "main")
    run_git(repository, "merge", "-q", "--no-ff", "-s", "ours", "dev-me", "-m", "Merge dev-me into main")
    run_git(repository, "push", "-q", "origin", "main")
    run_git(repository, "checkout", "-q", "dev-me")
    monkeypatch.chdir(repository)
    return repository, mine


def test_sync_warns_before_a_merge_drops_files_and_undo_restores_them(tmp_path, monkeypatch):
    repository, mine = _merge_that_drops_files(tmp_path, monkeypatch)

    plan, reason = main_sync.prepare_sync()
    assert plan is not None, reason
    deleted = {change.path for change in plan.preview.files if change.status == "D"}
    assert deleted == {"audio/PKGBUILD", "video/PKGBUILD"}
    assert any(tone == "warning" for tone, _text in plan.preview.notices)

    assert main_sync.execute_sync(_Bp(), plan)
    assert not (repository / "audio" / "PKGBUILD").exists()

    checkpoint, _reason = history.latest_checkpoint()
    assert checkpoint.operation == "Synchronize with main" and checkpoint.pushes
    assert history.undo(_Bp(), checkpoint, include_remote=True)

    assert _sha(repository, "dev-me") == mine
    assert (repository / "audio" / "PKGBUILD").exists()
    run_git(repository, "fetch", "-q", "origin")
    assert _sha(repository, "origin/dev-me") == mine


def test_the_window_runner_keeps_a_checkpoint_for_any_operation(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from gitrepo.build_package.gui.dialogs.progress_dialog import OperationRunner

    repository, _remote, (_one, _two, three) = _work_branch(tmp_path, monkeypatch)
    runner = OperationRunner.__new__(OperationRunner)

    wrapped = runner._with_checkpoint(lambda: _commit(repository, "four.txt"), "Publish changes")
    wrapped()

    checkpoint = runner._last_checkpoint
    assert checkpoint.operation == "Publish changes"
    assert [(move.branch, move.before) for move in checkpoint.moves] == [("dev-me", three)]


def test_a_preview_reads_as_plain_text_for_the_terminal(tmp_path, monkeypatch):
    _repository, _remote, (one, _two, _three) = _work_branch(tmp_path, monkeypatch)

    text = history.preview_text(history.preview_go_back(one))

    assert text.startswith("Go back to ")
    assert "deleted: two.txt" in text and "git reset --keep" in text


class _ScriptedMenu:
    def __init__(self, picks, confirms):
        self.picks, self.confirms, self.questions = list(picks), list(confirms), []

    def show_menu(self, title, options, default_index=0, additional_content=None):
        pick = self.picks.pop(0)
        return pick, options[pick]

    def confirm(self, question, default_yes=True):
        self.questions.append(str(question))
        return self.confirms.pop(0)


def test_terminal_go_back_and_undo_show_the_preview_first(tmp_path, monkeypatch):
    from gitrepo.build_package.core import branch_menu

    repository, _remote, (one, _two, three) = _work_branch(tmp_path, monkeypatch)
    bp = _Bp()
    # Commits listed after the current one: two, one, base. Pick "one" (index 1);
    # confirm the preview, then decline GitHub.
    bp.menu = _ScriptedMenu([1], [True, False])
    branch_menu._go_back_flow(bp)

    assert _sha(repository, "dev-me") == one
    assert bp.menu.questions[0].startswith(f"Go back to {one[:8]}?")
    run_git(repository, "fetch", "-q", "origin")
    assert _sha(repository, "origin/dev-me") == three

    bp.menu = _ScriptedMenu([], [True])
    branch_menu._undo_flow(bp)

    assert _sha(repository, "dev-me") == three
    assert bp.menu.questions[0].startswith("Undo “Go back to")


def test_after_a_sync_onto_a_merge_the_previous_own_commit_is_listed(tmp_path, monkeypatch):
    repository, mine = _merge_that_drops_files(tmp_path, monkeypatch)
    plan, _reason = main_sync.prepare_sync()
    main_sync.execute_sync(_Bp(), plan)

    listed = [commit["sha"] for commit in history.recent_commits()]

    assert listed[0] == _sha(repository, "dev-me") != mine
    assert mine in listed
