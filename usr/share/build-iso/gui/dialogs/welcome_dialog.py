#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/welcome_dialog.py - First-run welcome dialog
#

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import APP_DESCRIPTION, APP_NAME, APP_VERSION
from core.translation_utils import _
from gi.repository import Adw, Gtk


class WelcomeDialog(Adw.Window):
    """First-run welcome dialog with setup guidance"""

    def __init__(self, parent, settings):
        super().__init__(
            transient_for=parent,
            modal=True,
        )

        self.settings = settings

        self.set_title(_("Welcome"))
        self.set_default_size(500, 480)
        self.set_resizable(False)

        self._create_ui()

    def _create_ui(self):
        toolbar = Adw.ToolbarView()
        self.set_content(toolbar)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(32)
        content.set_margin_bottom(32)
        content.set_margin_start(32)
        content.set_margin_end(32)
        toolbar.set_content(content)

        # App icon
        icon = Gtk.Image.new_from_icon_name("media-optical-symbolic")
        icon.set_pixel_size(64)
        icon.set_halign(Gtk.Align.CENTER)
        content.append(icon)

        # Title
        title = Gtk.Label()
        title.set_markup(f"<b>{APP_NAME}</b>")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.CENTER)
        content.append(title)

        # Version
        version = Gtk.Label()
        version.set_text(f"v{APP_VERSION}")
        version.add_css_class("dim-label")
        version.set_halign(Gtk.Align.CENTER)
        content.append(version)

        # Description
        desc = Gtk.Label()
        desc.set_text(APP_DESCRIPTION)
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.CENTER)
        desc.set_margin_top(8)
        content.append(desc)

        # Requirements
        req_group = Adw.PreferencesGroup()
        req_group.set_title(_("Requirements"))
        req_group.set_margin_top(16)
        content.append(req_group)

        requirements = [
            ("system-run-symbolic", _("Docker or Podman installed")),
            ("drive-harddisk-symbolic", _("At least 20 GB free disk space")),
            ("network-wireless-symbolic", _("Internet connection for image download")),
        ]

        for icon_name, text in requirements:
            row = Adw.ActionRow()
            row.set_title(text)
            i = Gtk.Image.new_from_icon_name(icon_name)
            row.add_prefix(i)
            req_group.add(row)

        # Get Started button
        start_btn = Gtk.Button()
        start_btn.set_label(_("Get Started"))
        start_btn.add_css_class("suggested-action")
        start_btn.add_css_class("pill")
        start_btn.set_halign(Gtk.Align.CENTER)
        start_btn.set_size_request(200, -1)
        start_btn.set_margin_top(16)
        start_btn.connect("clicked", self._on_start_clicked)
        content.append(start_btn)

    def _on_start_clicked(self, button):
        self.settings.set("first_run", False)
        self.settings.save()
        self.close()


def should_show_welcome(settings) -> bool:
    """Check if welcome dialog should be shown"""
    return settings.get("first_run", True)
