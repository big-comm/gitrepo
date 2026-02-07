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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        self.build_package = build_package
        self.selected_package_type = None
        self.commit_message = ""

        # Remover vexpand para evitar espaço vazio
        self.set_valign(Gtk.Align.START)

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        
        self.create_ui()
        self.refresh_status()
    
    def create_ui(self):
        """Create the widget UI"""
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        title_label = Gtk.Label()
        title_label.set_text(_("Generate Package"))
        title_label.add_css_class("title-4")
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
        
        # Package type selection with radio buttons style
        package_type_group = Adw.PreferencesGroup()
        package_type_group.set_title(_("Target Repository"))
        
        # Package types
        self.package_types = [
            ("testing", _("Testing"), _("Deploy to testing repo for beta users"), "system-software-update-symbolic"),
            ("stable", _("Stable"), _("Deploy to stable repo for all users"), "emblem-ok-symbolic"),
            ("extra", _("Extra"), _("Deploy to extra repo for additional packages"), "folder-new-symbolic")
        ]
        
        # Use a ListBox for selection
        self.package_types_list = Gtk.ListBox()
        self.package_types_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.package_types_list.add_css_class("boxed-list")
        self.package_types_list.connect('row-selected', self.on_package_type_selected)
        
        for pkg_type, title, description, icon_name in self.package_types:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(description)
            row.set_activatable(True)
            row.package_type = pkg_type
            
            # Add icon as prefix
            icon = Gtk.Image.new_from_icon_name(icon_name)
            row.add_prefix(icon)
            
            # Add checkmark (hidden by default)
            check_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            check_icon.set_visible(False)
            check_icon.add_css_class("success")
            row.check_icon = check_icon
            row.add_suffix(check_icon)
            
            self.package_types_list.append(row)
        
        package_type_group.add(self.package_types_list)
        self.append(package_type_group)
        
        # NOTE: seleção será feita após criar build_button em refresh_status
        
        # Commit message (conditional)
        self.commit_group = Adw.PreferencesGroup()
        self.commit_group.set_title(_("Commit Changes"))
        self.commit_group.set_description(_("Required when uncommitted changes are present"))
        
        # Get commit types from build_package
        self.commit_types = self.build_package.get_commit_types()
        self.selected_commit_type = None
        self.selected_emoji = None
        
        # Create expander row for commit types
        self.commit_type_expander = Adw.ExpanderRow()
        self.commit_type_expander.set_title(_("Commit Type"))
        self.commit_type_expander.set_subtitle(_("Select the type of change"))
        
        # Add commit type rows inside expander
        for idx, (emoji, commit_type, description) in enumerate(self.commit_types):
            type_row = Adw.ActionRow()
            type_row.set_title(f"{emoji} {commit_type}")
            type_row.set_subtitle(description)
            type_row.set_activatable(True)
            type_row.commit_type = commit_type
            type_row.emoji = emoji
            type_row.idx = idx
            
            # Add checkmark for selected
            check_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            check_icon.set_visible(False)
            type_row.check_icon = check_icon
            type_row.add_suffix(check_icon)
            
            type_row.connect('activated', self.on_commit_type_row_activated)
            self.commit_type_expander.add_row(type_row)
        
        self.commit_group.add(self.commit_type_expander)
        
        # Commit message - multiline support (same as commit_widget.py)
        # Label for description
        message_label = Gtk.Label()
        message_label.set_text(_("Commit Message (supports multiple lines)"))
        message_label.set_halign(Gtk.Align.START)
        message_label.add_css_class("dim-label")
        message_label.set_margin_start(6)
        message_label.set_margin_bottom(4)
        message_label.set_margin_top(6)
        
        # Frame for better visual separation
        message_frame = Gtk.Frame()
        message_frame.set_margin_start(6)
        message_frame.set_margin_end(6)
        
        # ScrolledWindow for multiline text
        message_scroll = Gtk.ScrolledWindow()
        message_scroll.set_min_content_height(80)
        message_scroll.set_max_content_height(120)
        message_scroll.set_vexpand(False)
        message_scroll.set_hexpand(True)
        
        # TextView for multiline commit message
        self.message_textview = Gtk.TextView()
        self.message_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.message_textview.set_left_margin(8)
        self.message_textview.set_right_margin(8)
        self.message_textview.set_top_margin(8)
        self.message_textview.set_bottom_margin(8)
        self.message_textview.get_buffer().connect('changed', self.on_commit_message_changed)
        message_scroll.set_child(self.message_textview)
        
        message_frame.set_child(message_scroll)
        
        # Add to group using a vertical box
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        message_box.append(message_label)
        message_box.append(message_frame)
        message_box.set_margin_bottom(6)
        
        self.append(self.commit_group)
        self.append(message_box)
        
        # Store reference for visibility control
        self.commit_message_box = message_box
        
        # Select first commit type by default
        self._select_first_commit_type()
        
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
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
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
        
        # Select testing by default (after all widgets created)
        first_row = self.package_types_list.get_row_at_index(0)
        if first_row:
            # Set package type without triggering update_build_button_state
            actual_row = first_row.get_child() if first_row.get_child() else first_row
            if hasattr(actual_row, 'package_type'):
                self.selected_package_type = actual_row.package_type
            if hasattr(actual_row, 'check_icon'):
                actual_row.check_icon.set_visible(True)
            self.package_types_list.select_row(first_row)
    
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
        
        # Clear previous state from changes_status_row
        self.changes_status_row.remove_css_class("warning")
        self.changes_status_row.remove_css_class("success")
        # Remove previous suffix icons (clear all Image suffixes)
        # Note: Adw.ActionRow doesn't have a clear_suffixes method,
        # so we track the suffix ourselves
        if hasattr(self, '_changes_suffix_icon') and self._changes_suffix_icon:
            self.changes_status_row.remove(self._changes_suffix_icon)
            self._changes_suffix_icon = None
        
        # Changes status
        has_changes = GitUtils.has_changes()
        if has_changes:
            self.changes_status_row.set_subtitle(_("Uncommitted changes present"))
            self._changes_suffix_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            self.changes_status_row.add_suffix(self._changes_suffix_icon)
            self.changes_status_row.add_css_class("warning")
            self.commit_group.set_visible(True)
            self.commit_message_box.set_visible(True)
        else:
            self.changes_status_row.set_subtitle(_("Working directory clean"))
            self._changes_suffix_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            self.changes_status_row.add_suffix(self._changes_suffix_icon)
            self.changes_status_row.add_css_class("success")
            self.commit_group.set_visible(False)
            self.commit_message_box.set_visible(False)
        
        self.update_build_button_state()
    
    def on_package_type_selected(self, list_box, row):
        """Handle package type selection"""
        # Hide all checkmarks first
        for i in range(3):  # 3 package types
            child_row = self.package_types_list.get_row_at_index(i)
            if child_row and hasattr(child_row.get_child(), 'check_icon'):
                child_row.get_child().check_icon.set_visible(False)
            elif child_row:
                # Get the actual row from ListBoxRow
                actual_row = child_row.get_child() if child_row.get_child() else child_row
                if hasattr(actual_row, 'check_icon'):
                    actual_row.check_icon.set_visible(False)
        
        if row:
            # Show checkmark on selected
            actual_row = row.get_child() if hasattr(row, 'get_child') and row.get_child() else row
            if hasattr(actual_row, 'check_icon'):
                actual_row.check_icon.set_visible(True)
            if hasattr(actual_row, 'package_type'):
                self.selected_package_type = actual_row.package_type
            elif hasattr(row, 'package_type'):
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
    
    def on_commit_message_changed(self, buffer):
        """Handle commit message changes"""
        # Get text from TextView buffer
        start, end = buffer.get_bounds()
        self.commit_message = buffer.get_text(start, end, False).strip()
        self.update_build_button_state()
    
    def _select_first_commit_type(self):
        """Select first commit type by default"""
        if len(self.commit_types) > 0:
            # Find and select first row in expander
            first_row = None
            child = self.commit_type_expander.get_first_child()
            while child:
                if hasattr(child, 'commit_type'):
                    first_row = child
                    break
                child = child.get_next_sibling()
            
            if first_row:
                self._select_commit_type_row(first_row)
    
    def on_commit_type_row_activated(self, row):
        """Handle commit type row activation"""
        self._select_commit_type_row(row)
    
    def _select_commit_type_row(self, row):
        """Select a commit type row and update visuals"""
        # Hide all checkmarks first
        child = self.commit_type_expander.get_first_child()
        while child:
            if hasattr(child, 'check_icon'):
                child.check_icon.set_visible(False)
            child = child.get_next_sibling()
        
        # Show checkmark on selected
        if hasattr(row, 'check_icon'):
            row.check_icon.set_visible(True)
        
        # Update selected values
        self.selected_commit_type = row.commit_type
        self.selected_emoji = row.emoji
        
        # Update expander subtitle to show selection
        self.commit_type_expander.set_subtitle(f"{row.emoji} {row.commit_type}")
        
        # Collapse expander after selection
        self.commit_type_expander.set_expanded(False)
        
        self.update_build_button_state()
    
    def update_build_button_state(self):
        """Update build button sensitivity"""
        # Check if package type is selected
        has_package_type = self.selected_package_type is not None
        
        # Check if commit message and type are provided when needed
        has_changes = GitUtils.has_changes()
        has_commit_msg = bool(self.commit_message) if has_changes else True
        has_commit_type = (self.selected_commit_type is not None) if has_changes else True
        
        # Check if package name is valid
        package_name = GitUtils.get_package_name()
        has_valid_package = not package_name.startswith("error")
        
        self.build_button.set_sensitive(
            has_package_type and has_commit_msg and has_commit_type and has_valid_package
        )
    
    def on_reset_clicked(self, button):
        """Handle reset button click"""
        # Clear selections
        self.package_types_list.unselect_all()
        self.selected_package_type = None
        
        # Reset commit type selection
        self._select_first_commit_type()
        
        # Clear commit message
        self.message_textview.get_buffer().set_text("")
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
            # Format commit message with type (support multiline)
            if self.selected_commit_type == "custom":
                formatted_message = self.commit_message
            else:
                # For multiline messages, put type on first line
                if '\n' in self.commit_message:
                    lines = self.commit_message.split('\n', 1)
                    formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {lines[0]}\n\n{lines[1]}"
                else:
                    formatted_message = f"{self.selected_emoji} {self.selected_commit_type}: {self.commit_message}"
            
            # Need to commit first, then build
            self.emit('commit-and-build-requested', 
                     self.selected_package_type, 
                     formatted_message, 
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
        print(_("Building {0} package with TMATE: {1}").format(package_type_name, tmate_enabled))
    
    def show_build_summary(self, package_name, package_type, working_branch):
        """Show build summary before execution"""
        # This could open a summary dialog
        # For now, just update the UI to show what will be built
        summary_text = _("Ready to build {0} package '{1}' from branch '{2}'").format(
            package_type, package_name, working_branch
        )
        
        print(_("Build Summary: {0}").format(summary_text))