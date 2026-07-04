#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/ui_helpers.py - Shared GTK UI helpers
#

import math

import cairo
import gi

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
    "dialog-error-symbolic": "x",
    "dialog-warning-symbolic": "warning",
    "document-open-recent-symbolic": "clock",
    "drive-harddisk-symbolic": "drive",
    "emblem-ok-symbolic": "check",
    "emblem-synchronizing-symbolic": "sync",
    "folder-open-symbolic": "folder",
    "folder-remote-symbolic": "folder",
    "folder-symbolic": "folder",
    "go-next-symbolic": "right",
    "media-optical-symbolic": "disc",
    "network-wireless-symbolic": "network",
    "preferences-system-symbolic": "gear",
    "speedometer-symbolic": "gauge",
    "system-run-symbolic": "terminal",
    "view-refresh-symbolic": "sync",
}


def _rounded_rect(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
    cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
    cr.close_path()


def _set_icon_color(cr, tone):
    red, green, blue = _TONE_RGB.get(tone, _TONE_RGB["accent"])
    cr.set_source_rgb(red, green, blue)


def _stroke_arrow(cr, cx, cy, size):
    half = size * 0.28
    head = size * 0.20
    cr.move_to(cx - half, cy)
    cr.line_to(cx + half, cy)
    cr.move_to(cx + half - head, cy - head)
    cr.line_to(cx + half, cy)
    cr.line_to(cx + half - head, cy + head)
    cr.stroke()


def _draw_check(cr, cx, cy, size):
    cr.move_to(cx - size * 0.30, cy + size * 0.02)
    cr.line_to(cx - size * 0.08, cy + size * 0.24)
    cr.line_to(cx + size * 0.34, cy - size * 0.26)
    cr.stroke()


def _draw_icon(area, cr, width, height, data):
    icon_name, tone, requested_size = data
    kind = _ICON_KINDS.get(icon_name, "disc")
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

    if kind == "right":
        _stroke_arrow(cr, cx, cy, size)
        return

    if kind == "check":
        _draw_check(cr, cx, cy, size)
        return

    if kind == "x":
        arm = size * 0.25
        cr.move_to(cx - arm, cy - arm)
        cr.line_to(cx + arm, cy + arm)
        cr.move_to(cx + arm, cy - arm)
        cr.line_to(cx - arm, cy + arm)
        cr.stroke()
        return

    if kind == "disc":
        cr.arc(cx, cy, size * 0.32, 0, 6.2832)
        cr.stroke()
        cr.arc(cx, cy, size * 0.10, 0, 6.2832)
        cr.stroke()
        cr.move_to(cx + size * 0.12, cy - size * 0.08)
        cr.arc(cx, cy, size * 0.22, -0.55, 0.55)
        cr.stroke()
        return

    if kind == "drive":
        _rounded_rect(cr, cx - size * 0.32, cy - size * 0.22, size * 0.64, size * 0.44, 4)
        cr.stroke()
        cr.move_to(cx - size * 0.22, cy + size * 0.08)
        cr.line_to(cx + size * 0.14, cy + size * 0.08)
        cr.stroke()
        cr.arc(cx + size * 0.24, cy + size * 0.08, line_width * 0.45, 0, 6.2832)
        cr.fill()
        return

    if kind == "folder":
        _rounded_rect(cr, cx - size * 0.34, cy - size * 0.18, size * 0.68, size * 0.43, 3)
        cr.fill()
        cr.rectangle(cx - size * 0.34, cy - size * 0.28, size * 0.28, size * 0.18)
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

    if kind == "sync":
        radius = size * 0.27
        cr.arc(cx, cy, radius, 0.35, 4.4)
        cr.stroke()
        cr.move_to(cx + radius * 0.80, cy - radius * 0.55)
        cr.line_to(cx + radius * 1.18, cy - radius * 0.50)
        cr.line_to(cx + radius * 0.96, cy - radius * 0.18)
        cr.move_to(cx - radius * 0.80, cy + radius * 0.55)
        cr.line_to(cx - radius * 1.18, cy + radius * 0.50)
        cr.line_to(cx - radius * 0.96, cy + radius * 0.18)
        cr.stroke()
        return

    if kind == "gauge":
        cr.arc(cx, cy + size * 0.16, size * 0.34, 3.1416, 6.2832)
        cr.stroke()
        cr.move_to(cx, cy + size * 0.12)
        cr.line_to(cx + size * 0.20, cy - size * 0.12)
        cr.stroke()
        return

    if kind == "gear":
        cr.arc(cx, cy, size * 0.22, 0, 6.2832)
        cr.stroke()
        for index in range(8):
            angle = index * 0.7854
            inner = size * 0.30
            outer = size * 0.38
            cr.move_to(cx + inner * math.cos(angle), cy + inner * math.sin(angle))
            cr.line_to(cx + outer * math.cos(angle), cy + outer * math.sin(angle))
        cr.stroke()
        return

    if kind == "network":
        for radius in (0.34, 0.23, 0.12):
            cr.arc(cx, cy + size * 0.18, size * radius, 3.95, 5.47)
            cr.stroke()
        cr.arc(cx, cy + size * 0.24, line_width * 0.45, 0, 6.2832)
        cr.fill()


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


def row_arrow():
    arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
    arrow.set_valign(Gtk.Align.CENTER)
    arrow.add_css_class("row-arrow")
    return arrow


def action_button(label, icon_name=None, style=None):
    button = Gtk.Button()
    button.add_css_class("pill")
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
