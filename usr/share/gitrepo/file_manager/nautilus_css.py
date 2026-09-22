"""Keep GitRepo's colored emblems legible in Nautilus without touching widgets.

Nautilus puts ``dim-label`` on the emblem box of every grid and list cell,
which renders the whole box at ~55% opacity. A child cannot override a
parent's opacity, so the fix has to target the box itself. This module does
that with a single global CSS provider and nothing else: no widget lookups,
no signal handlers, no Python attributes on GTK objects. Everything the
provider touches is plain CSS resolved by GTK on its own schedule.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

# Scoped to Nautilus file views. ``.nautilus-view-cell`` is the public style
# class Nautilus applies to its cells and the only ``box.dim-label`` inside a
# cell is the emblem box. Nothing else here depends on Nautilus internals.
EMBLEM_CSS = """
.nautilus-grid-view .nautilus-view-cell box.dim-label,
.nautilus-list-view .nautilus-view-cell box.dim-label {
  opacity: 1;
}
"""


def load_provider(css: str = EMBLEM_CSS) -> Gtk.CssProvider:
    """Parse ``css`` into a provider; raises ValueError on a parse error."""
    errors: list[str] = []
    provider = Gtk.CssProvider()
    provider.connect(
        "parsing-error", lambda _p, section, error: errors.append(f"{section.to_string()}: {error.message}")
    )
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(css)
    else:  # GTK < 4.12
        provider.load_from_data(css.encode(), -1)
    if errors:
        raise ValueError("; ".join(errors))
    return provider


def install(display: Gdk.Display | None = None) -> Gtk.CssProvider | None:
    """Install the emblem CSS once for ``display`` and return the provider.

    Returns None when no display is available (headless or too early), in
    which case the emblems simply stay dimmed; nothing is retried later.
    """
    display = display or Gdk.Display.get_default()
    if display is None:
        return None
    provider = load_provider()
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return provider
