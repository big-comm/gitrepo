"""Bounded, asynchronous emblem updates for Nautilus-compatible providers."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from gi.repository import Gio, GLib

from .scanner import ScanJob
from .status import EMBLEMS, State


@dataclass
class _Entry:
    files: dict[int, Any] = field(default_factory=dict)
    state: State | None = None
    checked: float = 0
    future: Future | None = None


class EmblemProvider:
    """Keep Git and filesystem probes off the file manager's main thread."""

    # Bounds the folders remembered after they leave the screen, not the ones
    # displayed: those are all tracked, or their emblems would freeze.
    MAX_ENTRIES = 256
    REFRESH_SECONDS = 5
    CACHE_SECONDS = 300

    def __init__(self, on_changed=None):
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._queued = {}
        self._dispatch_source = 0
        self._scan = None
        self._on_changed = on_changed
        self._timer = 0
        self._closed = False
        application = Gio.Application.get_default()
        if application:
            application.connect("shutdown", self.close)

    def close(self, *_args):
        self._closed = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self._dispatch_source:
            GLib.source_remove(self._dispatch_source)
            self._dispatch_source = 0
        if self._scan:
            self._scan.cancel()
            self._scan = None
        self._queued.clear()
        self._entries.clear()

    def update(self, file_info):
        if self._closed or file_info.is_gone() or not file_info.is_directory():
            return
        location = file_info.get_location()
        path = location.get_path() if location else None
        if not path:
            return

        entry = self._entries.get(path)
        if entry is None:
            self._make_room()
            entry = self._entries[path] = _Entry()
        self._entries.move_to_end(path)
        # GObject weak refs survive replacement of the Python wrapper.
        entry.files[hash(file_info)] = file_info.weak_ref()
        if entry.state:
            file_info.add_emblem(EMBLEMS[entry.state])
            if self._on_changed:
                self._on_changed()
        if monotonic() - entry.checked >= self.REFRESH_SECONDS:
            self._schedule(path, entry)
        if not self._timer:
            self._timer = GLib.timeout_add_seconds(self.REFRESH_SECONDS, self._refresh)

    def _schedule(self, path, entry):
        if entry.future is not None:
            return
        entry.future = Future()
        self._queued[path] = (entry, entry.future)
        if not self._dispatch_source and self._scan is None:
            self._dispatch_source = GLib.idle_add(self._dispatch)

    def _dispatch(self):
        self._dispatch_source = 0
        if self._closed or self._scan is not None:
            return GLib.SOURCE_REMOVE
        batch = {
            path: (entry, future)
            for path, (entry, future) in self._queued.items()
            if self._entries.get(path) is entry and not future.cancelled()
        }
        self._queued.clear()
        if batch:
            self._scan = ScanJob(list(batch), lambda states: self._scan_finished(batch, states))
        return GLib.SOURCE_REMOVE

    def _scan_finished(self, batch, states):
        self._scan = None
        if self._closed:
            return
        for path, (entry, future) in batch.items():
            if not future.cancelled():
                state = states.get(path)
                future.set_result(state if isinstance(state, str) and state in EMBLEMS else None)
                self._complete(path, entry, future)
        if self._queued:
            self._dispatch()
        if self._on_changed:
            self._on_changed()

    def _complete(self, path, entry, future):
        if self._entries.get(path) is not entry or future.cancelled():
            return GLib.SOURCE_REMOVE
        entry.future = None
        entry.checked = monotonic()
        try:
            state = future.result()
        except Exception:
            state = None  # A failed probe must clear any stale success emblem.
        if state != entry.state:
            entry.state = state
            for reference in tuple(entry.files.values()):
                file_info = reference()
                if file_info is not None and not file_info.is_gone():
                    file_info.invalidate_extension_info()
        return GLib.SOURCE_REMOVE

    def _make_room(self):
        """Forget folders nobody displays anymore; never one still on screen.

        Nautilus asks for a folder's emblems when it loads it and again only
        when this provider invalidates it. A folder dropped while displayed
        would therefore keep its last emblem until the user pressed F5, so the
        bound only applies to folders whose file objects are all gone.
        """
        self._prune()
        while len(self._entries) >= self.MAX_ENTRIES:
            retired = next((path for path, entry in self._entries.items() if not entry.files), None)
            if retired is None:
                return
            entry = self._entries.pop(retired)
            if entry.future:
                entry.future.cancel()

    def _prune(self):
        for path, entry in tuple(self._entries.items()):
            for key, reference in tuple(entry.files.items()):
                file_info = reference()
                if file_info is None or file_info.is_gone():
                    del entry.files[key]
            if not entry.files:
                if entry.future:
                    entry.future.cancel()
                    entry.future = None
                if not entry.checked or monotonic() - entry.checked > self.CACHE_SECONDS:
                    del self._entries[path]

    def _refresh(self):
        self._prune()
        if not any(entry.files for entry in self._entries.values()):
            self._timer = 0
            return GLib.SOURCE_REMOVE
        for path, entry in self._entries.items():
            if entry.files and monotonic() - entry.checked >= self.REFRESH_SECONDS:
                self._schedule(path, entry)
        return GLib.SOURCE_CONTINUE
