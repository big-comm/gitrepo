"""Truthful remaining-time estimates for a running ISO build."""

from __future__ import annotations

from statistics import median
from typing import Any

# Early progress is dominated by fixed setup work, so the elapsed/fraction
# projection only becomes meaningful once a real part of the build is done.
PROJECTION_MIN_FRACTION = 0.15


def _successful_duration(entry: dict[str, Any]) -> int:
    """Return a usable duration for a successful build, or zero to skip it."""
    if not entry.get("success"):
        return 0
    try:
        duration = int(entry.get("duration", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, duration)


def historical_total_seconds(history: list[dict[str, Any]], distro: str, edition: str) -> int | None:
    """Return the median duration of comparable successful builds, if any."""
    successful = [duration for entry in history if (duration := _successful_duration(entry))]
    if not successful:
        return None
    same_profile = [
        duration
        for entry in history
        if (duration := _successful_duration(entry))
        and entry.get("distro") == distro
        and entry.get("edition") == edition
    ]
    return int(median(same_profile or successful))


def remaining_seconds(elapsed: int, fraction: float, historical_total: int | None) -> int | None:
    """Return the seconds left, or None while no honest estimate exists."""
    if elapsed < 0:
        return None
    if fraction >= PROJECTION_MIN_FRACTION and fraction < 1.0:
        return max(0, int(elapsed / fraction) - elapsed)
    if historical_total:
        return max(0, historical_total - elapsed)
    return None
