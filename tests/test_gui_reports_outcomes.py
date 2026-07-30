"""Widgets must report what happened instead of showing a stale success."""

import ast
import sys
from pathlib import Path


SHARE = Path(__file__).resolve().parents[1] / "usr" / "share"
sys.path.insert(0, str(SHARE))

BUILD_ISO = SHARE / "gitrepo" / "build_iso" / "gui" / "widgets"
BUILD_PACKAGE = SHARE / "gitrepo" / "build_package" / "gui" / "widgets"


def _source(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def _function(path: Path, name: str) -> str:
    tree = ast.parse(_source(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name} not found in {path.name}")


def test_the_build_button_keeps_its_content_widget():
    # Gtk.Button.set_label replaces the child, detaching build_button_content;
    # the button then froze on that text and stopped naming the target repo.
    body = _function(BUILD_PACKAGE / "package_widget.py", "on_reset_clicked")

    assert "build_button_content.set_label" in body
    assert "build_button.set_label" not in body


def test_the_empty_history_placeholder_cannot_be_selected():
    # Selecting it enabled the destructive revert button for commit "--------".
    body = _function(BUILD_PACKAGE / "advanced_widget.py", "apply_snapshot")

    assert "set_activatable(False)" in body
    assert "set_selectable(False)" in body


def test_an_identical_source_and_target_is_reported():
    body = _function(BUILD_PACKAGE / "branch_widget.py", "on_merge_clicked")

    assert "show_error_toast" in body


def test_a_failed_history_clear_is_reported():
    body = _function(BUILD_ISO / "history_widget.py", "_on_clear_confirmed")

    assert "_report_storage_failure" in body


def test_a_failed_settings_reset_does_not_redisplay_old_values_as_applied():
    body = _function(BUILD_ISO / "settings_widget.py", "_on_reset_confirmed")

    assert "_report_settings_failure" in body
    # The reload must not run when the reset failed.
    assert body.index("_report_settings_failure") < body.index("_load_settings")
    assert "return" in body


def test_the_reporting_helpers_exist():
    for path, name in (
        (BUILD_ISO / "history_widget.py", "_report_storage_failure"),
        (BUILD_ISO / "settings_widget.py", "_report_settings_failure"),
    ):
        assert "show_toast" in _function(path, name)
