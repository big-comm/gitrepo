"""Only a GitHub origin may address the GitHub API."""

import importlib

import pytest


@pytest.fixture
def git_utils(build_package_modules):
    return importlib.import_module("gitrepo.build_package.core.git_utils")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/widgets.git",
        "https://github.com/acme/widgets",
        "http://github.com/acme/widgets",
        "https://user:token@github.com/acme/widgets.git",
        "ssh://git@github.com/acme/widgets.git",
        "ssh://git@github.com:22/acme/widgets.git",
        "git://github.com/acme/widgets.git",
        "git@github.com:acme/widgets.git",
        "git@github.com:acme/widgets",
        "https://www.github.com/acme/widgets",
        "  https://github.com/acme/widgets.git  ",
    ],
)
def test_every_github_remote_form_resolves_to_the_same_repository(git_utils, url):
    host, owner, repository = git_utils.parse_github_remote(url)

    assert (owner, repository) == ("acme", "widgets")
    assert host in git_utils.GITHUB_HOSTS


@pytest.mark.parametrize(
    "url",
    [
        # Another forge that happens to use the same owner/repository names.
        "https://gitlab.com/acme/widgets.git",
        "git@gitlab.com:acme/widgets.git",
        "https://codeberg.org/acme/widgets",
        "ssh://git@git.example.com/acme/widgets.git",
        # Look-alike hosts.
        "https://github.com.evil.test/acme/widgets",
        "https://notgithub.com/acme/widgets",
        # Path shapes that are not exactly owner/repository.
        "https://github.com/acme",
        "https://github.com/acme/widgets/extra",
        "https://github.com/acme/",
        # Traversal attempts.
        "https://github.com/../..",
        "https://github.com/acme/..",
        "git@github.com:../../etc/passwd",
        # Unsupported transports and empty input.
        "file:///srv/git/acme/widgets.git",
        "/srv/git/acme/widgets",
        "",
        "   ",
    ],
)
def test_non_github_and_malformed_remotes_resolve_to_nothing(git_utils, url):
    assert git_utils.parse_github_remote(url) == ("", "", "")


def test_repository_name_is_empty_when_origin_is_not_github(git_utils, monkeypatch):
    monkeypatch.setattr(git_utils.GitUtils, "get_origin_url", staticmethod(lambda: "https://gitlab.com/acme/widgets"))

    assert git_utils.GitUtils.get_repo_name() == ""
    assert git_utils.GitUtils.get_canonical_repository() == ""


def test_confirmations_can_name_the_canonical_repository(git_utils, monkeypatch):
    monkeypatch.setattr(git_utils.GitUtils, "get_origin_url", staticmethod(lambda: "git@github.com:acme/widgets.git"))

    assert git_utils.GitUtils.get_repo_name() == "acme/widgets"
    assert git_utils.GitUtils.get_canonical_repository() == "github.com/acme/widgets"


def test_destructive_github_cleanups_stop_before_any_request(build_package_modules, monkeypatch):
    github_api = importlib.import_module("gitrepo.build_package.core.github_api")

    def forbidden(*args, **kwargs):
        raise AssertionError("no GitHub request may be made for a non-GitHub origin")

    monkeypatch.setattr(github_api.GitUtils, "get_repo_name", staticmethod(lambda: ""))
    monkeypatch.setattr(github_api.requests, "get", forbidden)
    monkeypatch.setattr(github_api.requests, "delete", forbidden)

    class Logger:
        def __init__(self):
            self.messages = []

        def log(self, style, message):
            self.messages.append((style, message))

        def die(self, style, message):
            self.messages.append((style, message))

    class Menu:
        def confirm(self, question, default_yes=True):
            raise AssertionError("nothing may be confirmed before the repository is known")

    api = github_api.GitHubAPI("token", "acme")

    assert api.clean_action_jobs("failure", Logger(), Menu()) is False
    assert api.clean_all_tags(Logger(), Menu()) is False
