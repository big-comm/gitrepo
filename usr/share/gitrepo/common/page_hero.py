"""Adaptive page headings shared by the two GTK applications."""

from __future__ import annotations

import gi

from .translation import _

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango  # noqa: E402


def git_command_description(*commands: str) -> str:
    """Describe the exact Git sequence behind a visible action."""
    return _("Git commands: {0}").format(" → ".join(commands))


def github_action_description(action: str) -> str:
    """Identify remote GitHub work without presenting it as a Git command."""
    return _("GitHub action: {0}").format(action)


def is_large_text_enabled(settings: Gtk.Settings) -> bool:
    """Return whether the effective UI font benefits from a stacked layout."""
    font = Pango.FontDescription.from_string(settings.get_property("gtk-font-name"))
    font_points = font.get_size() / Pango.SCALE
    dpi = settings.get_property("gtk-xft-dpi")
    dpi_scale = dpi / (96 * 1024) if dpi and dpi > 0 else 1
    return font_points * dpi_scale >= 16


class PageHero(Gtk.WindowHandle):
    """Draggable, accessible heading with product-specific CSS names."""

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        action: Gtk.Widget | None = None,
        *,
        css_prefix: str,
    ) -> None:
        super().__init__()

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.add_css_class(f"{css_prefix}-page-hero")

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        heading.set_hexpand(True)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(56)
        icon.add_css_class(f"{css_prefix}-page-hero-icon")
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(icon)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        copy.set_hexpand(True)
        copy.set_valign(Gtk.Align.CENTER)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("title-2")
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        copy.append(title_label)

        self.description_label = Gtk.Label(label=description, xalign=0)
        self.description_label.add_css_class(f"{css_prefix}-hero-subtitle")
        self.description_label.set_wrap(True)
        self.description_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.description_label.set_width_chars(1)
        copy.append(self.description_label)

        heading.append(copy)
        content.append(heading)

        if action is not None:
            action.set_valign(Gtk.Align.CENTER)
            content.append(action)

        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:

            def sync_layout(*_args: object) -> None:
                is_large = is_large_text_enabled(gtk_settings)
                content.set_orientation(Gtk.Orientation.VERTICAL if is_large else Gtk.Orientation.HORIZONTAL)
                if action is not None:
                    action.set_halign(Gtk.Align.START if is_large else Gtk.Align.FILL)

            gtk_settings.connect("notify::gtk-font-name", sync_layout)
            gtk_settings.connect("notify::gtk-xft-dpi", sync_layout)
            sync_layout()

        self.set_child(content)


class BuildPackagePageHero(PageHero):
    def __init__(self, icon_name: str, title: str, description: str, action: Gtk.Widget | None = None) -> None:
        super().__init__(icon_name, title, description, action, css_prefix="build-package")


class BuildIsoPageHero(PageHero):
    def __init__(self, icon_name: str, title: str, description: str, action: Gtk.Widget | None = None) -> None:
        super().__init__(icon_name, title, description, action, css_prefix="build-iso")
