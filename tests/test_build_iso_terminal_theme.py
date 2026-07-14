from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROGRESS_DIALOG = PROJECT_ROOT / "usr/share/build-iso/gui/dialogs/progress_dialog.py"
STYLE_SHEET = PROJECT_ROOT / "usr/share/build-iso/resources/style.css"


def test_build_log_uses_terminal_theme_classes():
    source = PROGRESS_DIALOG.read_text()

    assert 'scrolled.add_css_class("terminal-frame")' in source
    assert 'self.log_view.add_css_class("terminal-view")' in source


def test_terminal_text_node_has_fixed_dark_palette():
    css = STYLE_SHEET.read_text()

    assert "textview.terminal-view text" in css
    assert "background-color: #1e1e2e" in css
    assert "color: #cdd6f4" in css
