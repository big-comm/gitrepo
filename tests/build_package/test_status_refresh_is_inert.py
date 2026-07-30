"""The status refresh must not execute the repository it is inspecting."""

import os
from unittest import mock

import pytest

from gitrepo.build_package.core import repository_snapshot
from gitrepo.build_package.core.git_utils import GitUtils


PKGBUILD = """# Maintainer: someone
pkgname=biglinux-session-and-themes
pkgver=1.0
arch=('any')
"""


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "PKGBUILD").write_text(PKGBUILD, encoding="utf-8")
    with mock.patch.object(GitUtils, "get_repo_root_path", staticmethod(lambda: str(tmp_path))):
        yield tmp_path


def test_the_package_name_is_read_without_running_the_pkgbuild(repository):
    marker = repository / "executed"
    repository.joinpath("PKGBUILD").write_text(
        PKGBUILD + f"\ntouch {marker}\n",
        encoding="utf-8",
    )

    assert GitUtils.read_package_name() == "biglinux-session-and-themes"
    assert not marker.exists()


def test_a_quoted_name_is_accepted(repository):
    repository.joinpath("PKGBUILD").write_text('pkgname="big-store"\n', encoding="utf-8")

    assert GitUtils.read_package_name() == "big-store"


def test_an_array_pkgname_is_refused_rather_than_guessed(repository):
    # A split package declares pkgname=(a b); only makepkg resolves that, and
    # guessing would put a wrong name in the interface.
    repository.joinpath("PKGBUILD").write_text("pkgname=('one' 'two')\n", encoding="utf-8")

    assert GitUtils.read_package_name() == ""


@pytest.mark.parametrize("content", ["", "pkgver=1.0\n", "not a pkgbuild"])
def test_a_pkgbuild_without_a_name_reads_empty(repository, content):
    repository.joinpath("PKGBUILD").write_text(content, encoding="utf-8")

    assert GitUtils.read_package_name() == ""


def test_a_missing_pkgbuild_reads_empty(tmp_path):
    with mock.patch.object(GitUtils, "get_repo_root_path", staticmethod(lambda: str(tmp_path))):
        assert GitUtils.read_package_name() == ""


def test_the_snapshot_uses_the_non_executing_reader():
    # RepositorySnapshot.capture() runs on window construction and after every
    # operation, so it must never reach makepkg.
    source = repository_snapshot.__file__
    with open(source, "r", encoding="utf-8") as stream:
        text = stream.read()

    assert "read_package_name()" in text
    assert "get_package_name()" not in text


def test_only_the_build_journey_still_executes_the_pkgbuild():
    from gitrepo.build_package.core import package_operations

    executing_callers = []
    for module in (repository_snapshot, package_operations):
        with open(module.__file__, "r", encoding="utf-8") as stream:
            if "get_package_name()" in stream.read():
                executing_callers.append(os.path.basename(module.__file__))

    assert executing_callers == ["package_operations.py"]
