"""Branch overview: each branch against origin and against main, on real repositories."""

import subprocess

import pytest

from gitrepo.build_package.core import branch_menu
from gitrepo.build_package.core import branch_overview as overview_core
from gitrepo.build_package.core.repository_snapshot import RepositorySnapshot

from .git_fixtures import create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    # The assertions read the English labels; gettext consults LANGUAGE on every call.
    monkeypatch.setenv("LANGUAGE", "en")


def _commit(repository, filename, content="x\n"):
    (repository / filename).write_text(content, encoding="utf-8")
    run_git(repository, "add", filename)
    run_git(repository, "commit", "-m", f"add {filename}")


def _clone(tmp_path, remote, name="other"):
    other = tmp_path / name
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.name", "Other Test")
    run_git(other, "config", "user.email", "other@example.invalid")
    return other


def _by_name(overview):
    return {branch.name: branch for branch in overview.branches}


def test_fresh_clone_reports_everything_in_sync(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    run_git(repository, "push", "-u", "origin", "dev-me")
    monkeypatch.chdir(repository)

    overview = overview_core.capture_branch_overview()
    branches = _by_name(overview)

    assert overview.base == "main" and overview.base_ref == "main"
    # The base comes first, then the checked-out branch.
    assert [branch.name for branch in overview.branches] == ["main", "dev-me"]
    assert branches["dev-me"].is_current
    assert branches["dev-me"].local.sha == branches["main"].local.sha
    assert branches["dev-me"].vs_remote.state == overview_core.SAME
    assert branches["dev-me"].vs_base.state == overview_core.SAME
    assert branches["main"].vs_base is None
    assert overview.needs_attention == ()


def test_origin_advanced_elsewhere_shows_only_after_fetch(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    other = _clone(tmp_path, remote)
    _commit(other, "a.txt")
    _commit(other, "b.txt")
    run_git(other, "push", "origin", "main")
    monkeypatch.chdir(repository)

    before = _by_name(overview_core.capture_branch_overview())["main"]
    # Nothing touches the network until asked: origin/main is still the old tip.
    assert before.vs_remote.state == overview_core.SAME

    success, error = overview_core.fetch_origin()
    after_overview = overview_core.capture_branch_overview()
    after = _by_name(after_overview)["main"]

    assert success, error
    assert (after.vs_remote.ahead, after.vs_remote.behind) == (0, 2)
    assert overview_core.describe_vs_remote(after) == (overview_core.TONE_BEHIND, "↓2 to pull")
    assert after_overview.last_fetch is not None
    assert [branch.name for branch in after_overview.needs_attention] == ["main"]


def test_local_and_origin_diverged(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    other = _clone(tmp_path, remote)
    _commit(other, "theirs.txt")
    run_git(other, "push", "origin", "main")
    _commit(repository, "mine-1.txt")
    _commit(repository, "mine-2.txt")
    monkeypatch.chdir(repository)
    assert overview_core.fetch_origin()[0]

    main = _by_name(overview_core.capture_branch_overview())["main"]

    assert (main.vs_remote.ahead, main.vs_remote.behind) == (2, 1)
    assert overview_core.describe_vs_remote(main) == (overview_core.TONE_DIVERGED, "↑2 ↓1 diverged")


def test_work_branch_against_main_and_unpublished_commits(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    run_git(repository, "push", "-u", "origin", "dev-me")
    _commit(repository, "work.txt")
    run_git(repository, "checkout", "main")
    _commit(repository, "hotfix.txt")
    run_git(repository, "checkout", "dev-me")
    monkeypatch.chdir(repository)

    overview = overview_core.capture_branch_overview()
    dev = _by_name(overview)["dev-me"]

    assert overview_core.describe_vs_remote(dev) == (overview_core.TONE_AHEAD, "↑1 to push")
    assert overview_core.describe_vs_base(dev, overview) == (overview_core.TONE_DIVERGED, "↑1 ↓1 diverged from main")


def test_local_only_and_origin_only_branches(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    other = _clone(tmp_path, remote)
    run_git(other, "checkout", "-b", "dev-colleague")
    run_git(other, "push", "-u", "origin", "dev-colleague")
    run_git(repository, "branch", "dev-draft")
    _commit(repository, "main-moved.txt")
    monkeypatch.chdir(repository)
    assert overview_core.fetch_origin()[0]

    overview = overview_core.capture_branch_overview()
    branches = _by_name(overview)

    draft, colleague = branches["dev-draft"], branches["dev-colleague"]
    assert draft.remote is None and draft.vs_remote is None
    assert overview_core.describe_vs_remote(draft) == (overview_core.TONE_NEUTRAL, "Not on origin")
    assert overview_core.describe_vs_base(draft, overview) == (overview_core.TONE_BEHIND, "↓1 behind main")
    # A branch only on origin is still measured, from its origin tip.
    assert colleague.local is None
    assert overview_core.describe_vs_remote(colleague) == (overview_core.TONE_NEUTRAL, "Only on origin")
    assert colleague.vs_base.state == overview_core.BEHIND


def test_without_local_main_origin_main_is_the_base(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    run_git(repository, "branch", "-D", "main")
    monkeypatch.chdir(repository)

    overview = overview_core.capture_branch_overview()

    assert overview.base_ref == "origin/main"
    assert overview_core.describe_vs_base(_by_name(overview)["dev-me"], overview)[1] == "Same as origin/main"


def test_snapshot_carries_the_overview(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    snapshot = RepositorySnapshot.capture()

    assert [branch.name for branch in snapshot.branch_overview.branches] == ["main"]


def test_outside_a_repository_reports_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert overview_core.capture_branch_overview().error


def test_describe_age_is_coarse():
    now = 1_000_000.0
    assert overview_core.describe_age(None) == "never"
    assert overview_core.describe_age(now - 30, now) == "just now"
    assert overview_core.describe_age(now - 600, now) == "10 min ago"
    assert overview_core.describe_age(now - 7200, now) == "2 h ago"
    assert overview_core.describe_age(now - 3 * 86400, now) == "3 d ago"


class _Menu:
    def __init__(self, picks):
        self.picks = list(picks)
        self.contents = []

    def show_menu(self, title, options, default_index=0, additional_content=None):
        self.contents.append(additional_content)
        pick = self.picks.pop(0)
        return pick, options[pick]


class _Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


class _Bp:
    def __init__(self, menu):
        self.menu = menu
        self.logger = _Logger()
        self.is_git_repo = True


def test_cli_compare_flow_fetches_on_request_and_redraws(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    other = _clone(tmp_path, remote)
    _commit(other, "a.txt")
    run_git(other, "push", "origin", "main")
    monkeypatch.chdir(repository)
    # branch menu: Compare; compare: Update from origin, then Back; branch menu: Back.
    menu = _Menu([0, 0, 1, 5])
    bp = _Bp(menu)

    branch_menu.branch_menu(bp)

    from rich.console import Console

    def rendered(content):
        console = Console(width=160, record=True)
        console.print(content)
        return console.export_text()

    before, after = rendered(menu.contents[1]), rendered(menu.contents[2])
    assert "Same as origin" in before and "↓1 to pull" not in before
    assert "↓1 to pull" in after
    assert ("cyan", "Running git fetch --prune origin...") in bp.logger.messages


def test_failed_fetch_is_not_reported_as_fresh(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    assert overview_core.fetch_origin()[0]
    assert overview_core.describe_freshness(overview_core.capture_branch_overview()) == (
        overview_core.TONE_NEUTRAL,
        "origin as of the last git fetch: just now",
    )

    run_git(repository, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    success, error = overview_core.fetch_origin()
    overview = overview_core.capture_branch_overview()

    # Git still touches FETCH_HEAD on failure; its age must not read as fresh data.
    assert not success and error
    assert overview.last_fetch_failed
    tone, text = overview_core.describe_freshness(overview)
    assert tone == overview_core.TONE_DIVERGED and "failed" in text


def test_never_fetched_origin_is_flagged_as_stale(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    assert overview_core.describe_freshness(overview_core.capture_branch_overview()) == (
        overview_core.TONE_BEHIND,
        "origin as of the last git fetch: never",
    )
