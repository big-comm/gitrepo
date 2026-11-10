"""One window, many repositories: launching GitRepo again moves the open window."""

import importlib
import os
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(build_package_modules, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    return SimpleNamespace(
        switch=importlib.import_module("gitrepo.build_package.core.repository_switch"),
        build=importlib.import_module("gitrepo.build_package.core.build_package"),
    )


def _repository(tmp_path, origin):
    path = tmp_path / origin.split("/")[1]
    (path / "sub" / "dir").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", f"https://github.com/{origin}.git"], check=True)
    return os.path.realpath(path)


def test_the_root_of_a_launch_directory_is_its_working_tree(modules, tmp_path):
    root = _repository(tmp_path, "big-comm/repo-a")
    assert modules.switch.repository_root(os.path.join(root, "sub", "dir")) == root
    outside = tmp_path / "outside"
    outside.mkdir()
    assert modules.switch.repository_root(str(outside)) == ""
    assert modules.switch.repository_root(str(tmp_path / "missing")) == ""


def test_the_window_moves_only_to_another_idle_repository(modules, tmp_path):
    switch = modules.switch
    a = _repository(tmp_path, "big-comm/repo-a")
    b = _repository(tmp_path, "biglinux/repo-b")
    assert switch.switch_decision(a, b, busy=False) == switch.SWITCH
    assert switch.switch_decision(a, a, busy=False) == switch.SAME
    assert switch.switch_decision(a, "", busy=False) == switch.STAY
    assert switch.switch_decision(a, b, busy=True) == switch.BUSY
    # A window opened outside any repository can always move into one.
    assert switch.switch_decision("", b, busy=False) == switch.SWITCH


def test_reloading_follows_the_new_repository(modules, tmp_path, monkeypatch):
    a = _repository(tmp_path, "big-comm/repo-a")
    b = _repository(tmp_path, "biglinux/repo-b")
    monkeypatch.chdir(a)
    instance = modules.build.BuildPackage()
    assert (instance.organization, instance.repo_name) == ("big-comm", "big-comm/repo-a")
    instance.last_operation_details = {"remote_unchanged": True}

    monkeypatch.chdir(b)
    instance.reload_repository()

    assert instance.organization == "biglinux" and instance.repo_workflow == "biglinux/build-package"
    assert instance.repo_name == "biglinux/repo-b" and os.path.realpath(instance.repo_path) == b
    assert instance.last_operation_details == {}


def test_an_organization_from_the_command_line_survives_the_move(modules, tmp_path, monkeypatch):
    a = _repository(tmp_path, "big-comm/repo-a")
    b = _repository(tmp_path, "biglinux/repo-b")
    monkeypatch.chdir(a)
    instance = modules.build.BuildPackage(args=modules.build.parse_arguments(["--organization", "big-comm"]))

    monkeypatch.chdir(b)
    instance.reload_repository()

    assert instance.organization == "big-comm"
