"""execute_commit is the GUI publish path; it must refuse an unresolved merge."""

from types import SimpleNamespace
from unittest import mock

import pytest

from gitrepo.build_package.core import commit_handler


class _Resolver:
    def __init__(self, conflicts: bool, resolved: bool = False):
        self._conflicts = conflicts
        self._resolved = resolved
        self.resolve_calls = 0

    def has_conflicts(self):
        return self._conflicts

    def resolve(self):
        self.resolve_calls += 1
        return self._resolved


def _bp(resolver=None):
    logged = []
    return (
        SimpleNamespace(
            logger=SimpleNamespace(log=lambda style, message: logged.append((style, message))),
            conflict_resolver=resolver,
            menu=None,
        ),
        logged,
    )


@pytest.fixture
def git_calls():
    with mock.patch.object(commit_handler.subprocess, "run_git") as run_git:
        run_git.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(commit_handler.GitUtils, "get_current_branch", staticmethod(lambda: "dev-someone")):
            yield run_git


def test_an_unresolved_merge_is_refused_before_anything_is_staged(git_calls):
    bp, logged = _bp(_Resolver(conflicts=True, resolved=False))

    assert commit_handler.execute_commit(bp, "feat: x") is False
    # The repository lock probes git, but nothing may stage or commit: `git add
    # -A` would stage the conflict markers and the commit would complete the
    # merge around them.
    argv = [call.args[0] for call in git_calls.call_args_list]
    assert ["git", "add", "-A"] not in argv
    assert not any(command[:2] == ["git", "commit"] or command[:2] == ["git", "push"] for command in argv)
    # The reason is reported as an error. Asserting the text would only test the
    # active translation, so check the level the user actually sees.
    assert [style for style, _message in logged] == ["red"]


def test_a_resolved_merge_proceeds(git_calls):
    resolver = _Resolver(conflicts=True, resolved=True)
    bp, _logged = _bp(resolver)

    with mock.patch.object(commit_handler, "_sync_branch"), mock.patch.object(commit_handler, "_push_branch"):
        assert commit_handler.execute_commit(bp, "feat: x") is True

    assert resolver.resolve_calls == 1
    assert ["git", "add", "-A"] in [call.args[0] for call in git_calls.call_args_list]


def test_a_repository_without_conflicts_is_unaffected(git_calls):
    bp, _logged = _bp(_Resolver(conflicts=False))

    with mock.patch.object(commit_handler, "_sync_branch"), mock.patch.object(commit_handler, "_push_branch"):
        assert commit_handler.execute_commit(bp, "feat: x") is True

    assert ["git", "add", "-A"] in [call.args[0] for call in git_calls.call_args_list]


def test_a_caller_without_a_resolver_still_publishes(git_calls):
    # The CLI passes a resolver; a bare adapter may not, and must not break.
    bp, _logged = _bp(resolver=None)

    with mock.patch.object(commit_handler, "_sync_branch"), mock.patch.object(commit_handler, "_push_branch"):
        assert commit_handler.execute_commit(bp, "feat: x") is True


def test_the_publish_path_runs_under_the_repository_lock():
    # Without @journey a GUI publish could interleave with another journey.
    assert hasattr(commit_handler.execute_commit, "__wrapped__")
