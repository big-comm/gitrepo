#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/gtk_logger.py - Logger that routes messages to GUI terminal widget
#

import gi

gi.require_version('Gtk', '4.0')

from gi.repository import GLib, Gtk


class GTKLogger:
    """Logger that routes messages to a GTK TextView terminal widget"""

    COLOR_MAP = {
        "cyan": "#00CED1",
        "green": "#32CD32",
        "red": "#FF6B6B",
        "yellow": "#FFD93D",
        "white": "#FFFFFF",
        "dim": "#888888",
        "blue": "#4A90D9",
        "purple": "#B19CD9",
        "orange": "#FFA500",
    }

    def __init__(self):
        self._text_view = None
        self._buffer = None
        self._tags_initialized = False
        self._log_history = []

    def set_text_view(self, text_view: Gtk.TextView):
        """Attach a TextView widget for log output"""
        self._text_view = text_view
        self._buffer = text_view.get_buffer()
        self._tags_initialized = False
        self._setup_tags()

        # Replay history
        for color, msg in self._log_history:
            self._append(color, msg)

    def _setup_tags(self):
        if not self._buffer:
            return
        tag_table = self._buffer.get_tag_table()
        for name, color in self.COLOR_MAP.items():
            if not tag_table.lookup(name):
                tag = Gtk.TextTag.new(name)
                tag.set_property("foreground", color)
                tag_table.add(tag)
        bold_tag = Gtk.TextTag.new("bold")
        if not tag_table.lookup("bold"):
            bold_tag.set_property("weight", 700)
            tag_table.add(bold_tag)
        self._tags_initialized = True

    def log(self, color: str, message: str):
        """Log a message with color (thread-safe)"""
        self._log_history.append((color, message))
        if self._buffer:
            GLib.idle_add(self._append, color, message)

    def _append(self, color: str, message: str):
        if not self._buffer:
            return False
        if not self._tags_initialized:
            self._setup_tags()

        end_iter = self._buffer.get_end_iter()
        tag_name = color if color in self.COLOR_MAP else None

        if tag_name and self._buffer.get_tag_table().lookup(tag_name):
            start_mark = self._buffer.create_mark(None, end_iter, True)
            self._buffer.insert(end_iter, message + "\n")
            start_iter = self._buffer.get_iter_at_mark(start_mark)
            end_iter = self._buffer.get_end_iter()
            self._buffer.apply_tag_by_name(tag_name, start_iter, end_iter)
            self._buffer.delete_mark(start_mark)
        else:
            self._buffer.insert(end_iter, message + "\n")

        # Auto-scroll
        if self._text_view:
            end_iter = self._buffer.get_end_iter()
            self._text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)
        return False

    def clear(self):
        """Clear the log"""
        self._log_history.clear()
        if self._buffer:
            GLib.idle_add(self._buffer.set_text, "")
