#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/ui_helpers.py - Shared GTK UI helpers
#

import gi
import cairo
import math

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk


_TONE_RGB = {
    "accent": (0.38, 0.71, 1.0),
    "success": (0.34, 0.89, 0.54),
    "warning": (0.97, 0.89, 0.36),
    "error": (1.0, 0.48, 0.48),
    "purple": (0.74, 0.58, 1.0),
    "neutral": (0.82, 0.82, 0.82),
}

_TONE_BG_RGBA = {
    "accent": (0.22, 0.48, 0.78, 0.24),
    "success": (0.18, 0.76, 0.45, 0.18),
    "warning": (0.96, 0.83, 0.18, 0.18),
    "error": (0.93, 0.20, 0.23, 0.18),
    "purple": (0.60, 0.40, 1.0, 0.18),
    "neutral": (1.0, 1.0, 1.0, 0.10),
}

_ICON_KINDS = {
    "bookmark-remove-symbolic": "bookmark",
    "dialog-warning-symbolic": "warning",
    "document-edit-symbolic": "edit",
    "document-open-recent-symbolic": "clock",
    "document-save-symbolic": "save",
    "edit-clear-symbolic": "x",
    "edit-copy-symbolic": "copy",
    "edit-delete-symbolic": "x",
    "edit-undo-symbolic": "undo",
    "emblem-ok-symbolic": "check",
    "folder-symbolic": "folder",
    "go-down-symbolic": "down",
    "go-next-symbolic": "right",
    "go-up-symbolic": "up",
    "list-add-symbolic": "plus",
    "media-playlist-consecutive-symbolic": "right",
    "package-x-generic-symbolic": "package",
    "process-stop-symbolic": "record",
    "system-software-install-symbolic": "grid",
    "system-users-symbolic": "users",
    "utilities-terminal-symbolic": "terminal",
    "view-list-symbolic": "list",
    "web-browser-symbolic": "globe",
}


def _set_icon_color(cr, tone):
    red, green, blue = _TONE_RGB.get(tone, _TONE_RGB["accent"])
    cr.set_source_rgb(red, green, blue)


