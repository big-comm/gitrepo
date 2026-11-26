"""The Big kernel and mesa-big are the defaults of a local build.

Both are in the BigLinux repositories, which BigLinux and BigCommunity builds
use alike. The remote workflow runs a build script of its own that has neither,
so the terminal keeps the Big kernel out of a remote build.
"""

import json
from types import SimpleNamespace

import pytest

from gitrepo.build_iso import build_iso as cli
from gitrepo.build_iso.config import BUILD_MODE_LOCAL, BUILD_MODE_REMOTE
from gitrepo.build_iso.core.settings import Settings
from gitrepo.build_iso.local_config import LocalConfig


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")


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


@pytest.mark.parametrize(
    "mode,offered",
    [
        (BUILD_MODE_LOCAL, ["big", "lts", "latest", "oldlts", "xanmod"]),
        (BUILD_MODE_REMOTE, ["lts", "latest", "oldlts", "xanmod"]),
    ],
)
def test_terminal_kernel_choices(mode, offered):
    builder = SimpleNamespace(menu=Menu(), build_mode=mode, kernel="")

    assert cli.BuildISO.get_kernel(builder) is True
    assert builder.menu.options[:-1] == offered
    assert builder.kernel == offered[0]


@pytest.mark.parametrize("pick,mesa", [(0, "big"), (1, "manjaro")])
def test_terminal_video_driver_choice(pick, mesa):
    builder = SimpleNamespace(menu=Menu(pick), mesa="")

    assert cli.BuildISO.get_mesa(builder) is True
    assert builder.mesa == mesa


def test_terminal_refuses_remote_big_kernel():
    builder = SimpleNamespace(kernel="big", logger=Logger())

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
