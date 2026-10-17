"""Keep an unpublished commit draft with its repository.

When the window moves to another repository, the message and commit type typed
for the previous one are set aside and come back when the window returns to it,
so switching never discards text.
"""


def _type_rows(widget):
    """Every commit type row below *widget*, however deep the expander nests them."""
    child = widget.get_first_child()
    while child is not None:
        if hasattr(child, "commit_type"):
            yield child
        yield from _type_rows(child)
        child = child.get_next_sibling()


def capture_draft(form) -> dict | None:
    """Return the message and commit type typed in *form*, or None when it is empty."""
    buffer = form.message_textview.get_buffer()
    text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
    commit_type = getattr(form, "selected_commit_type", None)
    if not text.strip() and commit_type is None:
        return None
    return {"text": text, "commit_type": commit_type}


def restore_draft(form, draft: dict | None, empty_subtitle: str) -> None:
    """Put *draft* back in *form*, or leave the form empty when there is none."""
    draft = draft or {}
    form.message_textview.get_buffer().set_text(draft.get("text", ""))
    wanted = draft.get("commit_type")
    rows = list(_type_rows(form.commit_type_expander))
    row = next((row for row in rows if row.commit_type == wanted), None) if wanted else None
    if row is not None:
        form._select_commit_type_row(row)
        return
    for each in rows:
        if hasattr(each, "check_icon"):
            each.check_icon.set_visible(False)
    form.selected_commit_type = None
    form.selected_emoji = None
    form.commit_type_expander.set_subtitle(empty_subtitle)
