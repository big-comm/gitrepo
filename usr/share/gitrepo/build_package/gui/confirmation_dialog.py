"""Accessible, structured confirmation dialog for GTK workflows."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango

from gitrepo.build_package.core.confirmation import (
    ConfirmationBlock,
    StructuredConfirmation,
    plain_confirmation_content,
)
from gitrepo.common.translation import _


def _wrapped_label(text: str, css_class: str | None = None, selectable: bool = False) -> Gtk.Label:
    is_rtl = Pango.find_base_dir(text, -1) == Pango.Direction.RTL
    label = Gtk.Label(label=text, xalign=1 if is_rtl else 0, yalign=0)
    label.set_hexpand(True)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
    label.set_justify(Gtk.Justification.RIGHT if is_rtl else Gtk.Justification.LEFT)
    label.set_width_chars(1)
    label.set_selectable(selectable)
    if css_class:
        label.add_css_class(css_class)
    return label


def _row(child: Gtk.Widget) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    row.set_selectable(False)
    row.set_child(child)
    return row


def _caption(text: str) -> Gtk.Label:
    label = _wrapped_label(text, "build-package-confirmation-label")
    label.add_css_class("caption")
    label.add_css_class("dim-label")
    label.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    return label


def _field_row(block: ConfirmationBlock) -> Gtk.ListBoxRow:
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    content.add_css_class("build-package-confirmation-row")
    content.append(_caption(block.label))

    headline, separator, body = block.value.partition("\n")
    value = _wrapped_label(headline, "build-package-confirmation-value", selectable=True)
    value.update_property([Gtk.AccessibleProperty.LABEL], [f"{block.label}: {headline}"])
    content.append(value)

    body = body.strip("\n")
    if separator and body.strip():
        body_label = _wrapped_label(body, "build-package-confirmation-multiline-value", selectable=True)
        body_label.update_property([Gtk.AccessibleProperty.LABEL], [body])
        content.append(body_label)
    return _row(content)


def _format_command(command: str) -> str:
    steps = [step.strip() for step in command.split("→")]
    return "\n".join(step for step in steps if step)


def _command_row(block: ConfirmationBlock) -> Gtk.ListBoxRow:
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    content.add_css_class("build-package-confirmation-row")
    if block.label:
        content.append(_caption(block.label))

    command = _wrapped_label(_format_command(block.value), "build-package-confirmation-command", selectable=True)
    accessible_text = f"{block.label}: {block.value}" if block.label else block.value
    command.update_property([Gtk.AccessibleProperty.LABEL], [accessible_text])
    content.append(command)
    return _row(content)


def _text_row(block: ConfirmationBlock) -> Gtk.ListBoxRow:
    label = _wrapped_label(block.value, selectable=True)
    label.add_css_class("dim-label")
    label.add_css_class("build-package-confirmation-row")
    return _row(label)


def _section_row(section: ConfirmationBlock | None, items: list[ConfirmationBlock]) -> Gtk.ListBoxRow:
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    content.add_css_class("build-package-confirmation-row")

    if section and section.label:
        title = _wrapped_label(section.label, "build-package-confirmation-section")
        title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        content.append(title)

    for item in items:
        item_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        item_row.set_accessible_role(Gtk.AccessibleRole.GROUP)

        icon = Gtk.Label(label="•")
        icon.set_valign(Gtk.Align.START)
        icon.add_css_class("build-package-confirmation-item-icon")
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        item_row.append(icon)

        value = _wrapped_label(item.value, "build-package-confirmation-item", selectable=True)
        item_row.append(value)
        content.append(item_row)

    return _row(content)


def confirmation_details(blocks: tuple[ConfirmationBlock, ...]) -> Gtk.ListBox:
    details = Gtk.ListBox()
    details.set_selection_mode(Gtk.SelectionMode.NONE)
    details.add_css_class("boxed-list")
    details.add_css_class("build-package-confirmation-list")

    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "field":
            details.append(_field_row(block))
        elif block.kind == "command":
            details.append(_command_row(block))
        elif block.kind == "section":
            items: list[ConfirmationBlock] = []
            while index + 1 < len(blocks) and blocks[index + 1].kind == "item":
                index += 1
                items.append(blocks[index])
            details.append(_section_row(block, items))
        elif block.kind == "item":
            items = [block]
            while index + 1 < len(blocks) and blocks[index + 1].kind == "item":
                index += 1
                items.append(blocks[index])
            details.append(_section_row(None, items))
        else:
            details.append(_text_row(block))
        index += 1

    return details


def _details_need_scrolling(blocks: tuple[ConfirmationBlock, ...]) -> bool:
    units = 0
    for block in blocks:
        value_lines = max(1, block.value.count("\n") + 1)
        if block.kind == "command":
            value_lines = max(value_lines, block.value.count("→") + 1)
            units += value_lines + bool(block.label)
        elif block.kind == "field":
            units += value_lines + 1
        else:
            units += value_lines
    return units > 10


def _dialog_content_height(blocks: tuple[ConfirmationBlock, ...]) -> int:
    if not blocks or _details_need_scrolling(blocks):
        return -1
    return 375 if len(blocks) >= 3 else 335


def _confirmation_content(question: str) -> tuple[Gtk.Widget, str, bool, int]:
    parsed = question.content if isinstance(question, StructuredConfirmation) else plain_confirmation_content(question)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    header.set_valign(Gtk.Align.START)

    icon = Gtk.Image.new_from_icon_name("dialog-question-symbolic")
    icon.set_pixel_size(24)
    icon.set_valign(Gtk.Align.START)
    icon.add_css_class("build-package-confirmation-header-icon")
    icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    header.append(icon)

    heading = _wrapped_label(parsed.heading, "title-3")
    heading.set_accessible_role(Gtk.AccessibleRole.HEADING)
    header.append(heading)
    content.append(header)

    if parsed.blocks:
        details = confirmation_details(parsed.blocks)
        if _details_need_scrolling(parsed.blocks):
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_max_content_height(420)
            scrolled.set_propagate_natural_height(True)
            scrolled.set_child(details)
            content.append(scrolled)
        else:
            content.append(details)

    return content, parsed.heading, bool(parsed.blocks), _dialog_content_height(parsed.blocks)


class ConfirmationDialog(Adw.AlertDialog):
    """Render plain confirmation text with clear visual hierarchy."""

    def __init__(self, question: str, default_yes: bool = True) -> None:
        super().__init__(heading="", body="")

        content, accessible_heading, has_details, content_height = _confirmation_content(question)
        self.set_extra_child(content)
        self.set_follows_content_size(False)
        self.set_content_width(760 if has_details else 480)
        self.set_content_height(content_height)
        self.update_property([Gtk.AccessibleProperty.LABEL], [accessible_heading])

        self.add_response("no", _("No"))
        self.add_response("yes", _("Yes"))
        self.set_close_response("no")
        self.set_default_response("yes" if default_yes else "no")
        if default_yes:
            self.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
