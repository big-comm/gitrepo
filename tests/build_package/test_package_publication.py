import subprocess
from pathlib import Path
from types import SimpleNamespace

from gitrepo.build_package.core import package_operations
from gitrepo.build_package.core.conflict_resolver import ConflictResolver
from gitrepo.build_package.core.git_utils import GitUtils


def run_git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def create_repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repository.mkdir()
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Package Test")
    run_git(repository, "config", "user.email", "package@example.invalid")
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    run_git(repository, "add", "base.txt")
    run_git(repository, "commit", "-m", "base")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")
    return repository, remote


def clone_main(remote: Path, destination: Path) -> Path:
    subprocess.run(
        ["git", "clone", "-b", "main", str(remote), str(destination)],
        check=True,
        capture_output=True,
    )
    run_git(destination, "config", "user.name", "Remote Package Test")
    run_git(destination, "config", "user.email", "remote-package@example.invalid")
    return destination


class Logger:
    def __init__(self):
        self.messages = []
        self.summaries = []

    def log(self, style, message):
        self.messages.append((style, message))

    def display_summary(self, title, data):
        self.summaries.append((title, data))


class Menu:
    def __init__(self, answer=True, choice=None):
        self.answer = answer
        self.choice = choice
        self.questions = []
        self.menus = []

    def confirm(self, question, default_yes=True):
        self.questions.append(question)
        assert default_yes is False
        return self.answer

    def show_menu(self, title, options, default_index=None):
        self.menus.append((title, options))
        if self.choice is None:
            return None
        return (self.choice, options[self.choice])


def build_package(menu=None):
    return SimpleNamespace(
        logger=Logger(),
        menu=menu or Menu(),
        dry_run_mode=False,
        github_user_name="tester",
    )


def test_repository_type_label_is_translated_only_for_display(monkeypatch):
    monkeypatch.setattr(package_operations, "_", lambda text: f"<{text}>")

    assert package_operations._branch_type_label("testing") == "<Testing>"
    assert package_operations._branch_type_label("stable") == "<Stable>"
    assert package_operations._branch_type_label("extra") == "<Extra>"
    assert package_operations._branch_type_label("custom") == "custom"


def test_stable_promotion_is_atomic_and_restores_source_branch(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repository, "add", "feature.txt")
    run_git(repository, "commit", "-m", "feature")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "main.txt").write_text("main update\n", encoding="utf-8")
    run_git(peer, "add", "main.txt")
    run_git(peer, "commit", "-m", "main update")
    run_git(peer, "push", "origin", "main")

    monkeypatch.chdir(repository)
    bp = build_package()
    assert package_operations._merge_to_main(bp, "dev-tester")

    remote_main = run_git(remote, "rev-parse", "refs/heads/main")
    remote_development = run_git(remote, "rev-parse", "refs/heads/dev-tester")
    assert remote_main == remote_development
    assert run_git(repository, "rev-parse", "refs/heads/main") == remote_main
    assert run_git(repository, "branch", "--show-current") == "dev-tester"
    assert (repository / "feature.txt").is_file()
    assert (repository / "main.txt").is_file()
    assert "--atomic" in bp.menu.questions[0]


def test_stable_promotion_preserves_local_only_main_without_publishing_it(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repository, "add", "feature.txt")
    run_git(repository, "commit", "-m", "feature")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    run_git(repository, "checkout", "main")
    (repository / "local-main.txt").write_text("unpublished\n", encoding="utf-8")
    run_git(repository, "add", "local-main.txt")
    run_git(repository, "commit", "-m", "local-only main")
    local_main = run_git(repository, "rev-parse", "HEAD")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "remote-main.txt").write_text("remote\n", encoding="utf-8")
    run_git(peer, "add", "remote-main.txt")
    run_git(peer, "commit", "-m", "remote main")
    run_git(peer, "push", "origin", "main")
    run_git(repository, "checkout", "dev-tester")

    monkeypatch.chdir(repository)
    bp = build_package()
    assert package_operations._merge_to_main(bp, "dev-tester")

    backups = run_git(
        repository,
        "branch",
        "--format=%(refname:short)",
        "--list",
        "backup/main-before-stable-*",
    ).splitlines()
    assert len(backups) == 1
    assert run_git(repository, "rev-parse", backups[0]) == local_main
    assert "local-main.txt" not in run_git(remote, "ls-tree", "-r", "--name-only", "refs/heads/main").splitlines()
    assert run_git(remote, "rev-parse", "refs/heads/main") == run_git(remote, "rev-parse", "refs/heads/dev-tester")
    assert any(backups[0] in message for _style, message in bp.logger.messages)


