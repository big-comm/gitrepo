"""The Big kernel and mesa-big are the defaults of a local build.

Both are in the BigLinux repositories, which BigLinux and BigCommunity builds
use alike. The remote workflow runs a build script of its own that has neither,
so the terminal keeps the Big kernel out of a remote build.
"""

import argparse
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from gitrepo.build_iso import build_iso as cli
from gitrepo.build_iso.config import BUILD_MODE_LOCAL, BUILD_MODE_REMOTE, KERNEL_DISPLAY_NAMES, kernel_display_name
from gitrepo.build_iso.core import big_kernels
from gitrepo.build_iso.core.settings import Settings
from gitrepo.build_iso.local_config import LocalConfig


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")


# The fixed kernel names are translated when config is imported.
OTHER_KERNELS = [KERNEL_DISPLAY_NAMES[kernel] for kernel in ("lts", "latest", "oldlts")]


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


class Menu:
    def __init__(self, pick=0):
        self.pick = pick
        self.options = None

    def show_menu(self, _title, options):
        self.options = options
        return self.pick, options[self.pick]


def database(*packages):
    """A pacman database: one <name>-<version>-<release>/desc per package."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for package in packages:
            info = tarfile.TarInfo(f"{package}/desc")
            archive.addfile(info, io.BytesIO(b""))
    return buffer.getvalue()


STABLE = database(
    "linux-big-1:7.2-2",
    "linux-big-headers-1:7.2-2",
    "linux-big72-7.2.15-5",
    "linux-big72-zfs-2.4.4-7021505",
    "linux-big73-7.3.5-2",
    "linux-lts-6.12-1",
)
TESTING = database("linux-big73-7.3.6-1", "linux-big74-7.4.0-1", "linux-big75-headers-7.5.0-1")


@pytest.fixture
def repositories(monkeypatch):
    sections = {"biglinux-stable": STABLE, "biglinux-testing": TESTING}
    monkeypatch.setattr(big_kernels, "_download_database", sections.__getitem__)
    return sections


@pytest.mark.parametrize(
    "branch,current,series",
    [("stable", "big72", ("big72", "big73")), ("testing", "big72", ("big72", "big73", "big74"))],
)
def test_series_read_from_repositories(repositories, branch, current, series):
    assert big_kernels.read_big_kernels(branch) == (current, series)


def test_testing_meta_package_decides_current(repositories):
    repositories["biglinux-testing"] = database("linux-big-1:7.3-1", "linux-big73-7.3.6-1")

    assert big_kernels.read_big_kernels("testing") == ("big73", ("big72", "big73"))


def test_unreadable_database_raises(repositories):
    repositories["biglinux-stable"] = b"<html>maintenance</html>"

    with pytest.raises(tarfile.TarError):
        big_kernels.read_big_kernels("stable")


def test_current_series_offered_once():
    assert big_kernels.local_kernel_choices("big72", ("big72", "big73")) == ["big", "big73", "lts", "latest", "oldlts"]


@pytest.mark.parametrize(
    "kernel,current,name",
    [
        ("big", "big72", "Big 7.2 (Recommended)"),
        ("big", "", KERNEL_DISPLAY_NAMES["big"]),
        ("big73", "", "Big 7.3"),
        ("big710", "", "Big 7.10"),
        ("lts", "big72", KERNEL_DISPLAY_NAMES["lts"]),
    ],
)
def test_kernel_names(kernel, current, name):
    assert kernel_display_name(kernel, current) == name


@pytest.mark.parametrize("value,accepted", [("big73", True), ("lts", True), ("big7", False), ("big7x", False)])
def test_kernel_option_takes_series(value, accepted):
    if accepted:
        assert cli._kernel_selector(value) == value
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            cli._kernel_selector(value)


def test_terminal_offers_big_series(repositories):
    builder = SimpleNamespace(
        menu=Menu(1), build_mode=BUILD_MODE_LOCAL, kernel="", branches={"biglinux": "testing"}, logger=Logger()
    )

    assert cli.BuildISO.get_kernel(builder) is True
    assert builder.menu.options[:-1] == ["Big 7.2 (Recommended)", "Big 7.3", "Big 7.4", *OTHER_KERNELS]
    assert builder.kernel == "big73"


def test_terminal_without_repositories_offers_big(monkeypatch):
    def unreachable(_branch):
        raise OSError("network is unreachable")

    monkeypatch.setattr(cli, "read_big_kernels", unreachable)
    builder = SimpleNamespace(menu=Menu(), build_mode=BUILD_MODE_LOCAL, kernel="", branches={}, logger=Logger())

    assert cli.BuildISO.get_kernel(builder) is True
    assert builder.menu.options[:-1] == [KERNEL_DISPLAY_NAMES["big"], *OTHER_KERNELS]
    assert builder.logger.messages[0][0] == "yellow"


def test_remote_terminal_hides_big():
    builder = SimpleNamespace(menu=Menu(), build_mode=BUILD_MODE_REMOTE, kernel="")

    assert cli.BuildISO.get_kernel(builder) is True
    assert builder.menu.options[:-1] == OTHER_KERNELS
    assert builder.kernel == "lts"


@pytest.mark.parametrize("pick,mesa", [(0, "big"), (1, "manjaro")])
def test_terminal_video_driver_choice(pick, mesa):
    builder = SimpleNamespace(menu=Menu(pick), mesa="")

    assert cli.BuildISO.get_mesa(builder) is True
    assert builder.mesa == mesa


@pytest.mark.parametrize("kernel", ["big", "big73"])
def test_terminal_refuses_remote_big_kernel(kernel):
    builder = SimpleNamespace(kernel=kernel, logger=Logger())

    assert cli.BuildISO.resume_and_build(builder) is False
    assert builder.logger.messages[0][0] == "red"
    assert "--kernel" in builder.logger.messages[0][1]


def test_fresh_settings_default_to_big(tmp_path):
    settings = Settings(config_file=str(tmp_path / "settings.json"))

    assert (settings.kernel, settings.mesa) == ("big", "big")


def test_video_driver_is_remembered(tmp_path):
    config_file = tmp_path / "settings.json"
    assert LocalConfig(Settings(config_file=str(config_file))).save_config({"mesa": "manjaro"}) is True

    assert Settings(config_file=str(config_file)).mesa == "manjaro"


def test_saved_kernel_survives_new_default(tmp_path):
    # Settings written before the video driver existed keep their kernel.
    config_file = tmp_path / "settings.json"
    config_file.write_text(json.dumps({"version": 1, "general": {"kernel": "lts"}}), encoding="utf-8")

    settings = Settings(config_file=str(config_file))

    assert (settings.kernel, settings.mesa) == ("lts", "big")
