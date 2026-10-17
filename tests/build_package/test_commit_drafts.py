"""A commit draft set aside for one repository comes back intact, and never leaks into another."""

import pytest


@pytest.fixture
def gtk(build_package_modules):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    if not Gtk.init_check():
        pytest.skip("no display for GTK widgets")
    return Adw, Gtk


def _form(Adw, Gtk):
    class Form:
        def __init__(self):
            self.message_textview = Gtk.TextView()
            self.commit_type_expander = Adw.ExpanderRow()
            self.selected_commit_type = None
            self.selected_emoji = None
            for emoji, commit_type in (("✨", "feat"), ("🐛", "fix")):
                row = Adw.ActionRow()
                row.commit_type, row.emoji = commit_type, emoji
                row.check_icon = Gtk.Image()
                self.commit_type_expander.add_row(row)

        def _select_commit_type_row(self, row):
            self.selected_commit_type, self.selected_emoji = row.commit_type, row.emoji
            row.check_icon.set_visible(True)

    return Form()


def _text(form):
    buffer = form.message_textview.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def test_a_draft_round_trips_and_an_empty_one_clears_the_form(gtk):
    from gitrepo.build_package.gui.drafts import capture_draft, restore_draft

    Adw, Gtk = gtk
    form = _form(Adw, Gtk)
    assert capture_draft(form) is None

    form.message_textview.get_buffer().set_text("line one\nline two")
    form.selected_commit_type = "fix"
    draft = capture_draft(form)

    restore_draft(form, None, "pick a type")
    assert _text(form) == "" and form.selected_commit_type is None
    assert form.commit_type_expander.get_subtitle() == "pick a type"

    restore_draft(form, draft, "pick a type")
    assert _text(form) == "line one\nline two" and form.selected_commit_type == "fix"