def test_stable_promotion_retries_an_atomic_remote_race(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repository, "add", "feature.txt")
    run_git(repository, "commit", "-m", "feature")
    run_git(repository, "push", "-u", "origin", "dev-tester")
    peer = clone_main(remote, tmp_path / "peer")

    original_run = package_operations.subprocess._subprocess.run
    race_injected = False
    promotion = [
        "git",
        "push",
        "--atomic",
        "origin",
        "refs/heads/dev-tester:refs/heads/dev-tester",
        "refs/heads/dev-tester:refs/heads/main",
    ]

    def run_with_remote_race(command, *args, **kwargs):
        nonlocal race_injected
        if command == promotion and not race_injected:
            race_injected = True
            (peer / "race.txt").write_text("remote race\n", encoding="utf-8")
            original_run(["git", "add", "race.txt"], cwd=peer, check=True, capture_output=True)
            original_run(
                ["git", "commit", "-m", "concurrent main update"],
                cwd=peer,
                check=True,
                capture_output=True,
            )
            original_run(["git", "push", "origin", "main"], cwd=peer, check=True, capture_output=True)
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(package_operations.subprocess._subprocess, "run", run_with_remote_race)
    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    bp = build_package()
    assert package_operations._merge_to_main(bp, "dev-tester")

    assert race_injected
    assert (repository / "race.txt").read_text(encoding="utf-8") == "remote race\n"
    assert run_git(remote, "rev-parse", "refs/heads/main") == run_git(remote, "rev-parse", "refs/heads/dev-tester")
    assert any("retry" in message.lower() for _style, message in bp.logger.messages)


