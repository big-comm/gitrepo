"""What the interface shows is written for the user, not echoed from a tool."""

from pathlib import Path

import pytest

from gitrepo.build_iso.core.container_manager import engine_version_number
from gitrepo.build_iso.gui.widgets.history_widget import HistoryWidget


WIDGET_ROOT = Path(__file__).parents[2] / "usr/share/gitrepo/build_iso/gui/widgets"
MAIN_WINDOW = Path(__file__).parents[2] / "usr/share/gitrepo/build_iso/gui/main_window.py"


@pytest.mark.parametrize(
    ("banner", "expected"),
    [
        ("Docker version 29.6.1, build 8900f1d330", "29.6.1"),
        ("podman version 5.3.1", "5.3.1"),
        ("Docker version 27.0.0-rc.1, build abc123", "27.0.0-rc.1"),
        ("Docker Version 30.0.0, build x", "30.0.0"),
    ],
)
def test_the_engine_banner_is_reduced_to_its_version(banner, expected):
    # `docker --version` carries a build identifier that belongs in a bug
    # report, not in the sentence describing a healthy environment.
    assert engine_version_number(banner) == expected


def test_an_unrecognized_banner_is_shown_unchanged_rather_than_dropped():
    assert engine_version_number("some other runtime 1.2") == "some other runtime 1.2"


def test_the_destination_reports_free_space_only_when_it_matters():
    build_source = (WIDGET_ROOT / "build_widget.py").read_text(encoding="utf-8")

    # The environment line already states the free space of a healthy setup.
    assert '_("Disk space: {0:.1f} GB free of {1:.1f} GB")' not in build_source
    assert "self.disk_label.set_visible(False)" in build_source
    assert '_("Only {0:.1f} GB free here; a build needs about 20 GB.")' in build_source


def test_the_generated_isos_destination_and_its_page_share_one_name():
    window_source = MAIN_WINDOW.read_text(encoding="utf-8")
    history_source = (WIDGET_ROOT / "history_widget.py").read_text(encoding="utf-8")

    assert '_("Generated ISOs")' in window_source
    assert '_("Generated ISOs")' in history_source
    assert '_("Build History")' not in history_source


def test_a_history_row_is_identified_by_when_it_ran_and_how_it_ended():
    entry = {
        "date": "2026-07-25 16:56",
        "success": True,
        "status": "succeeded",
        "distro": "biglinux",
        "edition": "kde",
        "kernel": "lts",
        "duration": 1140,
    }

    # Consecutive builds of the same edition would otherwise share one title.
    assert HistoryWidget._outcome_text(entry) != ""
    subtitle = HistoryWidget._entry_subtitle(entry)
    assert "kernel lts" not in subtitle
    assert "19 min" in subtitle


def test_the_container_is_spelled_one_way_across_the_interface():
    settings_source = (WIDGET_ROOT / "settings_widget.py").read_text(encoding="utf-8")
    container_source = (WIDGET_ROOT / "container_widget.py").read_text(encoding="utf-8")

    assert '_("Container engine")' in settings_source
    assert '_("Container engine")' in container_source
    assert '_("Container Engine")' not in settings_source
