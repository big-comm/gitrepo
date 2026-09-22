"""The emblem CSS parses and stays scoped to Nautilus view cells."""

import pytest

from gitrepo.file_manager import nautilus_css


def test_emblem_css_parses():
    assert nautilus_css.load_provider() is not None


def test_parse_errors_are_reported():
    with pytest.raises(ValueError):
        nautilus_css.load_provider("box { opacity: ; }")


def test_css_only_targets_nautilus_cells():
    for selector in nautilus_css.EMBLEM_CSS.split("{")[0].split(","):
        assert ".nautilus-view-cell box.dim-label" in selector


def test_install_without_display_is_a_noop(monkeypatch):
    monkeypatch.setattr(nautilus_css.Gdk.Display, "get_default", staticmethod(lambda: None))
    assert nautilus_css.install() is None