def create_conflicting_promotion(tmp_path: Path) -> tuple[Path, Path]:
    """Leave dev-tester and origin/main editing the same line."""
    repository, remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "base.txt").write_text("local line\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "local edit")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "base.txt").write_text("remote line\n", encoding="utf-8")
    run_git(peer, "commit", "-am", "remote edit")
    run_git(peer, "push", "origin", "main")
    return repository, remote


def test_stable_conflict_offers_resolution_instead_of_only_reporting_it(tmp_path, monkeypatch):
    repository, remote = create_conflicting_promotion(tmp_path)

    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    bp = build_package()
    bp.conflict_resolver = ConflictResolver(bp.logger, bp.menu)

    assert package_operations._merge_to_main(bp, "dev-tester")

    questions = "\n".join(bp.menu.questions)
    assert "base.txt" in questions
    assert (repository / "base.txt").read_text(encoding="utf-8") == "local line\n"
    assert run_git(remote, "rev-parse", "refs/heads/main") == run_git(remote, "rev-parse", "refs/heads/dev-tester")
    assert run_git(repository, "branch", "--show-current") == "dev-tester"


def test_stable_conflict_reports_the_files_and_the_manual_commands(tmp_path, monkeypatch):
    repository, remote = create_conflicting_promotion(tmp_path)
    head_before = run_git(repository, "rev-parse", "HEAD")
    remote_main_before = run_git(remote, "rev-parse", "refs/heads/main")

    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    bp = build_package()

    assert package_operations._merge_to_main(bp, "dev-tester") is False

    message = "\n".join(message for _style, message in bp.logger.messages)
    assert "base.txt" in message
    assert "git checkout --ours -- base.txt" in message
    assert "git checkout --theirs -- base.txt" in message
    assert run_git(repository, "rev-parse", "HEAD") == head_before
    assert run_git(remote, "rev-parse", "refs/heads/main") == remote_main_before
    assert run_git(repository, "status", "--short") == ""
    assert run_git(repository, "branch", "--show-current") == "dev-tester"


def test_translation_catalog_conflicts_are_decided_once(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    for name in ("locale/app.pot", "locale/en.po"):
        path = repository / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('msgid "base"\n', encoding="utf-8")
    run_git(repository, "add", "locale")
    run_git(repository, "commit", "-m", "catalogs")
    run_git(repository, "push", "origin", "main")

    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "locale/app.pot").write_text('msgid "local"\n', encoding="utf-8")
    (repository / "locale/en.po").write_text('msgid "local"\n', encoding="utf-8")
    run_git(repository, "commit", "-am", "local catalogs")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "locale/app.pot").write_text('msgid "translated"\n', encoding="utf-8")
    (peer / "locale/en.po").write_text('msgid "translated"\n', encoding="utf-8")
    run_git(peer, "commit", "-am", "translate 26-08-06_15:00")
    run_git(peer, "push", "origin", "main")

    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    # Option 0 keeps the local catalogs for every conflicted file at once.
    bp = build_package(menu=Menu(choice=0))
    bp.conflict_resolver = ConflictResolver(bp.logger, bp.menu)

    assert package_operations._merge_to_main(bp, "dev-tester")

    assert len(bp.menu.menus) == 1
    title, options = bp.menu.menus[0]
    assert "locale/app.pot" in title and "locale/en.po" in title
    assert len(options) == 3
    assert (repository / "locale/en.po").read_text(encoding="utf-8") == 'msgid "local"\n'
    assert run_git(remote, "rev-parse", "refs/heads/main") == run_git(remote, "rev-parse", "refs/heads/dev-tester")


def test_translation_catalog_conflicts_can_take_the_remote_version(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    (repository / "locale").mkdir()
    (repository / "locale/en.po").write_text('msgid "base"\n', encoding="utf-8")
    run_git(repository, "add", "locale")
    run_git(repository, "commit", "-m", "catalog")
    run_git(repository, "push", "origin", "main")

    run_git(repository, "checkout", "-b", "dev-tester")
    (repository / "locale/en.po").write_text('msgid "local"\n', encoding="utf-8")
    run_git(repository, "commit", "-am", "local catalog")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "locale/en.po").write_text('msgid "translated"\n', encoding="utf-8")
    run_git(peer, "commit", "-am", "translate 26-08-06_15:00")
    run_git(peer, "push", "origin", "main")

    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    bp = build_package(menu=Menu(choice=1))
    bp.conflict_resolver = ConflictResolver(bp.logger, bp.menu)

    assert package_operations._merge_to_main(bp, "dev-tester")
    assert (repository / "locale/en.po").read_text(encoding="utf-8") == 'msgid "translated"\n'


def test_source_conflicts_are_never_grouped_as_translations(tmp_path, monkeypatch):
    repository, _remote = create_conflicting_promotion(tmp_path)

    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.chdir(repository)
    bp = build_package(menu=Menu(choice=0))
    bp.conflict_resolver = ConflictResolver(bp.logger, bp.menu)

    assert package_operations._merge_to_main(bp, "dev-tester")

    assert bp.menu.menus == []


