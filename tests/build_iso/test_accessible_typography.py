from pathlib import Path

from gitrepo.build_iso.gui.main_gui import BuildISOApplication
from gitrepo.common.page_hero import is_large_text_enabled
from gitrepo.common.premium_style import premium_css


PROJECT_ROOT = Path(__file__).parents[2]
WIDGET_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_iso/gui/widgets"
PAGE_HERO = PROJECT_ROOT / "usr/share/gitrepo/common/page_hero.py"
MAIN_WINDOW = PROJECT_ROOT / "usr/share/gitrepo/build_iso/gui/main_window.py"


def test_content_descriptions_use_readable_body_text():
    css = premium_css() + BuildISOApplication._get_default_css()

    assert "--dim-opacity: 72%;" in css
    assert ".content-canvas row label.subtitle" in css
    assert "font-size: inherit;" in css
    assert ".content-canvas .caption.dim-label" in css


def test_high_contrast_preserves_stronger_description_contrast():
    css = premium_css() + BuildISOApplication._get_default_css()

    assert "@media (prefers-contrast: more)" in css
    assert "--dim-opacity: 90%;" in css


def test_page_hero_reflows_for_large_text():
    hero_source = PAGE_HERO.read_text(encoding="utf-8")

    assert "set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)" in hero_source
    assert "self.description_label.set_width_chars(1)" in hero_source
    assert "Gtk.Orientation.VERTICAL if is_large else Gtk.Orientation.HORIZONTAL" in hero_source


def test_edition_choice_stays_one_row_with_clean_product_names():
    build_source = (WIDGET_ROOT / "build_widget.py").read_text(encoding="utf-8")

    # A long catalog reads better as one row than as a wall of cards.
    assert "self.edition_row = Adw.ComboRow()" in build_source
    assert "Gtk.FlowBox()" not in build_source
    assert '_("{0} (recommended)")' not in build_source


def test_build_page_orders_the_journey_and_folds_the_defaults():
    build_source = (WIDGET_ROOT / "build_widget.py").read_text(encoding="utf-8")

    # What, then where, then everything that already has a good default.
    assert build_source.index('_("What the ISO will install")') < build_source.index('_("Where to save it")')
    assert build_source.index('_("Where to save it")') < build_source.index('_("Advanced options")')
    advanced = build_source.split("def _create_advanced_section", 1)[1].split("def _create_footer", 1)[0]
    for folded in ('_("Kernel Variant")', '_("Manjaro Packages")', '_("Profile source")'):
        assert folded in advanced


def test_window_keeps_its_minimum_size():
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "self.set_size_request(1000, 600)" in window_source


def test_build_page_announces_a_broken_environment_with_its_fix():
    build_source = (WIDGET_ROOT / "build_widget.py").read_text(encoding="utf-8")

    assert "self.environment_banner = Adw.Banner()" in build_source
    assert 'self.environment_banner.set_button_label(_("Open settings"))' in build_source
    assert '"open-environment"' in build_source
    # A healthy environment is stated once, quietly, instead of as three cards,
    # and it names the engine rather than echoing its raw version banner.
    assert '_("Environment ready • {0} {1} • {2:.1f} GB free")' in build_source
    assert '(status.engine or "").capitalize()' in build_source


def test_navigation_and_page_controls_expose_accessible_labels():
    build_source = (WIDGET_ROOT / "build_widget.py").read_text(encoding="utf-8")
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert 'self.output_row.update_property([Gtk.AccessibleProperty.LABEL], [_("Destination path")])' in build_source
    assert "nav_row.update_property([Gtk.AccessibleProperty.LABEL], [title])" in window_source
    assert "row.update_property(" in window_source

    settings_source = (WIDGET_ROOT / "settings_widget.py").read_text(encoding="utf-8")
    assert "browse_btn.update_property([Gtk.AccessibleProperty.LABEL]" in settings_source


def test_sidebar_destinations_are_explicit_single_action_rows():
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")
    navigation_row_source = window_source.split("    def _append_navigation_row", 1)[1].split(
        "    def connect_widget_signals", 1
    )[0]

    assert "nav_row = Adw.ActionRow(title=title)" in navigation_row_source
    assert "nav_row.set_activatable(True)" in navigation_row_source
    assert "self.nav_list.append(nav_row)" in navigation_row_source
    assert 'nav_row.connect("activated"' in navigation_row_source
    assert "Gtk.Button" not in navigation_row_source
    assert ".get_parent()" not in navigation_row_source


def test_large_text_detection_includes_font_size_and_dpi_scaling():
    class Settings:
        def __init__(self, font_name, dpi):
            self.properties = {"gtk-font-name": font_name, "gtk-xft-dpi": dpi}

        def get_property(self, name):
            return self.properties[name]

    assert not is_large_text_enabled(Settings("Noto Sans 10", 96 * 1024))
    assert is_large_text_enabled(Settings("Noto Sans 20", 96 * 1024))
    assert is_large_text_enabled(Settings("Noto Sans 10", 192 * 1024))
