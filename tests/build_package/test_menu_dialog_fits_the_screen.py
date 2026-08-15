"""A menu body must not grow the dialog past its own responses.

The translation-catalog conflict names every file it found: merging the
translation workflow's output produced a 39-line body, and the unscrolled
label sized the dialog taller than the screen. The responses -- the only way
to answer the question -- ended up below the bottom edge, so the prompt could
not be answered or dismissed at all.

Only the widget is built here; nothing is presented, so no display is needed.
"""

import ast
from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

ADAPTERS = Path(__file__).parents[2] / "usr/share/gitrepo/build_package/gui/gtk_adapters.py"


def _scrollable_details():
    """The helper, loaded without importing the module's GTK/Adw dependencies."""
    tree = ast.parse(ADAPTERS.read_text(encoding="utf-8"))
    wanted = ("_scrollable_details", "_DETAILS_MAX_HEIGHT", "_DETAILS_MIN_WIDTH")
    body = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in wanted)
    ]
    namespace = {"Gtk": Gtk}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(ADAPTERS), "exec"), namespace)
    return namespace["_scrollable_details"], namespace["_DETAILS_MAX_HEIGHT"]


def test_a_long_body_is_capped_and_scrolls():
    build, max_height = _scrollable_details()
    catalogs = "\n".join(f"• usr/share/locale/{code}/LC_MESSAGES/LangForge.mo" for code in range(39))
    label = Gtk.Label(label=catalogs, wrap=True, xalign=0)

    scrolled = build(label)

    assert scrolled.get_max_content_height() == max_height
    _horizontal, vertical = scrolled.get_policy()
    assert vertical == Gtk.PolicyType.AUTOMATIC
    # The natural height of the label alone is what pushed the responses off
    # the screen; inside the scroller the dialog can never ask for more.
    _, natural, _baseline_min, _baseline_nat = scrolled.measure(Gtk.Orientation.VERTICAL, -1)
    assert natural <= max_height


def test_a_short_body_keeps_its_own_height():
    # The cap is a ceiling, not a size: a two-line question must not open a
    # dialog with 360px of empty space under it.
    build, max_height = _scrollable_details()
    label = Gtk.Label(label="Keep dev-talesam or use origin/main?", wrap=True, xalign=0)

    scrolled = build(label)

    assert scrolled.get_propagate_natural_height() is True
    _, natural, _baseline_min, _baseline_nat = scrolled.measure(Gtk.Orientation.VERTICAL, -1)
    assert natural < max_height


def test_the_body_gets_a_readable_width():
    # A wrapped label left to itself settles on a column too narrow to read a
    # file path in, which is exactly what these long bodies are made of.
    build, _max_height = _scrollable_details()
    label = Gtk.Label(label="• usr/share/locale/pt_BR/LC_MESSAGES/LangForge.mo", wrap=True, xalign=0)

    scrolled = build(label)

    minimum, _natural, _baseline_min, _baseline_nat = scrolled.measure(Gtk.Orientation.HORIZONTAL, -1)
    assert minimum >= 520


def test_the_menu_dialog_uses_the_helper():
    # The regression was in show_menu attaching the bare label.
    tree = ast.parse(ADAPTERS.read_text(encoding="utf-8"))
    show_menu = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "show_menu"
    )
    source = ast.unparse(show_menu)

    assert "set_extra_child(_scrollable_details(details))" in source