def test_alignment_failure_reports_that_remote_promotion_already_succeeded(monkeypatch):
    monkeypatch.setattr(package_operations, "_", lambda message: message)
    monkeypatch.setattr(GitUtils, "has_changes", staticmethod(lambda: False))
    monkeypatch.setattr(GitUtils, "ref_exists", staticmethod(lambda _ref: True))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: "dev-tester"))
    monkeypatch.setattr(
        package_operations.subprocess,
        "run_git",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(package_operations, "_create_main_backup_if_needed", lambda _bp: "")
    monkeypatch.setattr(package_operations, "_sync_source_and_promote_main", lambda _bp, _branch: True)

    def fail_alignment():
        raise subprocess.CalledProcessError(1, ["git", "branch"], stderr="alignment failed")

    monkeypatch.setattr(package_operations, "_align_local_main", fail_alignment)
    bp = build_package()

    assert package_operations._merge_to_main(bp, "dev-tester") is False
    message = "\n".join(message for _style, message in bp.logger.messages)
    assert "dev-tester" in message
    assert "main" in message
    assert "published" in message
    assert "alignment failed" in message


def test_stable_from_main_publishes_local_commits_before_dispatch(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    (repository / "release.txt").write_text("release\n", encoding="utf-8")
    run_git(repository, "add", "release.txt")
    run_git(repository, "commit", "-m", "local release")
    local_head = run_git(repository, "rev-parse", "HEAD")
    dispatches = []

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(package, branch_type, branch, aur, tmate, logger):
            remote_head = run_git(remote, "rev-parse", "refs/heads/main")
            dispatches.append((package, branch_type, branch, aur, tmate, logger, remote_head))
            return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)
    assert package_operations.commit_and_generate_package(bp, "stable")

    assert dispatches[0][1:3] == ("stable", "")
    assert dispatches[0][-1] == local_head
    assert len(bp.menu.questions) == 2
    assert "--atomic" not in bp.menu.questions[0]
    assert "refs/heads/main:refs/heads/main" in bp.menu.questions[0]


def test_stable_uses_package_name_after_main_sync(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    (repository / "PKGBUILD").write_text("pkgname=old-demo\n", encoding="utf-8")
    run_git(repository, "add", "PKGBUILD")
    run_git(repository, "commit", "-m", "old package name")
    run_git(repository, "push", "origin", "main")
    run_git(repository, "checkout", "-b", "dev-tester")
    run_git(repository, "push", "-u", "origin", "dev-tester")

    peer = clone_main(remote, tmp_path / "peer")
    (peer / "PKGBUILD").write_text("pkgname=new-demo\n", encoding="utf-8")
    run_git(peer, "commit", "-am", "new package name")
    run_git(peer, "push", "origin", "main")
    package_names = []
    dispatches = []

    def read_package_name():
        package_name = (repository / "PKGBUILD").read_text(encoding="utf-8").split("=", 1)[1].strip()
        package_names.append(package_name)
        return package_name

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(package, branch_type, branch, aur, tmate, logger):
            dispatches.append((package, branch_type, branch, aur, tmate, logger))
            return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(read_package_name))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "stable")

    assert package_names == ["old-demo", "new-demo"]
    assert dispatches[0][:3] == ("new-demo", "stable", "")
    assert (repository / "PKGBUILD").read_text(encoding="utf-8") == "pkgname=new-demo\n"


def test_testing_publishes_selected_personal_branch_before_dispatch(tmp_path, monkeypatch):
    repository, remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-selected")
    (repository / "testing.txt").write_text("testing\n", encoding="utf-8")
    run_git(repository, "add", "testing.txt")
    run_git(repository, "commit", "-m", "testing")
    selected_head = run_git(repository, "rev-parse", "HEAD")
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-selected")

    dispatches = []

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(package, branch_type, branch, aur, tmate, logger):
            remote_head = run_git(remote, "rev-parse", "refs/heads/dev-selected")
            dispatches.append((package, branch_type, branch, aur, tmate, logger, remote_head))
            return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing")

    assert dispatches[0][1:3] == ("testing", "dev-selected")
    assert dispatches[0][-1] == selected_head
    assert len(bp.menu.questions) == 2
    assert "git push -u origin refs/heads/dev-selected:refs/heads/dev-selected" in bp.menu.questions[0]


