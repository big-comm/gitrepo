import importlib
import subprocess
from pathlib import Path


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True, text=True)


def create_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Snapshot Test")
    run_git(repository, "config", "user.email", "snapshot@example.invalid")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(repository, "add", "tracked.txt")
    run_git(repository, "commit", "-m", "base")
    return repository


def test_snapshot_distinguishes_detached_head(build_package_modules, tmp_path, monkeypatch):
    snapshots = importlib.import_module("gitrepo.build_package.core.repository_snapshot")
    repository = create_repository(tmp_path)
    run_git(repository, "checkout", "--detach")
    monkeypatch.chdir(repository)

    snapshot = snapshots.RepositorySnapshot.capture()

    assert snapshot.is_repository is True
    assert snapshot.is_detached is True
    assert snapshot.branch == run_git(repository, "rev-parse", "--short", "HEAD").stdout.strip()
    assert snapshot.has_changes is False


def test_snapshot_does_not_report_clean_when_status_fails(build_package_modules, tmp_path, monkeypatch):
    snapshots = importlib.import_module("gitrepo.build_package.core.repository_snapshot")
    repository = create_repository(tmp_path)
    monkeypatch.chdir(repository)
    original_run_bytes = snapshots._run_bytes

    def fail_status(command):
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 128, b"", b"status unavailable")
        return original_run_bytes(command)

    monkeypatch.setattr(snapshots, "_run_bytes", fail_status)
    snapshot = snapshots.RepositorySnapshot.capture()

    assert snapshot.is_repository is True
    assert snapshot.has_changes is None
    assert snapshot.status_error == "status unavailable"


def test_package_name_uses_makepkg_metadata(build_package_modules, tmp_path, monkeypatch):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    (tmp_path / "PKGBUILD").write_text("pkgname=(ignored-by-design)\n", encoding="utf-8")
    command = []

    monkeypatch.setattr(git_utils.GitUtils, "get_repo_root_path", lambda: str(tmp_path))
    monkeypatch.setattr(git_utils.shutil, "which", lambda executable: f"/usr/bin/{executable}")
    monkeypatch.setattr(
        git_utils.subprocess,
        "run",
        lambda argv, **kwargs: (
            command.append((argv, kwargs))
            or subprocess.CompletedProcess(argv, 0, "pkgbase = example\n\tpkgname = example-cli\n", "")
        ),
    )

    assert git_utils.GitUtils.get_package_name() == "example-cli"
    assert command[0][0] == ["makepkg", "--printsrcinfo"]
    assert command[0][1]["cwd"] == str(tmp_path)
