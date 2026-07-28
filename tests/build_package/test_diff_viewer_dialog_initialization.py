"""Regression tests for the graphical diff viewer lifecycle."""

import ast
from pathlib import Path
from types import SimpleNamespace

from gitrepo.build_package.gui.dialogs.diff_viewer_dialog import DiffViewerDialog


DIALOG_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "usr"
    / "share"
    / "gitrepo"
    / "build_package"
    / "gui"
    / "dialogs"
    / "diff_viewer_dialog.py"
)


class SelfCallCollector(ast.NodeVisitor):
    """Collect direct self method calls in source order."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            if function.value.id == "self":
                self.names.append(function.attr)
        self.generic_visit(node)


def test_diff_view_exists_before_initial_file_selection() -> None:
    tree = ast.parse(DIALOG_SOURCE.read_text(encoding="utf-8"))
    dialog_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DiffViewerDialog"
    )
    initializer = next(
        node for node in dialog_class.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    calls = SelfCallCollector()
    calls.visit(initializer)

    assert calls.names.index("_create_diff_view") < calls.names.index("_create_file_list")


def test_closing_dialog_disconnects_global_style_handler_once() -> None:
    disconnected: list[int] = []
    dialog = SimpleNamespace(
        _style_handler=17,
        _style_manager=SimpleNamespace(disconnect=disconnected.append),
    )

    assert DiffViewerDialog._on_close_request(dialog, None) is False
    assert dialog._style_handler == 0
    assert disconnected == [17]

    assert DiffViewerDialog._on_close_request(dialog, None) is False
    assert disconnected == [17]


def test_review_action_closes_before_callback_and_runs_once() -> None:
    events: list[object] = []
    button = SimpleNamespace(set_sensitive=lambda value: events.append(("sensitive", value)))
    dialog = SimpleNamespace(
        _action_callback=lambda: events.append("callback"),
        close=lambda: events.append("close"),
    )

    DiffViewerDialog._on_action_clicked(dialog, button)
    DiffViewerDialog._on_action_clicked(dialog, button)

    assert events == [
        ("sensitive", False),
        "close",
        "callback",
        ("sensitive", False),
        "close",
    ]
