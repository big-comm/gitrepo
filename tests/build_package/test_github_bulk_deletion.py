"""A bulk deletion covers every page and never overstates what it removed."""

import importlib

import pytest

from .git_fixtures import AlwaysConfirm, Logger


@pytest.fixture
def github_api(build_package_modules, monkeypatch):
    module = importlib.import_module("gitrepo.build_package.core.github_api")
    monkeypatch.setattr(module.GitUtils, "get_repo_name", staticmethod(lambda: "acme/widgets"))
    monkeypatch.setattr(module.GitUtils, "get_canonical_repository", staticmethod(lambda: "github.com/acme/widgets"))
    return module


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def _paged_runs(total):
    """Answer like GitHub: full pages until the last, partial one."""

    def get(url, params=None, **kwargs):
        params = params or {}
        size = params["per_page"]
        start = (params["page"] - 1) * size
        batch = [{"id": index, "display_title": f"run {index}"} for index in range(start, min(start + size, total))]
        return Response({"workflow_runs": batch})

    return get


def test_actions_cleanup_covers_every_page_not_just_the_first(github_api, monkeypatch):
    api = github_api.GitHubAPI("token", "acme")
    monkeypatch.setattr(github_api.requests, "get", _paged_runs(250))
    deleted = []
    monkeypatch.setattr(github_api.requests, "delete", lambda url, **kwargs: deleted.append(url) or Response(None, 204))

    assert api.clean_action_jobs("failure", Logger(), AlwaysConfirm()) is True
    assert len(deleted) == 250


def test_a_confirmation_states_how_many_items_it_covers(github_api, monkeypatch):
    api = github_api.GitHubAPI("token", "acme")
    monkeypatch.setattr(github_api.requests, "get", _paged_runs(150))
    monkeypatch.setattr(github_api.requests, "delete", lambda url, **kwargs: Response(None, 204))

    class RecordingMenu:
        question = ""

        def confirm(self, question, default_yes=True):
            self.question = question
            return False

    menu = RecordingMenu()
    assert api.clean_action_jobs("failure", Logger(), menu) is False
    assert "150" in menu.question
    assert "github.com/acme/widgets" in menu.question


def test_a_partial_deletion_is_reported_as_a_failure(github_api, monkeypatch):
    api = github_api.GitHubAPI("token", "acme")
    monkeypatch.setattr(github_api.requests, "get", _paged_runs(3))

    def delete(url, **kwargs):
        return Response(None, 204 if url.endswith("/0") else 403)

    monkeypatch.setattr(github_api.requests, "delete", delete)
    logger = Logger()

    # Two of three survived, so reporting success would be a lie.
    assert api.clean_action_jobs("failure", logger, AlwaysConfirm()) is False
    reported = " ".join(message for _style, message in logger.messages)
    assert "1" in reported and "3" in reported


def test_a_failed_listing_deletes_nothing(github_api, monkeypatch):
    api = github_api.GitHubAPI("token", "acme")
    monkeypatch.setattr(github_api.requests, "get", lambda url, **kwargs: Response({}, 502))
    monkeypatch.setattr(
        github_api.requests,
        "delete",
        lambda *args, **kwargs: pytest.fail("nothing may be deleted when the listing failed"),
    )

    class Menu:
        def confirm(self, question, default_yes=True):
            raise AssertionError("nothing may be confirmed when the listing failed")

    assert api.clean_action_jobs("failure", Logger(), Menu()) is False


def test_tag_cleanup_also_paginates_and_reports_partial_results(github_api, monkeypatch):
    api = github_api.GitHubAPI("token", "acme")

    def get(url, params=None, **kwargs):
        params = params or {}
        size = params["per_page"]
        start = (params["page"] - 1) * size
        return Response([{"name": f"v{index}"} for index in range(start, min(start + size, 120))])

    monkeypatch.setattr(github_api.requests, "get", get)
    deleted = []

    def delete(url, **kwargs):
        deleted.append(url)
        return Response(None, 204 if len(deleted) < 120 else 404)

    monkeypatch.setattr(github_api.requests, "delete", delete)

    assert api.clean_all_tags(Logger(), AlwaysConfirm()) is False
    assert len(deleted) == 120
