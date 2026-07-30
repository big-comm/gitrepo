"""A build must always produce a result: the dialog reports nothing else."""

from unittest import mock

import pytest

from gitrepo.build_iso.core.container_manager import ContainerManager
from gitrepo.build_iso.core.iso_builder import ISOBuilder


def _builder(tmp_path, **extra):
    config = {"container_engine": "docker", "output_dir": str(tmp_path)}
    config.update(extra)
    return ISOBuilder(config)


@pytest.mark.parametrize(
    "error",
    [
        ValueError("refusing an unsafe build mirror URL"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        KeyError("missing"),
    ],
)
def test_an_unexpected_failure_still_returns_a_result(tmp_path, error):
    # execute() used to catch only OSError/SubprocessError/RuntimeError, so a
    # rejected mirror escaped, the worker thread died, and the dialog stayed
    # "running" with the elapsed timer ticking and a container still alive.
    builder = _builder(tmp_path)
    with mock.patch.object(ISOBuilder, "_prepare_build", side_effect=error):
        result = builder.execute()

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"]
    assert "duration" in result


def test_a_rejected_build_mirror_is_reported_not_raised(tmp_path):
    builder = _builder(tmp_path, build_mirror="https://example.org/$(id)")

    with mock.patch.object(ISOBuilder, "_prepare_build", return_value=""):
        result = builder.execute()

    assert result["success"] is False
    assert "unsafe build mirror" in result["error"]


def test_a_cancelled_build_does_not_advertise_a_removed_container(tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "gitrepo-build-iso-1"
    logged = []
    builder._callbacks = {"on_log": lambda color, message: logged.append(message)}
    builder._cancelled.set()

    with mock.patch.object(ISOBuilder, "_run_container", return_value=False):
        builder._build_and_publish_iso()

    # cancel() removes the container, so naming it sends the user to something
    # `docker logs` cannot resolve.
    assert not any("preserved for debugging" in message for message in logged)


def test_a_failed_build_still_names_the_container_it_kept(tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "gitrepo-build-iso-1"
    logged = []
    builder._callbacks = {"on_log": lambda color, message: logged.append(message)}

    with mock.patch.object(ISOBuilder, "_run_container", return_value=False):
        builder._build_and_publish_iso()

    assert any("gitrepo-build-iso-1" in message for message in logged)


def test_the_storage_driver_probe_is_bounded():
    # A wedged daemon socket accepts and never answers; the environment page
    # would sit on "Checking..." forever.
    manager = ContainerManager("docker")
    manager.engine = "docker"
    with mock.patch("gitrepo.build_iso.core.container_manager.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="overlay2")
        manager.get_storage_driver()

    assert run.call_args.kwargs.get("timeout")
