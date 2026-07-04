#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/welcome_dialog.py - Welcome dialog for first-time users
#
# Polish pass: same content as before (hero, key features, quick tips, the
# "don't show again" choice and Get Started) re-laid-out with native libadwaita
# components — Adw.ToolbarView + Adw.StatusPage hero, an Adw.PreferencesGroup of
# features, and the tips folded into a collapsible row — so it reads as a clean,
# modern onboarding screen instead of a scroll wall.

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gdk
from core.translation_utils import _
from core.config import APP_VERSION, APP_DESC


# GTK4 has no CSS blur filter, so the "blur-ish" touches are a radial accent
# glow behind the hero icon and a soft horizontal vignette that fades the
# content into the left/right edges. Scoped to uniquely-named classes so they
# only affect this dialog.
_WELCOME_CSS = """
.welcome-hero-glow {
  padding: 16px;
  border-radius: 999px;
  background: radial-gradient(circle at center,
                              alpha(@accent_bg_color, 0.30) 0%,
                              transparent 70%);
}
.welcome-side-fade {
  background: linear-gradient(to right,
                              @window_bg_color 0%,
                              transparent 18%,
                              transparent 82%,
                              @window_bg_color 100%);
}
"""


class WelcomeDialog(Adw.Window):
    """Welcome dialog shown on first run or when user requests"""

    __gsignals__ = {
        'closed': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # show_again
    }

    def __init__(self, parent, settings):
        super().__init__(transient_for=parent, modal=True)
        self.settings = settings

        self.set_title(_("Welcome"))
        self.set_default_size(560, 660)
        self.set_resizable(False)

        self._install_css()
        self.create_ui()

    @staticmethod
    def _install_css():
        provider = Gtk.CssProvider()
        provider.load_from_string(_WELCOME_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def create_ui(self):
        """Create the welcome dialog UI."""
        view = Adw.ToolbarView()
        self.set_content(view)

        # Flat top bar — just the window controls, keeps focus on the hero.
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        view.add_top_bar(header)

        overlay = Gtk.Overlay()
        view.set_content(overlay)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        overlay.set_child(scrolled)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(460)
        clamp.set_margin_top(4)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(content)

        content.append(self._build_hero())
        content.append(self._build_features())
        content.append(self._build_tips())

        # Side vignette on top of the scrolled content (click-through).
        side_fade = Gtk.Box()
        side_fade.add_css_class("welcome-side-fade")
        side_fade.set_can_target(False)
        overlay.add_overlay(side_fade)

        view.add_bottom_bar(self._build_action_bar())

    def _build_hero(self):
        # Built by hand (instead of Adw.StatusPage) so the branded app icon
        # keeps its colors and the title/description don't get swallowed by
        # StatusPage's full-page vertical centering when embedded in a list.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(18)
        box.set_margin_bottom(4)

        # Themed "package" glyph tinted with the accent colour — evokes package
        # building without looking like a flat grey generic icon.
        icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        icon.set_pixel_size(88)
        icon.add_css_class("accent")

        # Soft accent glow behind the icon.
        glow = Gtk.Box()
        glow.add_css_class("welcome-hero-glow")
        glow.set_halign(Gtk.Align.CENTER)
        glow.set_valign(Gtk.Align.CENTER)
        glow.append(icon)
        box.append(glow)

        title = Gtk.Label(label="GitRepo")
        title.add_css_class("title-1")
        title.set_justify(Gtk.Justification.CENTER)
        title.set_wrap(True)
        box.append(title)

        version = Gtk.Label(label=_("Version {0}").format(APP_VERSION))
        version.add_css_class("dim-label")
        version.add_css_class("caption")
        box.append(version)

        description = Gtk.Label(label=APP_DESC)
        description.add_css_class("body")
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        description.set_max_width_chars(48)
        description.set_margin_top(4)
        box.append(description)
        return box

    def _build_features(self):
        group = Adw.PreferencesGroup()
        group.set_title(_("Key Features"))

        features = [
            ("document-save-symbolic", _("Commit and Push"),
             _("Stage changes and push to your development branch with semantic commit messages")),
            ("package-x-generic-symbolic", _("Build Packages"),
             _("Build and deploy packages to testing, stable, or extra repositories")),
            ("system-software-install-symbolic", _("AUR Packages"),
             _("Build packages directly from the Arch User Repository")),
            ("media-playlist-consecutive-symbolic", _("Branch Management"),
             _("Manage branches, create merge requests, and cleanup old branches")),
            ("preferences-system-symbolic", _("Advanced Operations"),
             _("Cleanup GitHub Actions, tags, and revert commits")),
        ]
        for icon_name, title, description in features:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(description)
            row.set_subtitle_lines(0)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.add_css_class("accent")
            row.add_prefix(icon)
            group.add(row)
        return group

    def _build_tips(self):
        group = Adw.PreferencesGroup()

        expander = Adw.ExpanderRow()
        expander.set_title(_("Quick Tips"))
        expander.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))

        tips = [
            _("Use the sidebar to navigate between different operations"),
            _("The Overview page shows your current repository status"),
            _("Configure your preferences in Settings (Ctrl+,)"),
            _("Press Ctrl+Q to quit the application"),
        ]
        for tip in tips:
            row = Adw.ActionRow()
            row.set_title(tip)
            row.set_title_lines(0)
            expander.add_row(row)

        group.add(expander)
        return group

    def _build_action_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_margin_top(10)
        bar.set_margin_bottom(10)
        bar.set_margin_start(14)
        bar.set_margin_end(14)

        self.dont_show_check = Gtk.CheckButton()
        self.dont_show_check.set_label(_("Don't show this welcome screen again"))
        self.dont_show_check.set_hexpand(True)
        self.dont_show_check.set_valign(Gtk.Align.CENTER)
        bar.append(self.dont_show_check)

        start_button = Gtk.Button()
        start_button.set_label(_("Get Started"))
        start_button.add_css_class("suggested-action")
        start_button.add_css_class("pill")
        start_button.connect('clicked', self.on_start_clicked)
        bar.append(start_button)
        return bar

    def on_start_clicked(self, button):
        """Handle Get Started button click"""
        show_again = not self.dont_show_check.get_active()
        self.settings.set("show_welcome", show_again)
        self.emit('closed', show_again)
        self.close()


def should_show_welcome(settings):
    """Check if welcome dialog should be shown"""
    return settings.get("show_welcome", True)
