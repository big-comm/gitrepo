"""Regressions for the package-generator fixes ported from upstream."""

from pathlib import Path
from types import SimpleNamespace

from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.build_package.core.github_api import GitHubAPI
from gitrepo.build_package.core.version_bumper import _locate_app_version_entry


_OWNER_KEY = "APP_VERSION_" + "OWNER"


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


def _dispatch(branch_type, new_branch, monkeypatch, current_branch="dev-tester"):
    monkeypatch.setattr(GitUtils, "get_repo_name", staticmethod(lambda: "big-comm/gitrepo"))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: current_branch))
    return GitHubAPI._package_workflow_dispatch("gitrepo", branch_type, new_branch, False, Logger())


def test_stable_and_extra_packages_always_build_from_main(monkeypatch):
    for branch_type in ("stable", "extra"):
        _event, data = _dispatch(branch_type, "", monkeypatch)
        payload = data["client_payload"]

        assert payload["branch"] == "main"
        assert "new_branch" not in payload


def test_testing_packages_keep_the_selected_development_branch(monkeypatch):
    _event, data = _dispatch("testing", "dev-tester", monkeypatch)
    payload = data["client_payload"]

    assert payload["branch"] == "dev-tester"
    assert payload["new_branch"] == "dev-tester"


def test_package_source_allows_workflow_branch_selection():
    pkgbuild = Path("pkgbuild/PKGBUILD").read_text(encoding="utf-8")

    assert "#branch=main" in pkgbuild
    assert "#commit=" not in pkgbuild


def _bumper(tmp_path, cache=None):
    return SimpleNamespace(
        repo_path=str(tmp_path),
        _app_version_cache=cache,
        _app_version_warning_shown=False,
        logger=Logger(),
    )


def test_version_bump_targets_the_application_named_after_the_repository(tmp_path):
    (tmp_path / "PKGBUILD").write_text("pkgname=build-package\n", encoding="utf-8")
    (tmp_path / "a_iso.py").write_text('APP_VERSION = "3.7.8"\nAPP_NAME = _("BUILD ISO")\n', encoding="utf-8")
    (tmp_path / "b_pkg.py").write_text('APP_VERSION = "3.1.5"\nAPP_NAME = _("Build Package")\n', encoding="utf-8")

    file_path, _content, match = _locate_app_version_entry(_bumper(tmp_path))

    assert file_path.endswith("b_pkg.py")
    assert match.group(3) == "3.1.5"


def test_version_bump_refuses_to_guess_between_two_applications(tmp_path):
    (tmp_path / "PKGBUILD").write_text("pkgname=gitrepo\n", encoding="utf-8")
    (tmp_path / "a_iso.py").write_text('APP_VERSION = "3.7.8"\nAPP_NAME = _("BUILD ISO")\n', encoding="utf-8")
    (tmp_path / "b_pkg.py").write_text('APP_VERSION = "3.1.5"\nAPP_NAME = _("BUILD PACKAGE")\n', encoding="utf-8")

    assert _locate_app_version_entry(_bumper(tmp_path)) == (None, None, None)


def test_version_bump_prefers_explicit_repository_owner(tmp_path):
    (tmp_path / "PKGBUILD").write_text("pkgname=gitrepo\n", encoding="utf-8")
    (tmp_path / "a_iso.py").write_text(
        'APP_VERSION = "3.8.1"\nAPP_NAME = _("BUILD ISO")\n',
        encoding="utf-8",
    )
    package = tmp_path / "b_package.py"
    package.write_text(
        f'{_OWNER_KEY} = "gitrepo"\nAPP_VERSION = "4.0.0"\nAPP_NAME = _("BUILD PACKAGE")\n',
        encoding="utf-8",
    )

    file_path, _content, match = _locate_app_version_entry(_bumper(tmp_path))

    assert file_path == str(package)
    assert match.group(3) == "4.0.0"


def test_version_bump_refuses_duplicate_explicit_owners(tmp_path):
    (tmp_path / "PKGBUILD").write_text("pkgname=gitrepo\n", encoding="utf-8")
    for name in ("first.py", "second.py"):
        (tmp_path / name).write_text(
            f'{_OWNER_KEY} = "gitrepo"\nAPP_VERSION = "4.0.0"\n',
            encoding="utf-8",
        )

    assert _locate_app_version_entry(_bumper(tmp_path)) == (None, None, None)


def test_changed_files_keep_paths_with_spaces_and_skip_rename_sources(monkeypatch):
    record = b"R  new name.txt\x00old name.txt\x00 M plain.py\x00?? untracked file.md\x00"
    monkeypatch.setattr(
        "gitrepo.build_package.core.git_utils.subprocess.run_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=record),
    )

    assert GitUtils.get_changed_files() == [
        ("R", "new name.txt"),
        ("M", "plain.py"),
        ("??", "untracked file.md"),
    ]


def test_revision_changes_pair_status_and_path(monkeypatch):
    monkeypatch.setattr(
        "gitrepo.build_package.core.git_utils.subprocess.run_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"M\x00usr/app.py\x00A\x00docs/new file.md\x00"),
    )

    assert GitUtils.get_revision_changes("abc", "def") == [("M", "usr/app.py"), ("A", "docs/new file.md")]


def test_revision_changes_are_empty_without_movement(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("git must not run when the revisions match")

    monkeypatch.setattr("gitrepo.build_package.core.git_utils.subprocess.run_git", fail)

    assert GitUtils.get_revision_changes("abc", "abc") == []
    assert GitUtils.get_revision_changes("", "def") == []
