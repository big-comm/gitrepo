"""A running operation must not be detached by closing its window."""

from types import SimpleNamespace
from unittest import mock

from gitrepo.build_package.gui.dialogs.progress_dialog import ProgressDialog


def _dialog(running: bool):
    reported = []
    return (
        SimpleNamespace(
            _operation_running=running,
            _style_handler=0,
            _style_manager=None,
            operation_title="Publishing changes",
            _report_still_running=lambda: reported.append(True),
        ),
        reported,
    )


def test_closing_is_refused_while_the_operation_runs():
    # Returning False let Alt+F4 destroy the window while git kept working: the
    # log and result were lost and OperationRunner._busy stayed True, refusing
    # every later action until the process restarted.
    dialog, reported = _dialog(running=True)

    assert ProgressDialog._on_close_request(dialog, None) is True
    assert reported == [True]


def test_closing_is_allowed_once_the_operation_finished():
    dialog, reported = _dialog(running=False)

    assert ProgressDialog._on_close_request(dialog, None) is False
    assert reported == []


def test_the_style_handler_is_still_released_on_a_real_close():
    manager = mock.Mock()
    dialog = SimpleNamespace(
        _operation_running=False,
        _style_handler=7,
        _style_manager=manager,
        operation_title="x",
        _report_still_running=lambda: None,
    )

    assert ProgressDialog._on_close_request(dialog, None) is False
    manager.disconnect.assert_called_once_with(7)
    assert dialog._style_handler == 0


def test_completion_releases_the_window():
    source = ProgressDialog._complete_operation.__code__
    names = source.co_names

    # _complete_operation must clear the flag, or the window could never close.
    assert "_operation_running" in names