def test_testing_branch_mismatch_stops_before_commit_or_dispatch(tmp_path, monkeypatch):
    repository, _remote = create_repository(tmp_path)
    run_git(repository, "branch", "dev-selected")
    run_git(repository, "checkout", "-b", "feature-work")
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-selected")
    (repository / "pending.txt").write_text("must stay pending\n", encoding="utf-8")
    head_before = run_git(repository, "rev-parse", "HEAD")
    commit_calls = []

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(*_args):
            raise AssertionError("a mismatched branch must not be dispatched")

    def commit_and_push(_bp):
        commit_calls.append(True)
        return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(package_operations, "commit_and_push", commit_and_push)
    monkeypatch.setattr(
        GitUtils,
        "get_package_name",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("package lookup must happen after preflight"))),
    )
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing", "feat: pending") is False

    assert commit_calls == []
    assert run_git(repository, "rev-parse", "HEAD") == head_before
    assert run_git(repository, "status", "--short") == "?? pending.txt"
    message = "\n".join(message for _style, message in bp.logger.messages)
    assert "dev-selected" in message
    assert "feature-work" in message
    assert not bp.menu.questions


def test_testing_revalidates_the_selected_branch_after_commit_step(tmp_path, monkeypatch):
    repository, _remote = create_repository(tmp_path)
    run_git(repository, "checkout", "-b", "dev-selected")
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-selected")
    commit_calls = []

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(*_args):
            raise AssertionError("a changed target must not be dispatched")

    def change_target_during_commit(_bp, _message):
        commit_calls.append(True)
        run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-other")
        return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(package_operations, "_commit_pending_changes", change_target_during_commit)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing") is False

    assert commit_calls == [True]
    assert not bp.menu.questions
    message = "\n".join(message for _style, message in bp.logger.messages)
    assert "dev-selected" in message
    assert "dev-other" in message


def test_testing_refuses_to_dispatch_a_missing_personal_branch(tmp_path, monkeypatch):
    """Declining to create the branch must leave the dispatch unsent."""
    repository, _remote = create_repository(tmp_path)
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-missing")

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(*_args):
            raise AssertionError("a missing branch must not be dispatched")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package(Menu(answer=False))
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing") is False
    # The offer is made, and refusing it changes nothing in the repository.
    assert any("dev-missing" in str(question) for question in bp.menu.questions)
    assert GitUtils.get_current_branch() == "main"
    assert not GitUtils.ref_exists("refs/heads/dev-missing")
    assert any("dev-missing" in message for _style, message in bp.logger.messages)


def test_testing_offers_to_create_the_missing_personal_branch(tmp_path, monkeypatch):
    """A branch that was never created is not something switching can fix."""
    repository, remote = create_repository(tmp_path)
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-fresh")
    dispatched = []

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(*args):
            dispatched.append(args)
            return True

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing") is True

    # Created, checked out, and published: the workflow resolves the build from
    # origin by branch name, so an unpushed branch would build nothing.
    assert GitUtils.get_current_branch() == "dev-fresh"
    assert GitUtils.ref_exists("refs/heads/dev-fresh")
    assert run_git(remote, "rev-parse", "refs/heads/dev-fresh").strip()
    assert dispatched


def test_testing_does_not_offer_to_create_an_existing_branch(tmp_path, monkeypatch):
    """An existing branch is a branch to switch to, not one to create."""
    repository, _remote = create_repository(tmp_path)
    run_git(repository, "branch", "dev-existing")
    run_git(repository, "config", "--local", "gitrepo.personalBranch", "dev-existing")

    class GitHubAPI:
        @staticmethod
        def ensure_github_token(_logger):
            return True

        @staticmethod
        def trigger_workflow(*_args):
            raise AssertionError("the inactive branch must not be dispatched")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda: "demo"))
    bp = build_package()
    bp.is_git_repo = True
    bp.github_api = GitHubAPI()
    bp.organization = "example"
    bp.args = SimpleNamespace(commit=None)

    assert package_operations.commit_and_generate_package(bp, "testing") is False
    assert not bp.menu.questions
    assert GitUtils.get_current_branch() == "main"
