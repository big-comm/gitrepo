from types import SimpleNamespace

from gitrepo.build_iso.config import ORG_DEFAULT_CONFIGS
from gitrepo.build_iso.gui import main_window
from gitrepo.build_iso.gui.widgets import container_widget


def test_bigbruno_keeps_the_documented_compatibility_profile():
    config = ORG_DEFAULT_CONFIGS["bigbruno"]

    assert config["distroname"] == "bigcommunity"
    assert config["iso_profiles_repo"] == "https://github.com/biglinux/iso-profiles"
    assert config["build_dir"] == "biglinux"
    assert config["branches"] == {
        "manjaro": "stable",
        "community": "",
        "biglinux": "stable",
    }


def test_environment_probe_checks_the_configured_image(monkeypatch):
    captured = {}

    class Manager:
        def __init__(self, preference):
            captured["preference"] = preference

        def capture_status(self, image):
            captured["image"] = image
            return "status"

    monkeypatch.setattr(main_window, "ContainerManager", Manager)
    monkeypatch.setattr(main_window, "capture_disk_status", lambda output_dir: output_dir)
    monkeypatch.setattr(main_window.GLib, "idle_add", lambda *args: captured.setdefault("idle", args))

    window = SimpleNamespace(
        settings=SimpleNamespace(
            container_engine_preference="podman",
            container_image="registry.example/build:tested",
            output_dir="/tmp/iso",
        ),
        _apply_environment_status=object(),
    )

    main_window.MainWindow._probe_environment(window, 4)

    assert captured["preference"] == "podman"
    assert captured["image"] == "registry.example/build:tested"
    assert captured["idle"][0] is window._apply_environment_status
    assert captured["idle"][1] == 4
    assert isinstance(captured["idle"][2], Manager)
    assert captured["idle"][3:] == ("status", "/tmp/iso")


def test_pull_and_cleanup_target_the_configured_image(monkeypatch):
    calls = []

    class Manager:
        def pull_image(self, image, progress_callback):
            calls.append(("pull", image))
            return True

        def list_stopped_containers(self, image):
            calls.append(("list", image))
            return ["container-id"]

    queued = []
    monkeypatch.setattr(container_widget.GLib, "idle_add", lambda *args: queued.append(args))

    widget = SimpleNamespace(
        settings=SimpleNamespace(container_image="registry.example/build:tested"),
        container_mgr=Manager(),
        _pull_completed=object(),
        _show_cleanup_confirmation=object(),
    )

    container_widget.ContainerWidget._pull_worker(widget)
    container_widget.ContainerWidget._prepare_cleanup(widget, "button")

    assert calls == [
        ("pull", "registry.example/build:tested"),
        ("list", "registry.example/build:tested"),
    ]
    assert queued[-1][1:] == ("button", "registry.example/build:tested", ["container-id"])
