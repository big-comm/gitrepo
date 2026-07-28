from types import SimpleNamespace

from gitrepo.build_package.gui.dialogs.progress_dialog import OperationRunner, ProgressDialog


def test_acknowledged_progress_failure_does_not_open_a_second_dialog() -> None:
    calls = []
    parent = SimpleNamespace(
        is_active=lambda: True,
        show_error_dialog=lambda message: calls.append(message),
    )
    runner = OperationRunner.__new__(OperationRunner)
    runner.parent = parent

    runner._on_operation_error("failed")

    assert calls == []


def test_intermediate_success_opens_review_without_success_toast() -> None:
    events: list[object] = []
    parent = SimpleNamespace(
        show_toast=lambda message: events.append(("toast", message)),
        is_active=lambda: True,
        refresh_all_widgets=lambda: events.append("refresh"),
    )
    runner = OperationRunner.__new__(OperationRunner)
    runner.parent = parent
    runner._completion_callback = lambda result: events.append(("review", result))

    runner._on_operation_success("preview")

    assert events == [("review", "preview"), "refresh"]
    assert runner._completion_callback is None


def test_successful_intermediate_progress_advances_without_done_click() -> None:
    events: list[object] = []
    inert = SimpleNamespace(
        stop=lambda: None,
        set_visible=lambda value: events.append(("spinner-visible", value)),
    )
    cancel_button = SimpleNamespace(
        set_sensitive=lambda value: None,
        set_visible=lambda value: events.append(("button-visible", value)),
        set_label=lambda value: None,
        remove_css_class=lambda value: None,
        add_css_class=lambda value: None,
        connect=lambda *args: None,
    )
    dialog = SimpleNamespace(
        _pulse_timeout_id=None,
        spinner=inert,
        progress_bar=SimpleNamespace(set_fraction=lambda value: None),
        substatus_label=SimpleNamespace(set_text=lambda value: None),
        status_label=SimpleNamespace(set_text=lambda value: None, add_css_class=lambda value: None),
        cancel_button=cancel_button,
        cancellable=False,
        auto_advance=True,
        on_done_clicked=lambda *_args: None,
        emit=lambda *args: events.append(("emit", args)),
    )

    ProgressDialog._complete_operation(dialog, True, "preview")

    assert events[-2:] == [
        ("button-visible", False),
        ("emit", ("operation-completed", True, "preview")),
    ]
