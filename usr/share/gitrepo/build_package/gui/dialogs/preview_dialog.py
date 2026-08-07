#
# gui/dialogs/preview_dialog.py - Visual operation preview dialog
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GObject
from gitrepo.common.translation import _


class PreviewOperationRow(Adw.ActionRow):
    """Row for a single operation in preview"""

    __gtype_name__ = "PreviewOperationRow"

    def __init__(self, index, total, description, commands=None, destructive=False):
        super().__init__()

        self.index = index
        self.description = description
        self.commands = commands or []
        self.destructive = destructive

        # Set title with number
        self.set_title(_("[{0}/{1}] {2}").format(index, total, description))

        # Icon prefix
        icon_name = "dialog-warning-symbolic" if destructive else "emblem-ok-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        if destructive:
            icon.add_css_class("error")
        else:
            icon.add_css_class("success")
        self.add_prefix(icon)

        # If has commands, show as subtitle
        if commands:
            cmd_text = "\n".join(f"$ {cmd}" for cmd in commands[:3])  # Show first 3
            if len(commands) > 3:
                cmd_text += f"\n... (+{len(commands) - 3} more)"
            self.set_subtitle(cmd_text)
            self.set_subtitle_selectable(True)

        # Add destructive styling if needed
        if destructive:
            self.add_css_class("error")


class PreviewDialog(Adw.MessageDialog):
    """Visual dialog for previewing operations before execution"""

    __gsignals__ = {
        "preview-accepted": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "preview-rejected": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, parent, operations, dry_run=False):
        super().__init__(transient_for=parent, modal=True)

        self.operations = operations
        self.dry_run = dry_run

        # Count destructive operations
        self.destructive_count = sum(1 for op in operations if op.get("destructive", False))
        self.safe_count = len(operations) - self.destructive_count

        # Set title and message
        if dry_run:
            self.set_heading(_("🔍 Dry-Run Mode"))
            self.set_body(_("Simulating operations (nothing will be executed):"))
        else:
            self.set_heading(_("Operation Preview"))
            self.set_body(_("The following operations will be executed:"))

        self.create_ui()

    def create_ui(self):
        """Create preview UI"""

        # Create a box for the operations list
        operations_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        operations_box.set_margin_top(12)
        operations_box.set_margin_bottom(12)
        operations_box.set_margin_start(12)
        operations_box.set_margin_end(12)

        # Scrolled window for operations
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(400)
        scrolled.set_propagate_natural_height(True)

        # List box for operations
        operations_list = Gtk.ListBox()
        operations_list.set_selection_mode(Gtk.SelectionMode.NONE)
        operations_list.add_css_class("boxed-list")

        # Add operation rows
        total = len(self.operations)
        for i, op in enumerate(self.operations, 1):
            row = PreviewOperationRow(
                index=i,
                total=total,
                description=op.get("description", ""),
                commands=op.get("commands", []),
                destructive=op.get("destructive", False),
            )
            operations_list.append(row)

        scrolled.set_child(operations_list)
        operations_box.append(scrolled)

        # Summary label
        summary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        summary_box.set_halign(Gtk.Align.CENTER)
        summary_box.set_margin_top(6)

        # Safe operations label
        if self.safe_count > 0:
            safe_label = Gtk.Label()
            safe_label.set_text(_("✓ {0} safe operations").format(self.safe_count))
            safe_label.add_css_class("success")
            summary_box.append(safe_label)

        # Destructive operations label
        if self.destructive_count > 0:
            destructive_label = Gtk.Label()
            destructive_label.set_text(_("⚠ {0} destructive operations").format(self.destructive_count))
            destructive_label.add_css_class("error")
            summary_box.append(destructive_label)

        operations_box.append(summary_box)

        # Note: Adw.MessageDialog doesn't directly support adding widgets
        # We'll use the extra_child property if available, or modify approach
        # For now, we'll add the content in a different way

        # Set button labels and responses
        if self.dry_run:
            self.add_response("close", _("Close"))
            self.set_response_appearance("close", Adw.ResponseAppearance.DEFAULT)
            self.set_default_response("close")
        else:
            self.add_response("cancel", _("Cancel"))
            self.add_response("proceed", _("Proceed"))

            if self.destructive_count > 0:
                self.set_response_appearance("proceed", Adw.ResponseAppearance.DESTRUCTIVE)
            else:
                self.set_response_appearance("proceed", Adw.ResponseAppearance.SUGGESTED)

            self.set_default_response("proceed")
            self.set_close_response("cancel")

        # Connect response signal
        self.connect("response", self.on_response)

        # Try to set extra child (if supported in this GTK version)
        try:
            self.set_extra_child(operations_box)
        except AttributeError:
            # Fallback: just show operations in body text
            ops_text = "\n".join(
                f"[{i}/{total}] {op.get('description', '')}" for i, op in enumerate(self.operations, 1)
            )
            self.set_body(self.get_body() + "\n\n" + ops_text)

    def on_response(self, dialog, response_id):
        """Handle dialog response"""
        if response_id == "proceed":
            self.emit("preview-accepted")
        elif response_id in ("cancel", "close"):
            self.emit("preview-rejected")
