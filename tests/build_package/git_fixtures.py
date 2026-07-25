"""Real Git repositories for the safety tests that need observable state."""

import subprocess
from pathlib import Path


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


class AlwaysConfirm:
    def confirm(self, question, default_yes=True):
        return True
