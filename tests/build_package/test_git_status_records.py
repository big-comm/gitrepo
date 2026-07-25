"""Paths survive Git's record format, whatever bytes they contain."""

import importlib

import pytest

from gitrepo.build_package.core.git_status import (
    display_path,
    parse_path_records,
    parse_status_records,
)

from .git_fixtures import create_repository_with_remote, run_git


def test_status_records_keep_paths_that_line_parsing_would_mangle():
    record = b'R  new name.txt\x00old name.txt\x00 M with"quote.py\x00?? with\nnewline.md\x00'

    assert parse_status_records(record) == (
        ("R", "new name.txt"),
        ("M", 'with"quote.py'),
        ("??", "with\nnewline.md"),
    )


def test_path_records_drop_only_the_empty_trailer():
    assert parse_path_records(b"a.txt\x00b with space.txt\x00") == ("a.txt", "b with space.txt")
    assert parse_path_records(b"") == ()


def test_display_path_cannot_forge_extra_lines_in_a_confirmation():
    # A crafted name must not be able to add a bullet the user did not approve.
    assert display_path("evil.txt\n• innocent.txt") == "evil.txt\\n• innocent.txt"
    assert display_path("plain/path.py") == "plain/path.py"


def test_changed_files_report_a_newline_in_a_real_filename(build_package_modules, tmp_path, monkeypatch):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    repository, _remote = create_repository_with_remote(tmp_path)
    (repository / "two\nlines.txt").write_text("content\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    changed = git_utils.GitUtils.get_changed_files()

    assert ("??", "two\nlines.txt") in changed


def test_snapshot_and_conflict_enumeration_read_the_same_records(build_package_modules, tmp_path, monkeypatch):
    snapshots = importlib.import_module("gitrepo.build_package.core.repository_snapshot")
    conflict_resolver = importlib.import_module("gitrepo.build_package.core.conflict_resolver")
    repository, _remote = create_repository_with_remote(tmp_path)

    conflicted = 'quoted"and space.txt'
    run_git(repository, "checkout", "-b", "incoming")
    (repository / conflicted).write_text("theirs\n", encoding="utf-8")
    run_git(repository, "add", "--", conflicted)
    run_git(repository, "commit", "-m", "theirs")
    run_git(repository, "checkout", "main")
    (repository / conflicted).write_text("ours\n", encoding="utf-8")
    run_git(repository, "add", "--", conflicted)
    run_git(repository, "commit", "-m", "ours")
    import subprocess

    subprocess.run(["git", "merge", "incoming"], cwd=repository, capture_output=True)
    monkeypatch.chdir(repository)

    resolver = conflict_resolver.ConflictResolver(None, None)
    assert resolver.get_conflict_files() == [conflicted]

    snapshot = snapshots.RepositorySnapshot.capture()
    assert any(path == conflicted for _status, path in snapshot.changed_files)


@pytest.mark.parametrize("returncode", [128, 1])
def test_an_unreadable_status_never_reads_as_a_clean_tree(build_package_modules, monkeypatch, returncode):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")

    def failing(command, **kwargs):
        import subprocess as std

        return std.CompletedProcess(command, returncode, stdout=b"", stderr=b"")

    monkeypatch.setattr(git_utils.subprocess, "run_git", failing)

    # Every caller uses this as a guard before rewriting the working tree.
    assert git_utils.GitUtils.has_changes() is True
