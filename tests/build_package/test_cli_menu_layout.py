"""The terminal menu keeps its frame square and wraps long options under their text.

The commit type menu broke in a user's terminal: long descriptions wrapped to
the left edge, under the bullet, and the "custom" line pushed the right border
out of place because ✏️ (U+270F + VS16) is one cell in some terminals and two
in others.
"""

import io
from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.console import Console

from gitrepo.build_package.cli import cli_menu
from gitrepo.build_package.core.build_package import BuildPackage


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(cli_menu.subprocess, "run", lambda *args, **kwargs: None)

    def draw(title, options, selected=0):
        menu = cli_menu.MenuSystem(SimpleNamespace(draw_app_header=lambda: None))
        menu.console = Console(file=io.StringIO(), width=100, record=True, color_system=None)
        menu._draw_menu(title, options, selected, None)
        return [line for line in menu.console.export_text().splitlines() if line[:1] in "╭│╰"]

    return draw


def _commit_options():
    return [f"{emoji} {kind}: {description}" for emoji, kind, description in BuildPackage.get_commit_types(None)]


@pytest.mark.parametrize("language", ["en", "pt_BR", "de", "ja"])
def test_every_line_of_the_commit_menu_closes_its_frame(render, monkeypatch, language):
    monkeypatch.setenv("LANGUAGE", language)
    lines = render("Select commit type", _commit_options(), selected=1)
    assert {cell_len(line) for line in lines} == {70}
    assert all(line.endswith(("│", "╮", "╯")) for line in lines)


def test_commit_icons_are_two_cells_wide_everywhere():
    for emoji, _kind, _description in BuildPackage.get_commit_types(None):
        # A variation selector makes the width depend on the terminal.
        assert "️" not in emoji
        assert cell_len(emoji) == 2


def test_a_wrapped_option_continues_under_its_text(render, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")
    long = "🔨 refactor: " + "word " * 30
    lines = render("Select commit type", ["✨ feat: short", long.strip()])
    body = [line[1:-1] for line in lines[1:-1] if line[1:-1].strip()]
    first, continuation = body[1], body[2]
    assert first.startswith("    🔨 refactor:")
    # Under "refactor", past the bullet and the icon: 2 + 2 + 3 columns.
    assert continuation.startswith(" " * 7 + "word")


def test_options_are_shown_as_typed_not_as_markup(render):
    lines = render("Branch", ["[bold]dev-x[/]", "Straight to main"])
    assert any("[bold]dev-x[/]" in line for line in lines)
