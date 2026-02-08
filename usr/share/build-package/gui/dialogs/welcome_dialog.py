#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/welcome_dialog.py - Welcome dialog for first-time users
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.config import APP_NAME, APP_VERSION, APP_DESC


class WelcomeDialog(Adw.Window):
    """Welcome dialog shown on first run or when user requests"""
    
    __gsignals__ = {
        'closed': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # show_again
    }
    
    def __init__(self, parent, settings):
        super().__init__(
            transient_for=parent,
            modal=True
        )
        
        self.settings = settings
        
        self.set_title(_("Welcome"))
        self.set_default_size(600, 500)
        self.set_resizable(False)
        
        self.create_ui()
    
    def create_ui(self):
        """Create the welcome dialog UI"""
        
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header bar (minimal)
        header_bar = Adw.HeaderBar()
        header_bar.set_show_end_title_buttons(True)
        header_bar.set_show_start_title_buttons(False)
        main_box.append(header_bar)
        
        # Content with scroll
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        main_box.append(scrolled)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_top(32)
        content_box.set_margin_bottom(32)
        content_box.set_margin_start(48)
        content_box.set_margin_end(48)
        content_box.set_halign(Gtk.Align.CENTER)
        content_box.set_valign(Gtk.Align.START)
        scrolled.set_child(content_box)
        
        # App icon/logo
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        icon_box.set_halign(Gtk.Align.CENTER)
        
        app_icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        app_icon.set_pixel_size(80)
        app_icon.add_css_class("accent")
        icon_box.append(app_icon)
        
        content_box.append(icon_box)
        
        # Welcome title
        title_label = Gtk.Label()
        title_label.set_text(_("Welcome to {0}").format(APP_NAME))
        title_label.add_css_class("title-1")
        title_label.set_halign(Gtk.Align.CENTER)
        content_box.append(title_label)
        
        # Version
        version_label = Gtk.Label()
        version_label.set_text(_("Version {0}").format(APP_VERSION))
        version_label.add_css_class("dim-label")
        version_label.set_halign(Gtk.Align.CENTER)
        content_box.append(version_label)
        
        # Description
        desc_label = Gtk.Label()
        desc_label.set_text(APP_DESC)
        desc_label.add_css_class("body")
        desc_label.set_wrap(True)
        desc_label.set_justify(Gtk.Justification.CENTER)
        desc_label.set_halign(Gtk.Align.CENTER)
        desc_label.set_max_width_chars(60)
        content_box.append(desc_label)
        
        # Features section
        features_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        features_box.set_margin_top(16)
        
        features_title = Gtk.Label()
        features_title.set_text(_("Key Features"))
        features_title.add_css_class("title-4")
        features_title.set_halign(Gtk.Align.START)
        features_box.append(features_title)
        
        features = [
            ("document-save-symbolic", _("Commit and Push"), 
             _("Stage changes and push to your development branch with semantic commit messages")),
            ("package-x-generic-symbolic", _("Build Packages"), 
             _("Build and deploy packages to testing, stable, or extra repositories")),
            ("system-software-install-symbolic", _("AUR Packages"), 
             _("Build packages directly from the Arch User Repository")),
            ("git-branch-symbolic", _("Branch Management"), 
             _("Manage branches, create merge requests, and cleanup old branches")),
            ("preferences-system-symbolic", _("Advanced Operations"), 
             _("Cleanup GitHub Actions, tags, and revert commits")),
        ]
        
        for icon_name, title, description in features:
            feature_row = self._create_feature_row(icon_name, title, description)
            features_box.append(feature_row)
        
        content_box.append(features_box)
        
        # Tips section
        tips_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        tips_box.set_margin_top(16)
        
        tips_title = Gtk.Label()
        tips_title.set_text(_("Quick Tips"))
        tips_title.add_css_class("title-4")
        tips_title.set_halign(Gtk.Align.START)
        tips_box.append(tips_title)
        
        tips = [
            _("Use the sidebar to navigate between different operations"),
            _("The Overview page shows your current repository status"),
            _("Configure your preferences in Settings (Ctrl+,)"),
            _("Press Ctrl+Q to quit the application"),
        ]
        
        for tip in tips:
            tip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            bullet = Gtk.Label()
            bullet.set_text("•")
            bullet.add_css_class("accent")
            bullet.set_valign(Gtk.Align.START)
            tip_row.append(bullet)
            
            tip_label = Gtk.Label()
            tip_label.set_text(tip)
            tip_label.set_wrap(True)
            tip_label.set_xalign(0)
            tip_label.set_hexpand(True)
            tip_row.append(tip_label)
            
            tips_box.append(tip_row)
        
        content_box.append(tips_box)
        
        # Bottom section with checkbox and button
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        bottom_box.set_margin_top(24)
        main_box.append(bottom_box)
        
        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        bottom_box.append(separator)
        
        # Actions box
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions_box.set_margin_top(16)
        actions_box.set_margin_bottom(16)
        actions_box.set_margin_start(24)
        actions_box.set_margin_end(24)
        
        # Don't show again checkbox
        self.dont_show_check = Gtk.CheckButton()
        self.dont_show_check.set_label(_("Don't show this welcome screen again"))
        self.dont_show_check.set_hexpand(True)
        actions_box.append(self.dont_show_check)
        
        # Get started button
        start_button = Gtk.Button()
        start_button.set_label(_("Get Started"))
        start_button.add_css_class("suggested-action")
        start_button.add_css_class("pill")
        start_button.connect('clicked', self.on_start_clicked)
        actions_box.append(start_button)
        
        bottom_box.append(actions_box)
    
    def _create_feature_row(self, icon_name, title, description):
        """Create a feature row with icon, title, and description"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(8)
        row.set_margin_end(8)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        icon.add_css_class("accent")
        icon.set_valign(Gtk.Align.CENTER)
        row.append(icon)
        
        # Text box
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        
        title_label = Gtk.Label()
        title_label.set_text(title)
        title_label.add_css_class("heading")
        title_label.set_xalign(0)
        text_box.append(title_label)
        
        desc_label = Gtk.Label()
        desc_label.set_text(description)
        desc_label.add_css_class("dim-label")
        desc_label.set_wrap(True)
        desc_label.set_xalign(0)
        text_box.append(desc_label)
        
        row.append(text_box)
        
        return row
    
    def on_start_clicked(self, button):
        """Handle Get Started button click"""
        show_again = not self.dont_show_check.get_active()
        
        # Save preference
        self.settings.set("show_welcome", show_again)
        
        # Emit signal and close
        self.emit('closed', show_again)
        self.close()


def should_show_welcome(settings):
    """Check if welcome dialog should be shown"""
    return settings.get("show_welcome", True)
