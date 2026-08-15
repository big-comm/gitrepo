"""A menu body must not grow the dialog past its own responses.

The translation-catalog conflict names every file it found: merging the
translation workflow's output produced a 39-line body, and the unscrolled
label sized the dialog taller than the screen. The responses -- the only way
to answer the question -- ended up below the bottom edge, so the prompt could
not be answered or dismissed at all.

The helper is executed against a recording double rather than real GTK. The
package is built with no display: constructing a Gtk.Label there segfaults
inside pango, so a test that builds widgets fails the check() stage of the
PKGBUILD instead of the code it is meant to guard.
"""

import ast
from pathlib import Path

ADAPTERS = Path(__file__).parents[2] / "usr/share/gitrepo/build_package/gui/gtk_adapters.py"


class Recorder:
    """Records the calls made on it, so the helper can be read back as data."""

    def __init__(self, name):
        self.name = name
        self.calls = {}

    def __getattr__(self, attribute):
        def record(*args):
            self.calls[attribute] = args
            return None

        return record


class FakeGtk:
    class PolicyType:
        NEVER = "never"
        AUTOMATIC = "automatic"

    class Orientation:
        VERTICAL = "vertical"

    @staticmethod
    def ScrolledWindow():
        return Recorder("ScrolledWindow")


def load_helper():
    """The helper alone, without importing the module's GTK/Adw dependencies."""
    tree = ast.parse(ADAPTERS.read_text(encoding="utf-8"))
    wanted = ("_scrollable_details", "_DETAILS_MAX_HEIGHT", "_DETAILS_MIN_WIDTH")
    body = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in wanted)
    ]
    namespace = {"Gtk": FakeGtk}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(ADAPTERS), "exec"), namespace)
    return namespace


def build(namespace, details="the body"):
    return namespace["_scrollable_details"](details)


def test_the_body_scrolls_instead_of_growing_the_dialog():
    namespace = load_helper()

    scrolled = build(namespace)

    assert scrolled.calls["set_policy"] == (FakeGtk.PolicyType.NEVER, FakeGtk.PolicyType.AUTOMATIC)
    assert scrolled.calls["set_max_content_height"] == (namespace["_DETAILS_MAX_HEIGHT"],)


def test_the_cap_leaves_room_for_the_responses():
    # A ceiling taller than a small laptop's work area would not have fixed
    # anything: the dialog also carries a heading and a row of responses.
    namespace = load_helper()

    assert 0 < namespace["_DETAILS_MAX_HEIGHT"] <= 480


def test_a_short_body_keeps_its_own_height():
    # The cap is a ceiling, not a size: a two-line question must not open a
    # dialog with 360px of empty space under it.
    namespace = load_helper()

    scrolled = build(namespace)

    assert scrolled.calls["set_propagate_natural_height"] == (True,)


def test_the_body_gets_a_readable_width():
    # A wrapped label left to itself settles on a column too narrow to read a
    # file path in, which is exactly what these long bodies are made of.
    namespace = load_helper()

    scrolled = build(namespace)

    width, height = scrolled.calls["set_size_request"]
    assert width >= 480
    # -1 leaves the height to the ceiling above; a fixed one would defeat it.
    assert height == -1


def test_the_details_are_the_scrolled_child():
    namespace = load_helper()
    details = object()

    scrolled = build(namespace, details)

    assert scrolled.calls["set_child"] == (details,)


def test_the_menu_dialog_uses_the_helper():
    # The regression was in show_menu attaching the bare label.
    tree = ast.parse(ADAPTERS.read_text(encoding="utf-8"))
    show_menu = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "show_menu"
    )

    assert "set_extra_child(_scrollable_details(details))" in ast.unparse(show_menu)
