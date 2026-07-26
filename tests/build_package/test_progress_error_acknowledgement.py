from types import SimpleNamespace

from gitrepo.build_package.gui.dialogs.progress_dialog import OperationRunner


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
