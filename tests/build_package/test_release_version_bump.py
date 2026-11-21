"""A package build bumps APP_VERSION for commits that never passed gitrepo's commit flow."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import package_operations, version_bumper

from .git_fixtures import Logger, run_git


def _repository(tmp_path: Path, version: str = "1.2.3") -> Path:
    repository = tmp_path / "widgets"
    repository.mkdir()
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Bump Test")
    run_git(repository, "config", "user.email", "bump@example.invalid")
    (repository / "PKGBUILD").write_text("pkgname=widgets\n", encoding="utf-8")
    (repository / "widgets.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-m", "feat: first release")
    return repository


def _commit(repository: Path, message: str) -> None:
    with (repository / "notes.txt").open("a", encoding="utf-8") as notes:
        notes.write(message + "\n")
    run_git(repository, "add", "notes.txt")
    run_git(repository, "commit", "-m", message)


def _context(repository: Path, confirm: bool = True, **overrides) -> SimpleNamespace:
    context = SimpleNamespace(
        repo_path=str(repository),
        _app_version_cache=None,
        _app_version_warning_shown=False,
        logger=Logger(),
        settings={"auto_version_bump": True},
        menu=SimpleNamespace(questions=[]),
    )

    def answer(question, default_yes=True):
        context.menu.questions.append(str(question))
        return confirm

    context.menu.confirm = answer
    for name, value in overrides.items():
        setattr(context, name, value)
    return context


def _version(repository: Path) -> str:
    return (repository / "widgets.py").read_text(encoding="utf-8")


def test_no_new_commits_no_bump(tmp_path):
    repository = _repository(tmp_path)

    assert version_bumper.plan_release_bump(_context(repository)) is None


# Expected versions follow Semantic Versioning 2.0.0: a feature resets the patch,
# a breaking change resets minor and patch; untyped commits count as fixes.
@pytest.mark.parametrize(
    ("messages", "level", "version"),
    [
        (["Fix the scroll routing", "fix: keep the socket short"], "patch", "1.2.4"),
        (["Fix the scroll routing", "feat(tabs): restore tabs after a crash"], "minor", "1.3.0"),
        (["fix!: drop the old settings format", "feat: add a thing"], "major", "2.0.0"),
        (["Refactor the parser\n\nBREAKING CHANGE: the CLI flags changed"], "major", "2.0.0"),
    ],
)
def test_highest_commit_type_decides(tmp_path, messages, level, version):
    repository = _repository(tmp_path)
    for message in messages:
        _commit(repository, message)

    plan = version_bumper.plan_release_bump(_context(repository))

    assert (plan.bump_level, plan.new_version, plan.commit_count) == (level, version, len(messages))


def test_merge_commits_are_ignored(tmp_path):
    repository = _repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-someone")
    _commit(repository, "Fix a typo")
    run_git(repository, "checkout", "main")
    run_git(repository, "merge", "--no-ff", "-m", "feat: merge pull request", "dev-someone")

    plan = version_bumper.plan_release_bump(_context(repository))

    assert (plan.bump_level, plan.commit_count) == ("patch", 1)


def test_committed_bump_is_final(tmp_path, monkeypatch):
    """A stable build after the testing build of the same commits keeps the version."""
    repository = _repository(tmp_path)
    _commit(repository, "feat: add a thing")
    monkeypatch.chdir(repository)
    assert package_operations._commit_release_bump(_context(repository)) is True

    assert version_bumper.plan_release_bump(_context(repository)) is None


def test_approved_bump_commits_alone(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    _commit(repository, "feat: add a thing")
    (repository / "draft.txt").write_text("not part of the bump\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    context = _context(repository)

    assert package_operations._commit_release_bump(context) is True

    assert 'APP_VERSION = "1.3.0"' in _version(repository)
    assert run_git(repository, "log", "-1", "--format=%s").stdout.strip() == "chore: bump version to 1.3.0"
    assert run_git(repository, "show", "--name-only", "--format=", "HEAD").stdout.split() == ["widgets.py"]
    assert "1.2.3 → 1.3.0" in context.menu.questions[0]


def test_declined_bump_changes_nothing(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    _commit(repository, "feat: add a thing")
    head = run_git(repository, "rev-parse", "HEAD").stdout
    monkeypatch.chdir(repository)

    assert package_operations._commit_release_bump(_context(repository, confirm=False)) is True

    assert run_git(repository, "rev-parse", "HEAD").stdout == head
    assert 'APP_VERSION = "1.2.3"' in _version(repository)


def test_setting_disables_release_bump(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    _commit(repository, "feat: add a thing")
    monkeypatch.chdir(repository)
    context = _context(repository, settings={"auto_version_bump": False})

    assert package_operations._commit_release_bump(context) is True

    assert context.menu.questions == []
    assert 'APP_VERSION = "1.2.3"' in _version(repository)