def _rounded_rect(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
    cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
    cr.close_path()


def _stroke_arrow(cr, cx, cy, size, direction):
    half = size * 0.28
    head = size * 0.20
    if direction == "right":
        cr.move_to(cx - half, cy)
        cr.line_to(cx + half, cy)
        cr.move_to(cx + half - head, cy - head)
        cr.line_to(cx + half, cy)
        cr.line_to(cx + half - head, cy + head)
    elif direction == "down":
        cr.move_to(cx, cy - half)
        cr.line_to(cx, cy + half)
        cr.move_to(cx - head, cy + half - head)
        cr.line_to(cx, cy + half)
        cr.line_to(cx + head, cy + half - head)
    else:
        cr.move_to(cx, cy + half)
        cr.line_to(cx, cy - half)
        cr.move_to(cx - head, cy - half + head)
        cr.line_to(cx, cy - half)
        cr.line_to(cx + head, cy - half + head)
    cr.stroke()


def _draw_check(cr, cx, cy, size):
    cr.move_to(cx - size * 0.30, cy + size * 0.02)
    cr.line_to(cx - size * 0.08, cy + size * 0.24)
    cr.line_to(cx + size * 0.34, cy - size * 0.26)
    cr.stroke()


def _draw_icon(area, cr, width, height, data):
    icon_name, tone, requested_size = data
    kind = _ICON_KINDS.get(icon_name, "package")
    size = min(max(requested_size, 24), min(width, height) - 14)
    cx = width / 2
    cy = height / 2
    line_width = max(2.4, size * 0.12)

    bg = _TONE_BG_RGBA.get(tone, _TONE_BG_RGBA["accent"])
    cr.set_source_rgba(*bg)
    _rounded_rect(cr, 0.5, 0.5, width - 1, height - 1, 8)
    cr.fill()

    _set_icon_color(cr, tone)
    cr.set_line_width(line_width)
    cr.set_line_cap(cairo.LineCap.ROUND)
    cr.set_line_join(cairo.LineJoin.ROUND)

    if kind in ("right", "down", "up"):
        _stroke_arrow(cr, cx, cy, size, kind)
        return

    if kind == "check":
        _draw_check(cr, cx, cy, size)
        return

    if kind == "plus":
        arm = size * 0.30
        cr.move_to(cx - arm, cy)
        cr.line_to(cx + arm, cy)
        cr.move_to(cx, cy - arm)
        cr.line_to(cx, cy + arm)
        cr.stroke()
        return

    if kind == "x":
        arm = size * 0.25
        cr.move_to(cx - arm, cy - arm)
        cr.line_to(cx + arm, cy + arm)
        cr.move_to(cx + arm, cy - arm)
        cr.line_to(cx - arm, cy + arm)
        cr.stroke()
        return

    if kind == "edit":
        cr.move_to(cx - size * 0.26, cy + size * 0.23)
        cr.line_to(cx + size * 0.22, cy - size * 0.25)
        cr.move_to(cx + size * 0.12, cy - size * 0.32)
        cr.line_to(cx + size * 0.29, cy - size * 0.15)
        cr.stroke()
        return

    if kind == "list":
        for offset in (-0.24, 0.0, 0.24):
            y = cy + size * offset
            cr.rectangle(cx - size * 0.34, y - line_width / 2, line_width, line_width)
            cr.fill()
            cr.move_to(cx - size * 0.15, y)
            cr.line_to(cx + size * 0.34, y)
            cr.stroke()
        return

    if kind == "folder":
        _rounded_rect(cr, cx - size * 0.34, cy - size * 0.18, size * 0.68, size * 0.43, 3)
        cr.fill()
        cr.rectangle(cx - size * 0.34, cy - size * 0.28, size * 0.28, size * 0.18)
        cr.fill()
        return

    if kind == "package":
        radius = size * 0.32
        cr.move_to(cx, cy - radius)
        for point in range(1, 6):
            angle = -1.5708 + point * 1.0472
            cr.line_to(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        cr.close_path()
        cr.stroke()
        cr.move_to(cx, cy - radius)
        cr.line_to(cx, cy)
        cr.line_to(cx + radius * 0.82, cy - radius * 0.47)
        cr.move_to(cx, cy)
        cr.line_to(cx - radius * 0.82, cy - radius * 0.47)
        cr.stroke()
        return

    if kind == "clock":
        cr.arc(cx, cy, size * 0.30, 0, 6.2832)
        cr.stroke()
        cr.move_to(cx, cy)
        cr.line_to(cx, cy - size * 0.17)
        cr.move_to(cx, cy)
        cr.line_to(cx + size * 0.14, cy + size * 0.08)
        cr.stroke()
        return

    if kind == "warning":
        top = cy - size * 0.34
        left = cx - size * 0.34
        right = cx + size * 0.34
        bottom = cy + size * 0.28
        cr.move_to(cx, top)
        cr.line_to(right, bottom)
        cr.line_to(left, bottom)
        cr.close_path()
        cr.stroke()
        cr.move_to(cx, cy - size * 0.10)
        cr.line_to(cx, cy + size * 0.10)
        cr.stroke()
        cr.arc(cx, cy + size * 0.24, line_width * 0.45, 0, 6.2832)
        cr.fill()
        return

    if kind == "undo":
        cr.arc(cx + size * 0.04, cy, size * 0.27, 0.15, 4.3)
        cr.stroke()
        cr.move_to(cx - size * 0.24, cy - size * 0.24)
        cr.line_to(cx - size * 0.38, cy - size * 0.02)
        cr.line_to(cx - size * 0.12, cy + size * 0.01)
        cr.stroke()
        return

    if kind == "save":
        _rounded_rect(cr, cx - size * 0.28, cy - size * 0.30, size * 0.56, size * 0.60, 3)
        cr.stroke()
        cr.rectangle(cx - size * 0.14, cy - size * 0.24, size * 0.24, size * 0.16)
        cr.fill()
        cr.move_to(cx - size * 0.16, cy + size * 0.14)
        cr.line_to(cx + size * 0.16, cy + size * 0.14)
        cr.stroke()
        return

    if kind == "copy":
        _rounded_rect(cr, cx - size * 0.18, cy - size * 0.30, size * 0.38, size * 0.46, 3)
        cr.stroke()
        _rounded_rect(cr, cx - size * 0.30, cy - size * 0.16, size * 0.38, size * 0.46, 3)
        cr.stroke()
        return

    if kind == "grid":
        cell = size * 0.18
        gap = size * 0.13
        start_x = cx - cell - gap / 2
        start_y = cy - cell - gap / 2
        for row in range(2):
            for col in range(2):
                cr.rectangle(start_x + col * (cell + gap), start_y + row * (cell + gap), cell, cell)
                cr.fill()
        return

    if kind == "terminal":
        cr.move_to(cx - size * 0.28, cy - size * 0.14)
        cr.line_to(cx - size * 0.08, cy)
        cr.line_to(cx - size * 0.28, cy + size * 0.14)
        cr.move_to(cx + size * 0.02, cy + size * 0.18)
        cr.line_to(cx + size * 0.30, cy + size * 0.18)
        cr.stroke()
        return

    if kind == "globe":
        cr.arc(cx, cy, size * 0.30, 0, 6.2832)
        cr.stroke()
        cr.move_to(cx - size * 0.30, cy)
        cr.line_to(cx + size * 0.30, cy)
        cr.move_to(cx, cy - size * 0.30)
        cr.curve_to(cx - size * 0.12, cy - size * 0.12, cx - size * 0.12, cy + size * 0.12, cx, cy + size * 0.30)
        cr.move_to(cx, cy - size * 0.30)
        cr.curve_to(cx + size * 0.12, cy - size * 0.12, cx + size * 0.12, cy + size * 0.12, cx, cy + size * 0.30)
        cr.stroke()
        return

    if kind == "users":
        cr.arc(cx - size * 0.09, cy - size * 0.12, size * 0.13, 0, 6.2832)
        cr.stroke()
        cr.arc(cx + size * 0.14, cy - size * 0.04, size * 0.10, 0, 6.2832)
        cr.stroke()
        cr.arc(cx - size * 0.06, cy + size * 0.22, size * 0.22, 3.1416, 6.2832)
        cr.stroke()
        return

    if kind == "bookmark":
        cr.move_to(cx - size * 0.22, cy - size * 0.30)
        cr.line_to(cx + size * 0.22, cy - size * 0.30)
        cr.line_to(cx + size * 0.22, cy + size * 0.30)
        cr.line_to(cx, cy + size * 0.14)
        cr.line_to(cx - size * 0.22, cy + size * 0.30)
        cr.close_path()
        cr.stroke()
        return

    if kind == "record":
        cr.arc(cx, cy, size * 0.25, 0, 6.2832)
        cr.fill()


def page_header(title, subtitle=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("page-header")

    title_label = Gtk.Label(label=title)
    title_label.set_halign(Gtk.Align.START)
    title_label.set_xalign(0)
    title_label.add_css_class("title-2")
    box.append(title_label)

    if subtitle:
        subtitle_label = Gtk.Label(label=subtitle)
        subtitle_label.set_halign(Gtk.Align.START)
        subtitle_label.set_xalign(0)
        subtitle_label.set_wrap(True)
        subtitle_label.add_css_class("dim-label")
        subtitle_label.add_css_class("page-subtitle")
        box.append(subtitle_label)

    return box


def icon_tile(icon_name, tone="accent", size=24):
    icon_size = max(size, 24)
    tile_size = max(44, icon_size + 18)

    tile = Gtk.DrawingArea()
    tile.set_content_width(tile_size)
    tile.set_content_height(tile_size)
    tile.set_size_request(tile_size, tile_size)
    tile.set_halign(Gtk.Align.CENTER)
    tile.set_valign(Gtk.Align.CENTER)
    tile.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    tile.add_css_class("icon-tile")
    if tone:
        tile.add_css_class(tone)
    tile.set_draw_func(_draw_icon, (icon_name, tone or "accent", icon_size))
    return tile


def git_status_icon(status):
    """Return icon and tone for short git status codes."""
    if status in ("A", "AM", "??"):
        return "list-add-symbolic", "success"
    if status == "D":
        return "edit-delete-symbolic", "error"
    if status in ("M", "MM"):
        return "document-edit-symbolic", "warning"
    if status in ("R", "C"):
        return "edit-copy-symbolic", "accent"
    return "document-edit-symbolic", "accent"


def action_button(label, icon_name=None, style=None):
    button = Gtk.Button()
    button.add_css_class("pill-button")
    if style:
        button.add_css_class(style)

    if icon_name:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(18)
        content.append(icon)
        content.append(Gtk.Label(label=label))
        button.set_child(content)
    else:
        button.set_label(label)

    return button


def action_bar():
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    box.set_halign(Gtk.Align.END)
    box.set_margin_top(18)
    box.add_css_class("action-bar")
    return box
