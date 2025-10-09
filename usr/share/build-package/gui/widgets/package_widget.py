#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/package_widget.py - Package generation widget for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.git_utils import GitUtils

class PackageTypeRow(Adw.ActionRow):
    """Custom row for package type selection"""
    
    __gtype_name__ = 'PackageTypeRow'
    
    def __init__(self, package_type, title, description, icon_name):
        super().__init__()
        
        self.package_type = package_type
        
        self.set_title(title)
        self.set_subtitle(description)
        self.set_activatable(True)
        
        # Add icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        self.add_prefix(icon)
        
        # Add arrow
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        self.add_suffix(arrow)

class PackageWidget(Gtk.Box):
    """Widget for package generation operations"""
    
    __gsignals__ = {
        'package-build-requested': (GObject.SignalFlags.RUN_FIRST, None, (str, bool, bool)),  # type, tmate, has_commit_msg
        'commit-and-build-requested': (GObject.SignalFlags.RUN_FIRST, None, (str, str, bool)),  # type, commit_msg, tmate
    }
    
    def __init__(self, build_package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        self.build_package = build_package
        self.selected_package_type = None
        self.commit_message = ""
        
        self.set_vexpand(True)
        self.set_valign(Gtk.Align.FILL)
        
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        self.create_ui()
        self.refresh_status()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Generate Package"))
        title_label.add_css_class("title-2")
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_text(_("Build and deploy packages to repositories"))
        subtitle_label.add_css_class("subtitle")
        header_box.append(subtitle_label)
        
        self.append(header_box)
        
        # Repository status
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("Repository Status"))
        
        self.package_name_row = Adw.ActionRow()
        self.package_name_row.set_title(_("Package Name"))
        status_group.add(self.package_name_row)
        
        self.working_branch_row = Adw.ActionRow()
        self.working_branch_row.set_title(_("Working Branch"))
        status_group.add(self.working_branch_row)
        
        self.changes_status_row = Adw.ActionRow()
        self.changes_status_row.set_title(_("Changes Status"))
        status_group.add(self.changes_status_row)
        
        self.append(status_group)
        
        # Package type selection
        package_type_group = Adw.PreferencesGroup()
        package_type_group.set_title(_("Package Type"))
        package_type_group.set_description(_("Select the repository type for package deployment"))
        
        self.package_types_list = Gtk.ListBox()
        self.package_types_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.package_types_list.add_css_class("boxed-list")
        self.package_types_list.connect('row-selected', self.on_package_type_selected)
        
        # Add package types
        package_types = [
            ("testing", _("Testing Repository"), _("Deploy to testing repo for beta users"), "applications-debugging-symbolic"),
            ("stable", _("Stable Repository"), _("Deploy to stable repo for all users"), "emblem-ok-symbolic"),
            ("extra", _("Extra Repository"), _("Deploy to extra repo for additional packages"), "folder-symbolic")
        ]
        
        for pkg_type, title, description, icon in package_types:
            row = PackageTypeRow(pkg_type, title, description, icon)
            self.package_types_list.append(row)
        
        package_type_group.add(self.package_types_list)
        self.append(package_type_group)
        
        # Commit message (conditional)
        self.commit_group = Adw.PreferencesGroup()
        self.commit_group.set_title(_("Commit Changes"))
        self.commit_group.set_description(_("Required when uncommitted changes are present"))
        
        self.commit_message_entry = Adw.EntryRow()
        self.commit_message_entry.set_title(_("Commit Message"))
        self.commit_message_entry.connect('changed', self.on_commit_message_changed)
        self.commit_group.add(self.commit_message_entry)
        
        self.append(self.commit_group)
        
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
        
        self.workflow_row = Adw.ActionRow()
        self.workflow_row.set_title(_("Workflow Repository"))
        self.workflow_row.set_subtitle(self.build_package.repo_workflow)
        self.summary_group.add(self.workflow_row)
        
        self.append(self.summary_group)
        
        # Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(12)
        
        # Cancel/Reset button
        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Reset"))
        cancel_button.connect('clicked', self.on_reset_clicked)
        actions_box.append(cancel_button)
        
        # Build button
        self.build_button = Gtk.Button()
        self.build_button.set_label(_("Build Package"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.connect('clicked', self.on_build_clicked)
        self.build_button.set_sensitive(False)
        actions_box.append(self.build_button)
        
        self.append(actions_box)
    
    def refresh_status(self):
        """Refresh package and repository status"""
        # Package name
        package_name = GitUtils.get_package_name()
        if package_name.startswith("error"):
            self.package_name_row.set_subtitle(_("Error: PKGBUILD not found"))
            self.package_name_row.add_css_class("error")
        else:
            self.package_name_row.set_subtitle(package_name)
            self.package_name_row.remove_css_class("error")
        
        # Working branch
        current_branch = GitUtils.get_current_branch()
        if current_branch:
            self.working_branch_row.set_subtitle(current_branch)
        else:
            self.working_branch_row.set_subtitle(_("Unknown"))
        
        # Changes status
        has_changes = GitUtils.has_changes()
        if has_changes:
            self.changes_status_row.set_subtitle(_("Uncommitted changes present"))
            self.changes_status_row.add_suffix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            self.changes_status_row.add_css_class("warning")
            self.commit_group.set_visible(True)
        else:
            self.changes_status_row.set_subtitle(_("Working directory clean"))
            self.changes_status_row.add_suffix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
            self.changes_status_row.remove_css_class("warning")
            self.changes_status_row.add_css_class("success")
            self.commit_group.set_visible(False)
        
        self.update_build_button_state()
    
    def on_package_type_selected(self, list_box, row):
        """Handle package type selection"""
        if row:
            self.selected_package_type = row.package_type
            self.update_build_button_state()
            
            # Update build button text
            type_names = {
                "testing": _("Build Testing Package"),
                "stable": _("Build Stable Package"),
                "extra": _("Build Extra Package")
            }
            
            if self.selected_package_type in type_names:
                self.build_button.set_label(type_names[self.selected_package_type])
    
    def on_commit_message_changed(self, entry):
        """Handle commit message changes"""
        self.commit_message = entry.get_text().strip()
        self.update_build_button_state()
    
    def update_build_button_state(self):
        """Update build button sensitivity"""
        # Check if package type is selected
        has_package_type = self.selected_package_type is not None
        
        # Check if commit message is provided when needed
        has_changes = GitUtils.has_changes()
        has_commit_msg = bool(self.commit_message) if has_changes else True
        
        # Check if package name is valid
        package_name = GitUtils.get_package_name()
        has_valid_package = not package_name.startswith("error")
        
        self.build_button.set_sensitive(
            has_package_type and has_commit_msg and has_valid_package
        )
    
    def on_reset_clicked(self, button):
        """Handle reset button click"""
        # Clear selections
        self.package_types_list.unselect_all()
        self.selected_package_type = None
        
        # Clear commit message
        self.commit_message_entry.set_text("")
        self.commit_message = ""
        
        # Reset TMATE option
        self.tmate_row.set_active(False)
        
        # Reset build button
        self.build_button.set_label(_("Build Package"))
        self.update_build_button_state()
    
    def on_build_clicked(self, button):
        """Handle build button click"""
        if not self.selected_package_type:
            return
        
        tmate_enabled = self.tmate_row.get_active()
        has_changes = GitUtils.has_changes()
        
        if has_changes and self.commit_message:
            # Need to commit first, then build
            self.emit('commit-and-build-requested', 
                     self.selected_package_type, 
                     self.commit_message, 
                     tmate_enabled)
        else:
            # Direct build (no uncommitted changes)
            self.emit('package-build-requested', 
                     self.selected_package_type, 
                     tmate_enabled, 
                     bool(self.commit_message))
        
        # Show confirmation
        type_text = {
            "testing": _("Testing"),
            "stable": _("Stable"),
            "extra": _("Extra")
        }
        
        package_type_name = type_text.get(self.selected_package_type, self.selected_package_type)
        
        # You could show a toast or confirmation dialog here
        print(f"Building {package_type_name} package with TMATE: {tmate_enabled}")
    
    def show_build_summary(self, package_name, package_type, working_branch):
        """Show build summary before execution"""
        # This could open a summary dialog
        # For now, just update the UI to show what will be built
        summary_text = _("Ready to build {0} package '{1}' from branch '{2}'").format(
            package_type, package_name, working_branch
        )
        
        print(f"Build Summary: {summary_text}")