"""Contextual explanations shared by the two GTK applications."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from .translation import _  # noqa: E402


def help_button(title: str, body: str) -> Gtk.MenuButton:
    """Return a compact explanation attached to one configuration group."""
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)

    title_label = Gtk.Label(label=title, xalign=0)
    title_label.add_css_class("heading")
    title_label.set_wrap(True)
    title_label.set_max_width_chars(34)
    content.append(title_label)

    body_label = Gtk.Label(label=body, xalign=0)
    body_label.set_wrap(True)
    body_label.set_max_width_chars(38)
    content.append(body_label)

    popover = Gtk.Popover()
    popover.set_child(content)

    button = Gtk.MenuButton()
    button.set_icon_name("help-about-symbolic")
    button.set_popover(popover)
    button.add_css_class("flat")
    button.set_valign(Gtk.Align.CENTER)
    button.set_tooltip_text(_("What does this mean?"))
    button.update_property([Gtk.AccessibleProperty.LABEL], [_("Explain: {0}").format(title)])
    return button
