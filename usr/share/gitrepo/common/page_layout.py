"""Readable page bodies shared by the two GTK applications."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

# Long measures are hard to scan. Page bodies stop growing at this width while
# the hero keeps spanning the whole window.
BODY_MAXIMUM_WIDTH = 920
BODY_TIGHTENING_WIDTH = 760


def page_body(*, spacing: int = 0) -> tuple[Adw.Clamp, Gtk.Box]:
    """Return the clamp to append to a page and the box that holds its content."""
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    content.add_css_class("page-frame")
    clamp = Adw.Clamp(child=content)
    clamp.set_maximum_size(BODY_MAXIMUM_WIDTH)
    clamp.set_tightening_threshold(BODY_TIGHTENING_WIDTH)
    return clamp, content
