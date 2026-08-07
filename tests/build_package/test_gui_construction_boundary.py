"""Constructing the application must not depend on process arguments."""

import ast
import importlib
import sys
from pathlib import Path

import pytest


CORE = Path(__file__).parents[2] / "usr/share/gitrepo/build_package/core/build_package.py"


@pytest.fixture
def build_package_module(build_package_modules):
    return importlib.import_module("gitrepo.build_package.core.build_package")


def test_construction_ignores_argv_so_desktop_activation_cannot_kill_the_gui(build_package_module, monkeypatch):
    # A .desktop launch can pass arguments this parser has never heard of.
    monkeypatch.setattr(sys, "argv", ["gitrepo", "--a-flag-the-gui-never-defined", "/some/file"])

    instance = build_package_module.BuildPackage()

    assert instance.args.organization
    assert instance.args.commit is None


def test_explicit_arguments_are_used_as_given(build_package_module):
    args = build_package_module.parse_arguments(["--commit", "feat: something", "--dry-run"])

    instance = build_package_module.BuildPackage(args=args)

    assert instance.args.commit == "feat: something"
    assert instance.dry_run_mode is True


def test_the_parser_answers_a_list_instead_of_reading_the_process(build_package_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gitrepo", "--commit", "from argv"])

    assert build_package_module.parse_arguments([]).commit is None
    assert build_package_module.parse_arguments(["-c", "explicit"]).commit == "explicit"


def test_no_module_in_the_construction_path_calls_sys_exit():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    exits = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sys"
    ]

    # Ending the process is the terminal entry point's decision, not a
    # side effect of building the object the GUI window owns.
    assert exits == []
