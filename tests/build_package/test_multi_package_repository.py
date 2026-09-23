"""A repository may keep several packages side by side, one per subdirectory.

The usual layout -- one PKGBUILD at the root or in pkgbuild/ -- must resolve
exactly as before; only a repository with neither is searched one level down,
and then the package to build is chosen rather than guessed.
"""

from unittest import mock

import pytest

from gitrepo.build_package.core import package_operations, repository_snapshot
from gitrepo.build_package.core.git_utils import GitUtils, _pkgbuild_directory
from gitrepo.build_package.core.github_api import GitHubAPI


KERNEL = 'pkgbase=linux-big\npkgname=("$pkgbase" "$pkgbase-headers")\n'
KERNEL_LTS = 'pkgbase=linux-big-lts\npkgname=("$pkgbase" "$pkgbase-headers")\n'


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


def _package(root, directory, content="pkgname=demo\n"):
    path = root / directory if directory else root
    path.mkdir(parents=True, exist_ok=True)
    (path / "PKGBUILD").write_text(content, encoding="utf-8")


@pytest.fixture
def repository(tmp_path):
    with mock.patch.object(GitUtils, "get_repo_root_path", staticmethod(lambda: str(tmp_path))):
        yield tmp_path


@pytest.mark.parametrize("usual", ["", "pkgbuild"])
def test_the_usual_layout_ignores_packages_in_other_directories(repository, usual):
    _package(repository, usual, "pkgname=main-package\n")
    _package(repository, "tests-fixture", "pkgname=fixture\n")

    assert GitUtils.list_package_directories() == []
    expected = repository / usual if usual else repository
    assert _pkgbuild_directory(str(repository)) == str(expected)
    assert GitUtils.read_package_name() == "main-package"


def test_several_packages_are_listed_and_none_is_guessed(repository):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)

    assert GitUtils.list_package_directories() == ["linux-big", "linux-big-lts"]
    assert _pkgbuild_directory(str(repository)) == ""
    assert GitUtils.read_package_name() == ""


def test_a_chosen_package_resolves_and_a_split_package_is_named_by_its_pkgbase(repository):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)

    assert _pkgbuild_directory(str(repository), "linux-big-lts") == str(repository / "linux-big-lts")
    assert GitUtils.read_package_name("linux-big-lts") == "linux-big-lts"


@pytest.mark.parametrize("chosen", ["missing", "..", "../elsewhere", "/etc", "linux-big/.."])
def test_a_choice_outside_the_listed_packages_is_refused(repository, chosen):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)

    assert _pkgbuild_directory(str(repository), chosen) == ""


def test_a_single_package_in_a_subdirectory_needs_no_choice(repository):
    _package(repository, "linux-big", KERNEL)

    assert _pkgbuild_directory(str(repository)) == str(repository / "linux-big")
    assert GitUtils.read_package_name() == "linux-big"


def test_hidden_and_symlinked_directories_are_not_packages(repository, tmp_path_factory):
    _package(repository, "linux-big", KERNEL)
    _package(repository, ".cache", KERNEL_LTS)
    outside = tmp_path_factory.mktemp("outside")
    _package(outside, "", KERNEL_LTS)
    (repository / "linked").symlink_to(outside, target_is_directory=True)

    assert GitUtils.list_package_directories() == ["linux-big"]


def test_the_snapshot_names_every_package(repository):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)

    assert repository_snapshot._package_display_name() == "linux-big, linux-big-lts"


def _dispatch(monkeypatch, **extra):
    monkeypatch.setattr(GitUtils, "get_repo_name", staticmethod(lambda: "big-comm/big-kernel"))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: "dev-tester"))
    _event, data = GitHubAPI._package_workflow_dispatch("linux-big", "testing", "dev-tester", False, Logger(), **extra)
    return data["client_payload"]


def test_a_single_package_payload_is_unchanged(monkeypatch):
    assert "pkgbuild_dir" not in _dispatch(monkeypatch)


def test_the_chosen_package_directory_is_sent(monkeypatch):
    assert _dispatch(monkeypatch, package_directory="linux-big-lts")["pkgbuild_dir"] == "linux-big-lts"


class Menu:
    def __init__(self, answer):
        self.answer = answer
        self.titles = []
        self.options = []

    def show_menu(self, title, options, **_kwargs):
        self.titles.append(title)
        self.options.append(options)
        return self.answer(options)


def test_the_journey_asks_which_package_to_build(repository):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)
    menu = Menu(lambda options: (1, options[1]))
    bp = mock.Mock(menu=menu, logger=Logger())

    assert package_operations._choose_package_directory(bp) == "linux-big-lts"
    assert menu.options == [["linux-big/", "linux-big-lts/"]]


def test_cancelling_the_choice_stops_the_journey(repository):
    _package(repository, "linux-big", KERNEL)
    _package(repository, "linux-big-lts", KERNEL_LTS)
    bp = mock.Mock(menu=Menu(lambda _options: None), logger=Logger())

    assert package_operations._choose_package_directory(bp) is None


def test_the_usual_layout_is_never_asked(repository):
    _package(repository, "", "pkgname=demo\n")
    menu = Menu(lambda _options: pytest.fail("a single-package repository must not be asked"))

    assert package_operations._choose_package_directory(mock.Mock(menu=menu, logger=Logger())) == ""
