#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/aur_widget.py - AUR package widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _

class AURWidget(Gtk.Box):
    """Widget for AUR package building operations"""
    
    __gsignals__ = {
        'aur-build-requested': (GObject.SignalFlags.RUN_FIRST, None, (str, bool)),  # package_name, tmate
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        self.build_package = build_package
        self.package_name = ""

        # Remover vexpand para evitar espaço vazio
        self.set_valign(Gtk.Align.START)

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        
        self.create_ui()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("AUR Package Builder"))
        title_label.add_css_class("title-4")
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_text(_("Build packages from Arch User Repository"))
        subtitle_label.add_css_class("subtitle")
        header_box.append(subtitle_label)
        
        self.append(header_box)
        
        # Info banner
        info_banner = Adw.Banner()
        info_banner.set_title(_("AUR packages are built from community-maintained sources"))
        info_banner.set_button_label(_("Learn More"))
        info_banner.connect('button-clicked', self.on_info_banner_clicked)
        self.append(info_banner)
        
        # Package input
        package_group = Adw.PreferencesGroup()
        package_group.set_title(_("Package Information"))
        package_group.set_description(_("Enter the AUR package name to build"))
        
        self.package_entry = Adw.EntryRow()
        self.package_entry.set_title(_("AUR Package Name"))
        self.package_entry.set_text("")
        self.package_entry.connect('changed', self.on_package_name_changed)
        self.package_entry.connect('activate', self.on_build_clicked)
        package_group.add(self.package_entry)
        
        # Package URL preview
        self.url_row = Adw.ActionRow()
        self.url_row.set_title(_("AUR URL"))
        self.url_row.set_activatable(True)
        self.url_row.connect('activated', self.on_url_clicked)
        package_group.add(self.url_row)
        
        self.append(package_group)
        
        # Build options
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("Build Options"))
        
        self.tmate_row = Adw.SwitchRow()
        self.tmate_row.set_title(_("Enable TMATE Debug"))
        self.tmate_row.set_subtitle(_("Enable terminal access for debugging build issues"))
        options_group.add(self.tmate_row)
        
        self.append(options_group)
        
        # Build summary
        self.summary_group = Adw.PreferencesGroup()
        self.summary_group.set_title(_("Build Summary"))
        
        self.organization_row = Adw.ActionRow()
        self.organization_row.set_title(_("Organization"))
        self.organization_row.set_subtitle(self.build_package.organization)
        self.summary_group.add(self.organization_row)
        
        self.timestamp_row = Adw.ActionRow()
        self.timestamp_row.set_title(_("Branch Timestamp"))
        self.timestamp_row.set_subtitle(_("Will be generated automatically"))
        self.summary_group.add(self.timestamp_row)
        
        self.append(self.summary_group)
        
        # # Spacer to push actions to the bottom
        # spacer = Gtk.Box()
        # spacer.set_vexpand(True)
        # self.append(spacer)
        
        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)
        
        # Clear button
        clear_button = Gtk.Button()
        clear_button.set_label(_("Clear"))
        clear_button.connect('clicked', self.on_clear_clicked)
        actions_box.append(clear_button)
        
        # Build button
        self.build_button = Gtk.Button()
        self.build_button.set_label(_("Build AUR Package"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.connect('clicked', self.on_build_clicked)
        self.build_button.set_sensitive(False)
        actions_box.append(self.build_button)
        
        self.append(actions_box)
        
        # Initialize
        self.update_url_display()
    
    def set_package_name(self, name):
        """Set package name from quick access"""
        # Remove common prefixes that users might add
        clean_name = name.replace("aur-", "").replace("aur/", "")
        self.package_entry.set_text(clean_name)
    
    def on_package_name_changed(self, entry):
        """Handle package name changes"""
        text = entry.get_text().strip()
        
        # Clean the package name
        clean_name = text.replace("aur-", "").replace("aur/", "")
        if clean_name != text:
            entry.set_text(clean_name)
            return
        
        self.package_name = clean_name
        self.update_url_display()
        self.update_build_button_state()
    
    def update_url_display(self):
        """Update the AUR URL display"""
        if self.package_name:
            url = f"https://aur.archlinux.org/{self.package_name}.git"
            self.url_row.set_subtitle(url)
            self.url_row.set_sensitive(True)
        else:
            self.url_row.set_subtitle(_("Enter package name above"))
            self.url_row.set_sensitive(False)
    
    def update_build_button_state(self):
        """Update build button sensitivity"""
        self.build_button.set_sensitive(bool(self.package_name))
    
    def on_info_banner_clicked(self, banner):
        """Handle info banner click"""
        # Open AUR website
        try:
            import webbrowser
            webbrowser.open("https://aur.archlinux.org/")
        except:
            pass
    
    def on_url_clicked(self, row):
        """Handle URL row click to open in browser"""
        if self.package_name:
            try:
                import webbrowser
                url = f"https://aur.archlinux.org/packages/{self.package_name}/"
                webbrowser.open(url)
            except:
                pass
    
    def on_clear_clicked(self, button):
        """Handle clear button click"""
        self.package_entry.set_text("")
        self.package_name = ""
        self.tmate_row.set_active(False)
        self.update_url_display()
        self.update_build_button_state()
    
    def on_build_clicked(self, widget):
        """Handle build button click"""
        if not self.package_name:
            return
        
        tmate_enabled = self.tmate_row.get_active()
        
        # Show confirmation with package details
        self.show_build_confirmation(self.package_name, tmate_enabled)
    
    def show_build_confirmation(self, package_name, tmate_enabled):
        """Show build confirmation dialog"""
        from datetime import datetime
        
        # Generate timestamp for branch name
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
        branch_name = f"aur-{timestamp}"
        
        # Update timestamp display
        self.timestamp_row.set_subtitle(branch_name)
        
        # Create confirmation dialog with better formatting
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Confirm AUR Build"),
            ""
        )
        
        # Create custom content box for better layout
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(6)
        content_box.set_margin_bottom(6)
        content_box.set_size_request(450, -1)  # Force minimum width
        
        # Package name header
        pkg_label = Gtk.Label()
        pkg_label.set_markup(_("<b>Package:</b> {0}").format(package_name))
        pkg_label.set_halign(Gtk.Align.START)
        content_box.append(pkg_label)
        
        # Separator
        separator = Gtk.Separator()
        content_box.append(separator)
        
        # Details section
        details_label = Gtk.Label()
        details_label.set_text(_("This will:"))
        details_label.set_halign(Gtk.Align.START)
        details_label.add_css_class("dim-label")
        content_box.append(details_label)
        
        # Action items
        actions = [
            _("• Create branch: {0}").format(branch_name),
            _("• Download from: https://aur.archlinux.org/{0}.git").format(package_name),
            _("• Build package in BigCommunity infrastructure")
        ]
        
        for action in actions:
            action_label = Gtk.Label()
            action_label.set_text(action)
            action_label.set_halign(Gtk.Align.START)
            action_label.set_wrap(True)
            action_label.set_xalign(0)
            content_box.append(action_label)
        
        dialog.set_extra_child(content_box)
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("build", _("Build Package"))
        dialog.set_response_appearance("build", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("build")
        
        def on_response(dialog, response):
            if response == "build":
                self.emit('aur-build-requested', package_name, tmate_enabled)
                # Clear form after successful build request
                self.on_clear_clicked(None)
            dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()