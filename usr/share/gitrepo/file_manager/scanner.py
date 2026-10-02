"""Native asynchronous delivery for hosts that retain Python's GIL between callbacks."""

import json
from pathlib import Path

from gi.repository import Gio, GLib


class ScanJob:
    def __init__(self, paths, complete):
        self._complete = complete
        self._cancelled = False
        self._process = None
        self._timeout = 0
        try:
            self._process = Gio.Subprocess.new(
                ["python3", str(Path(__file__).with_name("scan.py"))],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            self._process.communicate_utf8_async(json.dumps(paths), None, self._finished)
            self._timeout = GLib.timeout_add_seconds(30, self._expire)
        except GLib.Error:
            GLib.idle_add(self._failed)

    def _failed(self):
        if not self._cancelled:
            self._complete({})
        return GLib.SOURCE_REMOVE

    def _expire(self):
        self._timeout = 0
        if self._process:
            self._process.force_exit()
        return GLib.SOURCE_REMOVE

    def cancel(self):
        self._cancelled = True
        if self._process:
            self._process.force_exit()

    def _finished(self, process, result):
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        states = {}
        try:
            success, stdout, _stderr = process.communicate_utf8_finish(result)
            if success and process.get_successful():
                decoded = json.loads(stdout)
                if isinstance(decoded, dict):
                    states = decoded
        except (GLib.Error, ValueError):
            pass
        if not self._cancelled:
            self._complete(states)
