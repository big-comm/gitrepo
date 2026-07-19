import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def create_repository_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repository.mkdir()
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Safety Test")
    run_git(repository, "config", "user.email", "safety@example.invalid")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(repository, "add", "tracked.txt")
    run_git(repository, "commit", "-m", "base")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")
    return repository, remote


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def die(self, style, message):
        self.log(style, message)


def test_conflicting_merge_never_rewrites_main(build_package_modules, tmp_path, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    package_operations = importlib.import_module("gitrepo.build_package.core.package_operations")
    repository, _ = create_repository_with_remote(tmp_path)

    run_git(repository, "checkout", "-b", "dev-safety")
    (repository / "tracked.txt").write_text("development\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "development")
    run_git(repository, "checkout", "main")
    (repository / "tracked.txt").write_text("main\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "main")
    run_git(repository, "push", "origin", "main")
    main_before = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert default_yes is False
            return True

    bp = SimpleNamespace(logger=Logger(), menu=Menu())

    assert package_operations._merge_to_main(bp, "dev-safety") is False
    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == main_before
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "main\n"
    assert not (repository / ".git" / "MERGE_HEAD").exists()


def test_branch_cleanup_cancel_preserves_every_candidate(build_package_modules, tmp_path, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    repository, _ = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "dev-25.01.01-0000")
    run_git(repository, "branch", "dev-26.01.01-0000")
    run_git(repository, "push", "origin", "dev-25.01.01-0000", "dev-26.01.01-0000")
    monkeypatch.chdir(repository)

    class Menu:
        def __init__(self):
            self.question = ""

        def confirm(self, question, default_yes=True):
            self.question = question
            assert default_yes is False
            return False

    menu = Menu()
    assert git_utils.GitUtils.cleanup_old_branches(Logger(), menu) is False
    assert "dev-25.01.01-0000" in menu.question
    local_branches = run_git(repository, "branch", "--format=%(refname:short)").stdout.splitlines()
    remote_branches = run_git(repository, "branch", "-r", "--format=%(refname:short)").stdout.splitlines()
    assert "dev-25.01.01-0000" in local_branches
    assert "origin/dev-25.01.01-0000" in remote_branches


def test_actions_cleanup_cancel_never_calls_delete(build_package_modules, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    github_api = importlib.import_module("gitrepo.build_package.core.github_api")

    class Response:
        status_code = 200

        def json(self):
            return {"workflow_runs": [{"id": 42, "display_title": "Release"}]}

    monkeypatch.setattr(github_api.GitUtils, "get_repo_name", lambda: "owner/repo")
    monkeypatch.setattr(github_api.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        github_api.requests,
        "delete",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("delete must not run after cancellation")),
    )

    class Menu:
        def confirm(self, question, default_yes=True):
            assert "42: Release" in question
            assert default_yes is False
            return False

    api = github_api.GitHubAPI("token", "owner")
    assert api.clean_action_jobs("success", Logger(), Menu()) is False


def test_tag_cleanup_encodes_the_confirmed_tag_name(build_package_modules, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    github_api = importlib.import_module("gitrepo.build_package.core.github_api")
    deleted_urls = []

    class Response:
        status_code = 200

        def json(self):
            return [{"name": "release/candidate"}]

    class Deleted:
        status_code = 204

    monkeypatch.setattr(github_api.GitUtils, "get_repo_name", lambda: "owner/repo")
    monkeypatch.setattr(github_api.requests, "get", lambda *args, **kwargs: Response())

    def delete(url, **kwargs):
        deleted_urls.append(url)
        return Deleted()

    monkeypatch.setattr(github_api.requests, "delete", delete)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert "release/candidate" in question
            assert default_yes is False
            return True

    api = github_api.GitHubAPI("token", "owner")
    assert api.clean_all_tags(Logger(), Menu()) is True
    assert deleted_urls == ["https://api.github.com/repos/owner/repo/git/refs/tags/release%2Fcandidate"]


def test_workflow_dispatch_uses_reviewed_branch_without_git_mutation(build_package_modules, monkeypatch):
    github_api = importlib.import_module("gitrepo.build_package.core.github_api")
    posted = []

    class Response:
        status_code = 204

    monkeypatch.setattr(github_api.GitUtils, "get_repo_name", lambda: "owner/repo")
    monkeypatch.setattr(github_api.GitUtils, "get_current_branch", lambda: "ignored-current")

    def post(url, **kwargs):
        posted.append((url, kwargs["json"]))
        return Response()

    monkeypatch.setattr(github_api.requests, "post", post)
    api = github_api.GitHubAPI("token", "owner")

    assert api.trigger_workflow("demo", "testing", "dev-reviewed", False, False, Logger()) is True
    assert posted[0][1]["client_payload"]["branch"] == "dev-reviewed"
    assert posted[0][1]["client_payload"]["new_branch"] == "dev-reviewed"


def _commit_flow_bp(commit_message, menu):
    class Settings:
        def get(self, key, default=None):
            return False if key == "auto_version_bump" else default

    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu,
        settings=Settings(),
        args=SimpleNamespace(commit_file=None, commit=commit_message),
        conflict_resolver=SimpleNamespace(has_conflicts=lambda: False),
        github_user_name="safety",
        dry_run_mode=False,
    )


def test_commit_preview_cancel_preserves_working_tree(build_package_modules, tmp_path, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    commit_operations = importlib.import_module("gitrepo.build_package.core.commit_operations")
    repository, _ = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("cancelled\n", encoding="utf-8")
    head_before = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert "tracked.txt" in question
            assert "Branch: main" in question
            assert default_yes is False
            return False

    assert commit_operations.commit_and_push(_commit_flow_bp("cancel me", Menu())) is False
    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == head_before
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "cancelled\n"


def test_initial_commit_cancel_does_not_create_branch(build_package_modules, tmp_path, monkeypatch):
    commit_operations = importlib.import_module("gitrepo.build_package.core.commit_operations")
    repository = tmp_path / "unborn"
    repository.mkdir()
    run_git(repository, "init")
    (repository / "first.txt").write_text("not committed\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert "Branch: dev-safety" in question
            assert default_yes is False
            return False

    assert commit_operations.commit_and_push(_commit_flow_bp("first commit", Menu())) is False
    assert run_git(repository, "branch", "--format=%(refname:short)").stdout == ""
    assert (repository / "first.txt").read_text(encoding="utf-8") == "not committed\n"


def test_confirmed_commit_pushes_exact_branch(build_package_modules, tmp_path, monkeypatch):
    importlib.import_module("gitrepo.build_package.core.settings")
    commit_operations = importlib.import_module("gitrepo.build_package.core.commit_operations")
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("confirmed\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert default_yes is False
            return True

    assert commit_operations.commit_and_push(_commit_flow_bp("confirmed commit", Menu())) is True
    assert run_git(repository, "log", "-1", "--format=%s").stdout.strip() == "confirmed commit"
    remote_head = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_head == run_git(repository, "rev-parse", "HEAD").stdout.strip()


def _pull_flow_bp(menu):
    resolver = SimpleNamespace(has_conflicts=lambda: False, resolve=lambda *args: False)
    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu,
        conflict_resolver=resolver,
        dry_run_mode=False,
    )


def test_pull_cancel_preserves_head_and_local_changes(build_package_modules, tmp_path, monkeypatch):
    pull_operations = importlib.import_module("gitrepo.build_package.core.pull_operations")
    repository, _ = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("keep me\n", encoding="utf-8")
    head_before = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            assert "git stash push" in "\n".join(message for _, message in bp.logger.messages)
            return False

    bp = _pull_flow_bp(Menu())
    assert pull_operations.pull_latest(bp) is False
    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == head_before
    assert (repository / "local.txt").read_text(encoding="utf-8") == "keep me\n"


def test_pull_updates_branch_and_restores_untracked_file(build_package_modules, tmp_path, monkeypatch):
    pull_operations = importlib.import_module("gitrepo.build_package.core.pull_operations")
    repository, remote = create_repository_with_remote(tmp_path)
    publisher = tmp_path / "publisher"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(publisher)], check=True, capture_output=True)
    run_git(publisher, "config", "user.name", "Publisher")
    run_git(publisher, "config", "user.email", "publisher@example.invalid")
    (publisher / "remote.txt").write_text("from remote\n", encoding="utf-8")
    run_git(publisher, "add", "remote.txt")
    run_git(publisher, "commit", "-m", "remote update")
    run_git(publisher, "push", "origin", "main")
    (repository / "local.txt").write_text("keep me\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            return True

    assert pull_operations.pull_latest(_pull_flow_bp(Menu())) is True
    assert (repository / "remote.txt").read_text(encoding="utf-8") == "from remote\n"
    assert (repository / "local.txt").read_text(encoding="utf-8") == "keep me\n"
    assert run_git(repository, "stash", "list").stdout.strip() == ""
