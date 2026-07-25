"""The version bump is reviewed before it is written, and written atomically."""

import os
from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import commit_operations, version_bumper


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


def _bumper(tmp_path, **overrides):
    context = {
        "repo_path": str(tmp_path),
        "_app_version_cache": None,
        "_app_version_warning_shown": False,
        "logger": Logger(),
    }
    context.update(overrides)
    return SimpleNamespace(**context)


def _repository(tmp_path, version="1.2.3"):
    (tmp_path / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    source = tmp_path / "widgets.py"
    source.write_text(f'APP_VERSION = "{version}"\nAPP_NAME = _("Widgets")\n', encoding="utf-8")
    return source


def test_planning_a_bump_changes_nothing_on_disk(tmp_path):
    source = _repository(tmp_path)
    before = source.read_bytes()

    plan = version_bumper.plan_version_bump(_bumper(tmp_path), "feat: add a thing")

    assert plan.new_version == "1.3.0"
    assert plan.current_version == "1.2.3"
    assert plan.relative_path == "widgets.py"
    assert source.read_bytes() == before


def test_publishing_the_plan_keeps_the_original_permissions(tmp_path):
    source = _repository(tmp_path)
    os.chmod(source, 0o644)
    context = _bumper(tmp_path)

    plan = version_bumper.plan_version_bump(context, "feat: add a thing")
    assert version_bumper.publish_version_bump(context, plan) is True

    assert 'APP_VERSION = "1.3.0"' in source.read_text(encoding="utf-8")
    assert oct(os.stat(source).st_mode & 0o777) == "0o644"


def test_a_symlinked_candidate_never_rewrites_a_file_outside_the_repository(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.py"
    victim.write_text('APP_VERSION = "9.9.9"\n', encoding="utf-8")
    original = victim.read_bytes()

    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    (repository / "widgets.py").symlink_to(victim)

    context = _bumper(repository)
    plan = version_bumper.plan_version_bump(context, "feat: add a thing")

    assert plan is None
    assert victim.read_bytes() == original
    # The refused path is named; the sentence around it is translated.
    assert any("widgets.py" in message for _style, message in context.logger.messages)


def test_a_failed_write_leaves_the_source_byte_identical(tmp_path, monkeypatch):
    source = _repository(tmp_path)
    before = source.read_bytes()
    context = _bumper(tmp_path)
    plan = version_bumper.plan_version_bump(context, "feat: add a thing")

    def failing_write(path, content, *, mode=0o600):
        raise OSError("No space left on device")

    monkeypatch.setattr(version_bumper, "atomic_write_text", failing_write)

    assert version_bumper.publish_version_bump(context, plan) is False
    assert source.read_bytes() == before


class Menu:
    def __init__(self, answer=True):
        self.answer = answer
        self.question = ""

    def confirm(self, question, default_yes=True):
        self.question = question
        return self.answer


def _publishing_context(tmp_path, monkeypatch, menu):
    monkeypatch.setattr(commit_operations.GitUtils, "has_changes", staticmethod(lambda: True))
    monkeypatch.setattr(commit_operations.GitUtils, "has_commits", staticmethod(lambda: True))
    monkeypatch.setattr(commit_operations.GitUtils, "get_current_branch", staticmethod(lambda: "dev-tester"))
    # get_changed_files() answers with (status, path) records.
    monkeypatch.setattr(commit_operations.GitUtils, "get_changed_files", staticmethod(lambda: [("M", "README.md")]))
    return SimpleNamespace(
        is_git_repo=True,
        conflict_resolver=None,
        args=SimpleNamespace(commit_file="", commit="feat: add a thing"),
        settings={"auto_version_bump": True},
        menu=menu,
        logger=Logger(),
        repo_path=str(tmp_path),
        github_user_name="tester",
        last_commit_type=None,
        _app_version_cache=None,
        _app_version_warning_shown=False,
        dry_run_mode=False,
    )


def test_the_confirmation_names_the_exact_version_change(tmp_path, monkeypatch):
    _repository(tmp_path)
    menu = Menu(answer=False)
    context = _publishing_context(tmp_path, monkeypatch, menu)

    assert commit_operations.commit_and_push(context) is False

    assert "1.2.3 → 1.3.0" in menu.question
    assert "widgets.py" in menu.question


def test_declining_the_confirmation_leaves_the_version_untouched(tmp_path, monkeypatch):
    source = _repository(tmp_path)
    before = source.read_bytes()
    context = _publishing_context(tmp_path, monkeypatch, Menu(answer=False))

    assert commit_operations.commit_and_push(context) is False
    assert source.read_bytes() == before


def test_a_dry_run_reviews_the_bump_without_writing_it(tmp_path, monkeypatch):
    source = _repository(tmp_path)
    before = source.read_bytes()
    menu = Menu(answer=True)
    context = _publishing_context(tmp_path, monkeypatch, menu)
    context.dry_run_mode = True

    assert commit_operations.commit_and_push(context) is True

    assert "1.2.3 → 1.3.0" in menu.question
    assert source.read_bytes() == before


def test_publication_stops_when_the_reviewed_bump_cannot_be_written(tmp_path, monkeypatch):
    _repository(tmp_path)
    context = _publishing_context(tmp_path, monkeypatch, Menu(answer=True))

    monkeypatch.setattr(commit_operations, "publish_version_bump", lambda _context, _plan: False)
    monkeypatch.setattr(
        commit_operations,
        "execute_commit",
        lambda *args, **kwargs: pytest.fail("nothing may be committed after a failed bump"),
    )

    # execute_commit fails the test if it runs, so returning False here proves
    # the publication stopped rather than committing without the reviewed bump.
    assert commit_operations.commit_and_push(context) is False
    assert any(style == "red" for style, _message in context.logger.messages)
