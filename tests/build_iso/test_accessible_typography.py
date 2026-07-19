from pathlib import Path

from gitrepo.build_iso.gui.main_gui import BuildISOApplication
from gitrepo.common.page_hero import is_large_text_enabled


PROJECT_ROOT = Path(__file__).parents[2]
WIDGET_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_iso/gui/widgets"
PAGE_HERO = PROJECT_ROOT / "usr/share/gitrepo/common/page_hero.py"
MAIN_WINDOW = PROJECT_ROOT / "usr/share/gitrepo/build_iso/gui/main_window.py"


def test_content_descriptions_use_readable_body_text():
    css = BuildISOApplication._get_default_css(None)

    assert ".content-canvas {\n                --dim-opacity: 72%;\n" in css
    assert ".content-canvas row label.subtitle" in css
    assert "font-size: inherit;" in css
    assert ".content-canvas .caption.dim-label" in css


def test_high_contrast_preserves_stronger_description_contrast():
    css = BuildISOApplication._get_default_css(None)

    assert "@media (prefers-contrast: more)" in css
    assert "--dim-opacity: 90%;" in css


def test_dashboard_and_page_hero_reflow_for_large_text():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")
    hero_source = PAGE_HERO.read_text(encoding="utf-8")

    assert "status_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)" in dashboard_source
    assert "status_grid.set_homogeneous(True)" in dashboard_source
    assert "if is_large_text_enabled(gtk_settings)" in dashboard_source
    assert "else Gtk.Orientation.HORIZONTAL" in dashboard_source
    assert "status_grid.set_min_children_per_line" not in dashboard_source
    assert "detail.set_width_chars(1)" in dashboard_source
    assert "set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)" in hero_source
    assert "self.description_label.set_width_chars(1)" in hero_source
    assert "Gtk.Orientation.VERTICAL if is_large else Gtk.Orientation.HORIZONTAL" in hero_source


def test_status_card_text_can_shrink_to_the_available_width():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")
    status_card_source = dashboard_source.split("def _create_status_card", 1)[1].split(
        "def _create_destination_card", 1
    )[0]

    assert "title_label.set_width_chars(1)" in status_card_source
    assert "detail.set_width_chars(1)" in status_card_source
    assert "detail.set_wrap_mode(Pango.WrapMode.WORD_CHAR)" in status_card_source
    assert "set_max_width_chars" not in status_card_source


def test_quick_action_icon_and_title_share_the_card_heading():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")
    destination_card_source = dashboard_source.split("def _create_destination_card", 1)[1].split("def set_checking", 1)[
        0
    ]

    assert "heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)" in destination_card_source
    assert "heading.append(icon)" in destination_card_source
    assert "heading.append(title_label)" in destination_card_source
    assert "content.append(heading)" in destination_card_source


def test_dashboard_hero_has_no_action_and_window_minimum_is_1000_by_600():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")
    dashboard_hero_source = dashboard_source.split("def _create_ui", 1)[1].split("def _create_status_section", 1)[0]
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "Gtk.Button" not in dashboard_hero_source
    assert "configure_button" not in dashboard_hero_source
    assert "self.set_size_request(1000, 600)" in window_source


def test_dashboard_explains_what_an_iso_is_and_how_it_is_built():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")

    assert '_("Create an installable Linux system image")' in dashboard_source
    assert "used to install or test a system from a USB drive or virtual machine" in dashboard_source
    assert "builds them in an isolated" in dashboard_source
    assert '_("Choose a system profile")' in dashboard_source
    assert '_("Prepare the build environment")' in dashboard_source
    assert '_("Review generated ISOs")' in dashboard_source


def test_navigation_and_destination_buttons_expose_accessible_labels():
    dashboard_source = (WIDGET_ROOT / "dashboard_widget.py").read_text(encoding="utf-8")
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")

    label_update = "button.update_property([Gtk.AccessibleProperty.LABEL], [title])"
    assert label_update in dashboard_source
    assert label_update in window_source

    settings_source = (WIDGET_ROOT / "settings_widget.py").read_text(encoding="utf-8")
    assert "browse_btn.update_property([Gtk.AccessibleProperty.LABEL]" in settings_source


def test_large_text_detection_includes_font_size_and_dpi_scaling():
    class Settings:
        def __init__(self, font_name, dpi):
            self.properties = {"gtk-font-name": font_name, "gtk-xft-dpi": dpi}

        def get_property(self, name):
            return self.properties[name]

    assert not is_large_text_enabled(Settings("Noto Sans 10", 96 * 1024))
    assert is_large_text_enabled(Settings("Noto Sans 20", 96 * 1024))
    assert is_large_text_enabled(Settings("Noto Sans 10", 192 * 1024))
