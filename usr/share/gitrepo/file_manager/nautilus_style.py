"""Keep GitRepo's full-color emblems out of Nautilus's dimmed presentation."""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from .status import EMBLEMS


class EmblemStyle:
    def __init__(self):
        self._source = 0
        self._application = Gio.Application.get_default()
        self._css = Gtk.CssProvider()
        self._css.load_from_data(b".gitrepo-emblems.dim-label { opacity: 1; }")
        self._display = None
        if isinstance(self._application, Gtk.Application):
            self._application.connect("window-added", self._window_added)
            for window in self._application.get_windows():
                self._window_added(self._application, window)

    def _window_added(self, _application, window):
        window.connect("map", lambda *_args: self.schedule())
        self.schedule()

    def schedule(self, *_args):
        if not self._source:
            self._source = GLib.idle_add(self._refresh)

    @staticmethod
    def _children(widget):
        child = widget.get_first_child()
        while child is not None:
            yield child
            child = child.get_next_sibling()

    @staticmethod
    def _is_gitrepo(image):
        icon = image.get_gicon()
        if not isinstance(icon, Gio.ThemedIcon):
            return False
        names = set(icon.get_names())
        return any(name in names or f"emblem-{name}" in names for name in EMBLEMS.values())

    def _style_box(self, box):
        images = [child for child in self._children(box) if isinstance(child, Gtk.Image)]
        has_gitrepo = any(self._is_gitrepo(image) for image in images)
        if has_gitrepo:
            box.add_css_class("gitrepo-emblems")
        else:
            box.remove_css_class("gitrepo-emblems")
        for image in images:
            # Move the inherited dimming onto unrelated emblems in the same box.
            dim = has_gitrepo and box.has_css_class("dim-label") and not self._is_gitrepo(image)
            if dim and not image.has_css_class("dim-label"):
                image.add_css_class("dim-label")
                image.add_css_class("gitrepo-inherited-dim")
            elif not dim and image.has_css_class("gitrepo-inherited-dim"):
                image.remove_css_class("dim-label")
                image.remove_css_class("gitrepo-inherited-dim")

    def _watch_box(self, box):
        if not hasattr(box, "_gitrepo_emblem_children"):
            children = box.observe_children()
            children.connect("items-changed", lambda *_args: self._style_box(box))
            box._gitrepo_emblem_children = children
        self._style_box(box)

    def _refresh(self):
        self._source = 0
        if not isinstance(self._application, Gtk.Application):
            return GLib.SOURCE_REMOVE
        pending = list(self._application.get_windows())
        while pending:
            widget = pending.pop()
            if self._display is None:
                self._display = widget.get_display()
                Gtk.StyleContext.add_provider_for_display(
                    self._display, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            if isinstance(widget, Gtk.GridView) and not hasattr(widget, "_gitrepo_grid_children"):
                children = widget.observe_children()
                children.connect("items-changed", self.schedule)
                widget._gitrepo_grid_children = children
            if widget.__gtype__.name == "NautilusGridCell":
                box = widget.get_template_child(widget.__gtype__, "emblems_box")
                if isinstance(box, Gtk.Box):
                    self._watch_box(box)
                continue
            pending.extend(self._children(widget))
        return GLib.SOURCE_REMOVE
