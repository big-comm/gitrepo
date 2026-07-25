from datetime import datetime

from gitrepo.build_iso.core.build_estimate import historical_total_seconds, remaining_seconds
from gitrepo.build_iso.core.build_log import BuildLogFile
from gitrepo.common.terminal_palette import LOG_COLORS_DARK, LOG_COLORS_LIGHT, log_palette


def test_build_log_is_written_with_private_permissions(tmp_path):
    log = BuildLogFile("biglinux", "kde", directory=str(tmp_path), started_at=datetime(2026, 7, 25, 10, 30, 0))

    log.append("==> Creating squashfs image")
    log.append("secret-free line")
    log.close()

    assert log.path.endswith("2026-07-25_10-30-00_biglinux-kde.log")
    assert (tmp_path / "2026-07-25_10-30-00_biglinux-kde.log").read_text(encoding="utf-8") == (
        "==> Creating squashfs image\nsecret-free line\n"
    )
    assert (tmp_path / "2026-07-25_10-30-00_biglinux-kde.log").stat().st_mode & 0o777 == 0o600


def test_build_log_rejects_path_traversal_in_profile_names(tmp_path):
    log = BuildLogFile("../../etc", "kde/../..", directory=str(tmp_path), started_at=datetime(2026, 7, 25, 10, 0, 0))
    log.append("line")
    log.close()

    written = list(tmp_path.iterdir())
    assert [entry.parent for entry in written] == [tmp_path]
    assert ".." not in written[0].name


def test_build_log_keeps_only_the_newest_runs(tmp_path):
    for hour in range(6):
        BuildLogFile("biglinux", "kde", directory=str(tmp_path), started_at=datetime(2026, 7, 25, hour, 0, 0)).close()
    newest = BuildLogFile("biglinux", "kde", directory=str(tmp_path), started_at=datetime(2026, 7, 25, 9, 0, 0))

    newest.prune(keep=3)

    remaining = sorted(entry.name for entry in tmp_path.iterdir())
    assert len(remaining) == 3
    assert remaining[-1].startswith("2026-07-25_09-00-00")


def test_build_log_survives_an_unwritable_directory(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    log = BuildLogFile("biglinux", "kde", directory=str(blocked))
    log.append("line")
    log.close()

    assert log.error


def test_estimate_prefers_the_same_profile_then_any_success():
    history = [
        {"success": True, "duration": 600, "distro": "biglinux", "edition": "gnome"},
        {"success": True, "duration": 1200, "distro": "biglinux", "edition": "kde"},
        {"success": True, "duration": 1800, "distro": "biglinux", "edition": "kde"},
        {"success": False, "duration": 60, "distro": "biglinux", "edition": "kde"},
    ]

    assert historical_total_seconds(history, "biglinux", "kde") == 1500
    assert historical_total_seconds(history, "bigcommunity", "xfce") == 1200
    assert historical_total_seconds([{"success": False, "duration": 100}], "biglinux", "kde") is None


def test_remaining_time_only_projects_once_progress_is_meaningful():
    assert remaining_seconds(600, 0.5, None) == 600
    assert remaining_seconds(60, 0.05, 1500) == 1440
    assert remaining_seconds(60, 0.05, None) is None
    # A finished build has nothing left to project.
    assert remaining_seconds(1500, 1.0, 1200) == 0


def test_log_palette_defines_a_readable_colour_for_every_tag():
    assert set(LOG_COLORS_LIGHT) == set(LOG_COLORS_DARK)
    assert log_palette(True) is LOG_COLORS_DARK
    assert log_palette(False) is LOG_COLORS_LIGHT
    assert all(value.startswith("#") and len(value) == 7 for value in LOG_COLORS_LIGHT.values())
