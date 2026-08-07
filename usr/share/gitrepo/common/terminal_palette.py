"""Readable terminal-log colours for both GitRepo progress dialogs."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

# Terminal colours must stay readable on both themes, so each tag carries an
# explicit foreground instead of relying on the default text colour.
LOG_COLORS_LIGHT = {
    "red": "#c01c28",
    "green": "#1a7f37",
    "yellow": "#9c6500",
    "orange": "#a33e03",
    "blue": "#1c71d8",
    "magenta": "#9141ac",
    "purple": "#9141ac",
    "cyan": "#0b6e8c",
    "white": "#241f31",
    "bold-white": "#000000",
    "dim": "#77767b",
}
LOG_COLORS_DARK = {
    "red": "#ff938c",
    "green": "#8ff0a4",
    "yellow": "#f8e45c",
    "orange": "#ffbe6f",
    "blue": "#99c1f1",
    "magenta": "#dc8add",
    "purple": "#dc8add",
    "cyan": "#7bd0e0",
    "white": "#deddda",
    "bold-white": "#ffffff",
    "dim": "#9a9996",
}


def log_palette(is_dark: bool) -> dict[str, str]:
    """Return the terminal-log foregrounds for the active colour scheme."""
    return LOG_COLORS_DARK if is_dark else LOG_COLORS_LIGHT


def apply_log_palette(buffer: Gtk.TextBuffer, is_dark: bool) -> None:
    """Repaint the tags a log buffer already owns for the active scheme."""
    tag_table = buffer.get_tag_table()
    for name, color in log_palette(is_dark).items():
        tag = tag_table.lookup(name)
        if tag is None:
            continue
        rgba = Gdk.RGBA()
        if rgba.parse(color):
            tag.set_property("foreground-rgba", rgba)
