#
# core/iso_builder.py - ISO build orchestration adapted for GUI
#
# Wraps the existing local_builder.py logic with a GUI-friendly interface
# that reports progress via callbacks instead of direct console output.
#

import codecs
import errno
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator

from gitrepo.build_iso.core.config import BUILD_ISO_REPO, BUILD_MIRRORS, CONTAINER_IMAGE
from gitrepo.build_iso.core.container_manager import ISO_BUILDER_LABEL
from gitrepo.common.translation import _
from gitrepo.common import child_process as subprocess
from gitrepo.common.atomic_file import atomic_write_text

# The container reports the commits it resolved for its cloned inputs.
MANIFEST_LINE = re.compile(r"^GITREPO-MANIFEST (?P<name>[a-z0-9-]+) (?P<revision>[0-9a-f]{7,40})$")

# manjaro-tools.conf is sourced by the build, so a mirror URL reaching it must not
# be able to carry shell syntax. Accept only a plain http(s) host and path.
BUILD_MIRROR_URL = re.compile(r"^https?://[A-Za-z0-9._~-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~-]+)*/?$")

# Regex to strip ANSI escape codes from container output
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")
_MKSQUASHFS_PROGRESS_RE = re.compile(r"\b\d+\s*/\s*\d+\s+(\d{1,3}(?:\.\d+)?)%")
_XORRISO_PROGRESS_RE = re.compile(r"xorriso\s*:\s*UPDATE\s*:\s*(\d{1,3}(?:\.\d+)?)%\s+done", re.IGNORECASE)
_CONTAINER_ROOT = "/root/gitrepo-build"
_CONTAINER_WORK = f"{_CONTAINER_ROOT}/work"
_CONTAINER_OUTPUT = f"{_CONTAINER_ROOT}/output"
_CONTAINER_BUILD_REPO = f"{_CONTAINER_ROOT}/build-iso"
_CONTAINER_LOCAL_PROFILES = "/root/gitrepo-input/iso-profiles"

# Replaces configure_live_image()'s bare manjaro-live-setup call with a checked
# one. Kept as a plain string so the shell braces need no escaping; see
# ISOBuilder._live_setup_check_commands() for why it exists.
_LIVE_SETUP_PATCH = r"""#!/bin/bash
set -eo pipefail

image_lib=/usr/lib/manjaro-tools/util-iso-image.sh
[[ -f "$image_lib" ]] || exit 0

# build-iso.sh may reinstall manjaro-tools and re-run this patch in one build.
if grep -q '^mkiso_live_setup()' "$image_lib"; then
    exit 0
fi

cat >> "$image_lib" <<'MKISO_LIVE_SETUP'

# Added by GitRepo: manjaro-live-setup, with its result checked.
mkiso_live_setup() {
    local path=$1 user home entry

    if [[ ! -x "$path/usr/bin/manjaro-live-setup" ]]; then
        # Older manjaro-live-base creates the live user at boot instead.
        msg2 "Skipping manjaro-live-setup (absent from livefs)"
        return 0
    fi

    chroot "$path" /usr/bin/manjaro-live-setup
    if [[ -f "$path/var/log/manjaro-live-setup.log" ]]; then
        chroot "$path" cat /var/log/manjaro-live-setup.log
    fi

    user=$(sed -n 's|^username=||p' "$path/etc/manjaro-tools/live.conf" | tail -n1)
    if [[ -z "$user" ]]; then
        error "live.conf declares no username; cannot verify the live home"
        return 1
    fi

    home="$path/home/$user"
    if [[ ! -d "$home" ]]; then
        error "manjaro-live-setup did not create /home/%s" "$user"
        return 1
    fi

    msg2 "Re-syncing /etc/skel into /home/%s" "$user"
    if ! cp -a "$path/etc/skel/." "$home/"; then
        error "could not copy /etc/skel into /home/%s" "$user"
        return 1
    fi
    chroot "$path" chown -R "$user:$user" "/home/$user"

    for entry in "$path/etc/skel"/* "$path/etc/skel"/.[!.]*; do
        [[ -e "$entry" ]] || continue
        if [[ ! -e "$home/${entry##*/}" ]]; then
            error "skel entry %s never reached /home/%s" "${entry##*/}" "$user"
            return 1
        fi
    done
}
MKISO_LIVE_SETUP

sed -i \
    -e 's|^\([[:space:]]*\)chroot \$1 /usr/bin/manjaro-live-setup$|\1mkiso_live_setup "$1"|' \
    -e 's|^\([[:space:]]*\)chroot \$1 cat /var/log/manjaro-live-setup.log$|\1:|' \
    "$image_lib"

# The unchecked upstream call must be gone and ours must be in place; otherwise
# the build could ship another black-screen ISO.
! grep -q 'chroot \$1 /usr/bin/manjaro-live-setup' "$image_lib"
grep -q 'mkiso_live_setup "\$1"' "$image_lib"
"""


# Shared payload with build-iso/set-manjaro-branch.sh; see
# ISOBuilder._manjaro_branch_commands() for why it exists.
_MANJARO_BRANCH_PATCH = r"""#!/bin/bash
#
# set-manjaro-branch.sh - point the shipped CDN mirrors at the branch the ISO
#                         was actually built from
#
# The profile ships /etc/pacman.d/mirrorcdn with the branch hardcoded to
# "stable", and its pacman.conf includes mirrorcdn BEFORE mirrorlist:
#
#   [core]
#   Include = /etc/pacman.d/mirrorcdn      <- wins
#   Include = /etc/pacman.d/mirrorlist
#
# manjaro-tools writes the right branch into /etc/pacman-mirrors.conf, so
# mirrorlist is regenerated correctly, but the hardcoded CDN entries take
# precedence. A testing or unstable ISO would therefore install and then update
# from stable, mixing two branches on the user's disk.
#
# Rewrite the branch segment instead, in the cloned profile, before buildiso
# runs. With MANJARO_BRANCH=stable this is a no-op.
#
set -eo pipefail

: "${MANJARO_BRANCH:?MANJARO_BRANCH must be set}"
: "${PROFILE_PATH_EDITION:?PROFILE_PATH_EDITION must be set}"

case "$MANJARO_BRANCH" in
    stable|testing|unstable) ;;
    *) echo "unknown Manjaro branch: $MANJARO_BRANCH" >&2; exit 1 ;;
esac

patched=0
for overlay in root live; do
    conf="$PROFILE_PATH_EDITION/$overlay-overlay/etc/pacman.d/mirrorcdn"
    [[ -f "$conf" ]] || continue

    # The branch is the path segment right before /$repo/$arch, which is the one
    # shape all three CDN entries share. The delimiter must not be '|': sed reads
    # \| as an escaped delimiter, not as BRE alternation.
    sed -i "s#/\(stable\|testing\|unstable\)/\$repo/\$arch#/$MANJARO_BRANCH/\$repo/\$arch#g" "$conf"

    if grep -q "/\$repo/\$arch" "$conf" && ! grep -q "/$MANJARO_BRANCH/\$repo/\$arch" "$conf"; then
        echo "failed to set the branch in $conf" >&2
        exit 1
    fi
    echo "  -> $overlay-overlay mirrorcdn now on $MANJARO_BRANCH"
    patched=$((patched + 1))
done

if [[ $patched -eq 0 ]]; then
    echo "no mirrorcdn found under $PROFILE_PATH_EDITION" >&2
    exit 1
fi
"""


# Shared payload with build-iso/set-biglinux-branch.sh; see
# ISOBuilder._biglinux_branch_commands() for why it exists.
_BIGLINUX_BRANCH_PATCH = r"""#!/bin/bash
#
# set-biglinux-branch.sh - ship the BigLinux testing repository in the ISO when
#                          the ISO was built from it
#
# BigLinux branches are additive, unlike Manjaro's: enabling testing does not
# replace stable, it is inserted above it so testing wins where it has a package
# and stable still answers for everything else. build-iso.sh already does that
# for the build itself:
#
#   testing)
#       add_biglinux_testing | sudo tee -a "$config_file"
#       add_biglinux_stable  | sudo tee -a "$config_file"
#
# The profile's pacman.conf, however, only ever ships [biglinux-stable]. A
# testing ISO would therefore install and then update from stable alone, so the
# user never receives the testing packages the ISO was built with.
#
# Insert the section in the cloned profile before buildiso runs, keeping stable
# below it. With BIGLINUX_BRANCH=stable this is a no-op.
#
set -eo pipefail

: "${BIGLINUX_BRANCH:?BIGLINUX_BRANCH must be set}"
: "${PROFILE_PATH_EDITION:?PROFILE_PATH_EDITION must be set}"

case "$BIGLINUX_BRANCH" in
    stable)
        echo "  -> BigLinux stable: pacman.conf already ships [biglinux-stable]"
        exit 0
        ;;
    testing) ;;
    *)
        # build-iso.sh's add_repositories_to_pacman only knows stable and
        # testing, so any other value would build with no BigLinux repository at
        # all. Fail here rather than ship a mismatched ISO.
        echo "unsupported BigLinux branch: $BIGLINUX_BRANCH" >&2
        exit 1
        ;;
esac

patched=0
for overlay in root live; do
    conf="$PROFILE_PATH_EDITION/$overlay-overlay/etc/pacman.conf"
    [[ -f "$conf" ]] || continue

    if grep -q '^\[biglinux-testing\]' "$conf"; then
        echo "  -> $overlay-overlay pacman.conf already has [biglinux-testing]"
        patched=$((patched + 1))
        continue
    fi

    if ! grep -q '^\[biglinux-stable\]' "$conf"; then
        echo "no [biglinux-stable] section to insert above in $conf" >&2
        exit 1
    fi

    # Above [biglinux-stable], so testing takes precedence and stable remains.
    sed -i '/^\[biglinux-stable\]/i\
[biglinux-testing]\
SigLevel = PackageRequired\
Server = https://repo.biglinux.com.br/testing/$arch\
' "$conf"

    testing_line=$(grep -n '^\[biglinux-testing\]' "$conf" | cut -d: -f1)
    stable_line=$(grep -n '^\[biglinux-stable\]' "$conf" | cut -d: -f1)
    if [[ -z "$testing_line" || -z "$stable_line" || "$testing_line" -ge "$stable_line" ]]; then
        echo "failed to insert [biglinux-testing] above [biglinux-stable] in $conf" >&2
        exit 1
    fi
    echo "  -> $overlay-overlay pacman.conf: [biglinux-testing] above [biglinux-stable]"
    patched=$((patched + 1))
done

if [[ $patched -eq 0 ]]; then
    echo "no pacman.conf found under $PROFILE_PATH_EDITION" >&2
    exit 1
fi
"""


def iter_terminal_records(stream: BinaryIO) -> Iterator[tuple[str, bool]]:
    """Yield decoded terminal records and whether they replace the current line."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    characters: list[str] = []
    previous_was_carriage_return = False

    while chunk := stream.read(4096):
        text = chunk if isinstance(chunk, str) else decoder.decode(chunk)
        for character in text:
            if character == "\r":
                yield "".join(characters), True
                characters.clear()
                previous_was_carriage_return = True
            elif character == "\n":
                if previous_was_carriage_return and not characters:
                    previous_was_carriage_return = False
                    continue
                yield "".join(characters), False
                characters.clear()
                previous_was_carriage_return = False
            else:
                characters.append(character)
                previous_was_carriage_return = False

    characters.extend(decoder.decode(b"", final=True))
    if characters:
        yield "".join(characters), False


def parse_mksquashfs_progress(line: str) -> float | None:
    """Return the bounded mksquashfs completion fraction from a status line."""
    match = _MKSQUASHFS_PROGRESS_RE.search(line)
    if not match:
        return None
    return min(1.0, max(0.0, float(match.group(1)) / 100.0))


def parse_xorriso_progress(line: str) -> float | None:
    """Return the bounded xorriso completion fraction from an update line."""
    match = _XORRISO_PROGRESS_RE.search(line)
    if not match:
        return None
    return min(1.0, max(0.0, float(match.group(1)) / 100.0))


def detect_build_substep(line: str) -> str | None:
    """Map stable manjaro-tools output markers to a Build ISO substep."""
    normalized = line.casefold()
    if any(marker in normalized for marker in ("creating iso image", "making bootable image")):
        return "image"
    if any(marker in normalized for marker in ("generating squashfs", "creating squashfs", "start [build iso]")):
        return "compress"
    if "prepare [/iso/boot" in normalized:
        return "boot"
    if any(
        marker in normalized
        for marker in (
            "prepare [base installation]",
            "prepare [desktop installation]",
            "prepare [live installation]",
            "prepare [drivers repository]",
        )
    ):
        return "system"
    if any(marker in normalized for marker in ("starting iso build process", "executing buildiso", "start building [")):
        return "profile"
    return None


class ISOBuilder:
    """ISO build orchestration with callback-based progress reporting"""

    BUILD_STEPS = (
        ("prepare", frozenset({"check_engine", "check_storage", "check_space"})),
        ("image", frozenset({"pull_image"})),
        ("build", frozenset({"container_build"})),
        ("publish", frozenset({"move_files"})),
        ("finish", frozenset({"cleanup"})),
    )
    STEP_PROGRESS_RANGES = ((0.0, 0.08), (0.08, 0.15), (0.15, 0.9), (0.9, 0.97), (0.97, 1.0))
    BUILD_SUBSTEPS = ("profile", "system", "boot", "compress", "image")

    def __init__(self, config: dict, callbacks: dict = None):
        """
        Args:
            config: Build configuration dict supplied by the selected interface
            callbacks: Dict of callback functions:
                - on_log(color, message): Log message
                - on_live_log(color, message): Replace the unfinished terminal line
                - on_progress(fraction, phase_text): Progress update 0.0-1.0
                - on_phase(phase_name): Phase change notification
                - on_build_substep(substep_name, fraction): Build ISO substep update
                - on_completed(success, iso_path, error_msg): Build finished
        """
        self.distroname = config.get("distroname", "bigcommunity")
        self.edition = config.get("edition", "gnome")
        self.branches = config.get("branches", {})
        self.kernel = config.get("kernel", "lts")
        self.iso_profiles_repo = config.get("iso_profiles_repo", "")
        self.iso_profiles_source = config.get("iso_profiles_source", "remote")
        self.iso_profiles_local_path = config.get("iso_profiles_local_path", "")
        self.build_dir = config.get("build_dir", "bigcommunity")
        self.output_dir = os.path.expanduser(config.get("output_dir", "~/ISO"))
        self.container_engine = self._resolve_engine(config.get("container_engine", "docker"))
        self.container_image = config.get("container_image", CONTAINER_IMAGE)
        configured_mirrors = config.get("build_mirrors")
        legacy_mirror = config.get("build_mirror")
        self.build_mirrors = tuple(configured_mirrors or ((legacy_mirror,) if legacy_mirror else BUILD_MIRRORS))
        self.build_mirror = self.build_mirrors[0]

        self.release_tag = datetime.now().strftime("%Y-%m-%d_%H-%M")

        self._callbacks = callbacks or {}
        self._cancelled = threading.Event()
        self._container_name = ""
        # What this build actually resolved: image digest and cloned commits.
        self.manifest: dict[str, str] = {}
        # One owner for whichever child is running now, so cancellation can
        # reach a phase that is blocked reading a stalled process.
        self._process_lock = threading.Lock()
        self._active_process = None
        self._build_substep_index = -1
        self._build_substep_fraction = 0.0

    @staticmethod
    def _resolve_engine(engine: str) -> str:
        """Resolve 'auto' engine to actual docker/podman binary"""
        if engine in ("docker", "podman"):
            return engine
        # Auto-detect: prefer docker, fallback to podman
        for eng in ("docker", "podman"):
            if shutil.which(eng):
                return eng
        return ""

    def _log(self, color: str, message: str):
        cb = self._callbacks.get("on_log")
        if cb:
            cb(color, message)

    def _live_log(self, color: str, message: str) -> None:
        cb = self._callbacks.get("on_live_log")
        if cb:
            cb(color, message)

    def _progress(self, fraction: float | None, text: str = ""):
        cb = self._callbacks.get("on_progress")
        if cb:
            cb(fraction, text)

    def _phase(self, name: str):
        cb = self._callbacks.get("on_phase")
        if cb:
            cb(name)
        self._progress(self.total_progress_for_phase(name), name)
        if name == "container_build":
            self._set_build_substep("profile")

    @classmethod
    def step_index_for_phase(cls, phase: str) -> int:
        for index, (_step_id, phases) in enumerate(cls.BUILD_STEPS):
            if phase in phases:
                return index
        raise ValueError(f"unknown build phase: {phase}")

    @classmethod
    def total_progress_for_phase(cls, phase: str, step_fraction: float = 0.0) -> float:
        step_index = cls.step_index_for_phase(phase)
        bounded_fraction = min(1.0, max(0.0, step_fraction))
        start, end = cls.STEP_PROGRESS_RANGES[step_index]
        return start + (end - start) * bounded_fraction

    @classmethod
    def total_progress_for_build_substep(cls, substep: str, fraction: float = 0.0) -> float:
        substep_index = cls.BUILD_SUBSTEPS.index(substep)
        bounded_fraction = min(1.0, max(0.0, fraction))
        build_fraction = (substep_index + bounded_fraction) / len(cls.BUILD_SUBSTEPS)
        return cls.total_progress_for_phase("container_build", build_fraction)

    def _set_build_substep(self, substep: str, fraction: float = 0.0, detail: str = "") -> None:
        substep_index = self.BUILD_SUBSTEPS.index(substep)
        bounded_fraction = min(1.0, max(0.0, fraction))
        if substep_index < self._build_substep_index:
            return
        if substep_index == self._build_substep_index and bounded_fraction < self._build_substep_fraction:
            return

        self._build_substep_index = substep_index
        self._build_substep_fraction = bounded_fraction
        callback = self._callbacks.get("on_build_substep")
        if callback:
            callback(substep, bounded_fraction)
        self._progress(self.total_progress_for_build_substep(substep, bounded_fraction), detail)

    @staticmethod
    def _normalize_terminal_record(record: str) -> str:
        visible: list[str] = []
        for character in _ANSI_RE.sub("", record):
            if character == "\b":
                if visible:
                    visible.pop()
            elif character.isprintable() or character == "\t":
                visible.append(character)
        return "".join(visible).rstrip()

    def _handle_container_record(self, record: str, replaces_line: bool) -> None:
        clean_line = self._normalize_terminal_record(record)
        if not clean_line:
            return

        if self._record_manifest_line(clean_line):
            return

        squashfs_fraction = parse_mksquashfs_progress(clean_line)
        xorriso_fraction = parse_xorriso_progress(clean_line)
        if squashfs_fraction is not None:
            percent = round(squashfs_fraction * 100)
            self._set_build_substep(
                "compress",
                squashfs_fraction,
                _("Compressing filesystem — {0}%").format(percent),
            )
        elif xorriso_fraction is not None:
            percent = round(xorriso_fraction * 100)
            self._set_build_substep(
                "image",
                xorriso_fraction,
                _("Creating ISO image — {0}%").format(percent),
            )
        elif substep := detect_build_substep(clean_line):
            self._set_build_substep(substep)

        if replaces_line:
            self._live_log("white", clean_line)
        else:
            self._log("white", clean_line)

    def _record_manifest_line(self, line: str) -> bool:
        """Capture a `GITREPO-MANIFEST <name> <sha>` line from the container.

        The build clones its inputs at whatever their default branch points to
        today. Recording the resolved commits is what makes a finished ISO
        reconstructible from the entry that describes it.
        """
        match = MANIFEST_LINE.match(line)
        if not match:
            return False
        name, revision = match.group("name"), match.group("revision")
        self.manifest[name] = revision
        self._log("dim", _("{0} at {1}").format(name, revision[:12]))
        return True

    def resolve_image_digest(self) -> str:
        """Return the exact image this build ran, as a pinnable reference."""
        if not self.container_engine:
            return ""
        for template in ("{{index .RepoDigests 0}}", "{{.Id}}"):
            result = subprocess.run(
                [self.container_engine, "image", "inspect", "--format", template, self.container_image],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=30,
            )
            reference = result.stdout.strip()
            if result.returncode == 0 and reference:
                return reference
        return ""

    def _own_process(self, process) -> bool:
        """Register *process* as the child cancellation must terminate."""
        with self._process_lock:
            if self._cancelled.is_set():
                # Cancelled between spawning and registering: stop it here,
                # because cancel() has already looked and found nothing.
                process.kill()
                process.wait()
                return False
            self._active_process = process
            return True

    def _release_process(self, process) -> None:
        with self._process_lock:
            if self._active_process is process:
                self._active_process = None

    def cancel(self):
        """Request cancellation and terminate whatever child is running now."""
        self._cancelled.set()
        # Kill running container in a thread to avoid blocking UI
        if self._container_name and self.container_engine:

            def _stop():
                subprocess.run(
                    [self.container_engine, "stop", "-t", "2", self._container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=30,
                )
                subprocess.run(
                    [self.container_engine, "rm", "-f", "-v", self._container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=30,
                )

            threading.Thread(target=_stop, daemon=True).start()

        with self._process_lock:
            process = self._active_process
        # Killing closes the pipe, so a phase blocked reading its output wakes
        # up instead of waiting for a line that will never arrive.
        if process and process.poll() is None:
            process.kill()
            process.wait()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _run_step(self, phase: str, action, error_message: str) -> str:
        if self.is_cancelled:
            return _("Build cancelled")
        self._phase(phase)
        return "" if action() else error_message

    def _check_output_space(self) -> bool:
        os.makedirs(self.output_dir, exist_ok=True)
        probe = None
        try:
            probe = tempfile.NamedTemporaryFile(prefix=".gitrepo-write-check-", dir=self.output_dir, delete=False)
            probe.close()
        except OSError as error:
            self._log("red", _("The output folder is not writable: {0}").format(error))
            return False
        finally:
            if probe:
                Path(probe.name).unlink(missing_ok=True)
        free_gb = shutil.disk_usage(self.output_dir).free / (1024**3)
        self._log("cyan", _("Disk space available: {0:.1f} GB").format(free_gb))
        if free_gb < 20:
            self._log("yellow", _("Only {0:.1f} GB is free; 20 GB is recommended.").format(free_gb))
        return True

    def _prepare_build(self) -> str:
        steps = [("check_engine", self._check_engine, _("The selected container engine is unavailable."))]
        if self.container_engine == "docker":
            steps.append(
                (
                    "check_storage",
                    self._check_storage_driver,
                    _("Docker is unavailable or access was denied."),
                )
            )
        steps.extend(
            [
                ("check_space", self._check_output_space, _("Could not inspect output disk space")),
                ("pull_image", self._pull_image, _("Failed to pull container image")),
            ]
        )
        for phase, action, message in steps:
            error = self._run_step(phase, action, message)
            if error:
                return error
        digest = self.resolve_image_digest()
        if digest:
            self.manifest["container-image"] = digest
            self._log("dim", _("Container image resolved to {0}").format(digest))
        return ""

    def _build_and_publish_iso(self) -> tuple[str, str]:
        error = self._run_step("container_build", self._run_container, _("Container build failed"))
        if error:
            # Cancelling removes the container, so pointing the user at a name
            # `docker logs` cannot resolve is worse than saying nothing.
            if self._container_name and not self.is_cancelled:
                self._log(
                    "yellow",
                    _("Stopped container preserved for debugging: {0}").format(self._container_name),
                )
            return "", error
        self._phase("move_files")
        iso_path = self._publish_container_artifacts()
        return (iso_path, "") if iso_path else ("", _("No ISO files found after build"))

    def _finish_successful_build(self) -> None:
        self._phase("cleanup")
        self._cleanup_containers()

    def execute(self) -> dict:
        """Execute the bounded build pipeline and always report elapsed duration."""
        started_at = time.monotonic()
        result = {
            "success": False,
            "status": "running",
            "iso_path": "",
            "error": "",
            "duration": 0,
            "manifest": {},
        }
        try:
            result["error"] = self._prepare_build()
            if not result["error"]:
                result["iso_path"], result["error"] = self._build_and_publish_iso()
            if not result["error"]:
                self._finish_successful_build()
                result["success"] = True
                result["status"] = "succeeded"
                self._log("green", _("Build completed successfully: {0}").format(result["iso_path"]))
        except Exception as error:
            # Every exit has to produce a result: the caller runs this on a
            # worker thread and only reports completion from its return value,
            # so an escaping exception leaves the dialog running forever with a
            # container still alive. The pipeline raises more than OSError --
            # a rejected build mirror raises ValueError, and strict decoding
            # raises UnicodeDecodeError -- and `finally` already normalizes the
            # status either way.
            result["error"] = str(error)
            self._log("red", _("Build failed: {0}").format(error))
        finally:
            if self.is_cancelled:
                result["status"] = "cancelled"
                result["error"] = _("Build cancelled")
            elif not result["success"]:
                result["status"] = "failed"
            result["duration"] = int(time.monotonic() - started_at)
            # The manifest describes what this build actually used, so it
            # is reported for a failed run too.
            result["manifest"] = dict(self.manifest)
        return result

    def _check_engine(self) -> bool:
        """Verify the exact selected engine and its service without fallback."""
        if self.container_engine not in {"docker", "podman"} or not shutil.which(self.container_engine):
            return False
        result = subprocess.run(
            [self.container_engine, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        return result.returncode == 0

    def _check_storage_driver(self) -> bool:
        """Report Docker's storage driver without changing host configuration."""
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.Driver}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                self._log("red", _("Docker did not answer the storage-driver check."))
                return False

            driver = result.stdout.strip()
            if driver == "btrfs":
                self._log("yellow", _("Docker is using the btrfs storage driver."))
                self._log("yellow", _("GitRepo will not change Docker storage or remove Docker data."))
            return True

        except Exception as e:
            self._log("red", _("Error checking Docker storage: {0}").format(str(e)))
            return False

    def _pull_image(self) -> bool:
        process = subprocess.Popen(
            [self.container_engine, "pull", self.container_image],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # A pull that stalls produces no further line, so the loop below would
        # never notice a cancellation on its own.
        if not self._own_process(process):
            return False
        try:
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    self._log("dim", f"  {line}")
                if self.is_cancelled:
                    break
            process.wait()
        finally:
            self._release_process(process)
        if self.is_cancelled:
            return False
        if process.returncode == 0:
            self._log("green", _("Container image pulled successfully"))
            return True
        self._log("red", _("Failed to pull container image"))
        return False

    def _build_mirror_commands(self) -> str:
        """Configure ordered mirrors for every Manjaro package download.

        mkchroot rewrites the build pacman.conf, replacing
        "Include = /etc/pacman.d/mirrorlist" with one Server, while chroot-run
        also overwrites the chroot mirrorlist. Patch both paths to use the same
        ordered file, so pacman falls through to the next Server when a package
        cannot be retrieved.

        manjaro-tools sources ~/.config/manjaro-tools/manjaro-tools.conf before
        applying its defaults. Keep its scalar set to the first mirror for its
        command-line plumbing; the patched consumers use the complete list.
        """
        for mirror in self.build_mirrors:
            if not isinstance(mirror, str) or not BUILD_MIRROR_URL.match(mirror):
                raise ValueError(f"refusing an unsafe build mirror URL: {mirror!r}")

        server_lines = "\n".join(
            f"Server = {mirror.rstrip('/')}/$MANJARO_BRANCH/\\$repo/\\$arch" for mirror in self.build_mirrors
        )
        return (
            "mkdir -p /root/.config/manjaro-tools\n"
            f"printf 'build_mirror=%s\\n' '{self.build_mirror}' > /root/.config/manjaro-tools/manjaro-tools.conf\n"
            f'grep -qx "build_mirror={self.build_mirror}" /root/.config/manjaro-tools/manjaro-tools.conf\n'
            f"cat > {_CONTAINER_ROOT}/patch-build-mirrors.sh <<'GITREPO_BUILD_MIRRORS'\n"
            + r"""#!/bin/bash
set -eo pipefail

: "${MANJARO_BRANCH:?MANJARO_BRANCH must be set}"
case "$MANJARO_BRANCH" in
    stable|testing|unstable) ;;
    *) echo "unknown Manjaro branch: $MANJARO_BRANCH" >&2; exit 1 ;;
esac

mirror_file=/etc/pacman.d/gitrepo-build-mirrors
mkchroot=/usr/bin/mkchroot
chroot_run=/usr/bin/chroot-run

install -dm755 "${mirror_file%/*}"
cat > "$mirror_file" <<GITREPO_MIRRORLIST
"""
            + server_lines
            + r"""
GITREPO_MIRRORLIST

old_mkchroot='sed "s#Include = /etc/pacman.d/mirrorlist#Server = ${url}#g" $pac_conf > $pac_base'
new_mkchroot='sed "s#Include = /etc/pacman.d/mirrorlist#Include = /etc/pacman.d/gitrepo-build-mirrors#g" "$pac_conf" > "$pac_base"'
if ! grep -Fqx "    $new_mkchroot" "$mkchroot"; then
    grep -Fqx "    $old_mkchroot" "$mkchroot"
    sed -i '\|^[[:space:]]*sed "s#Include = /etc/pacman.d/mirrorlist#Server = \${url}#g" \$pac_conf > \$pac_base$|c\    sed "s#Include = /etc/pacman.d/mirrorlist#Include = /etc/pacman.d/gitrepo-build-mirrors#g" "$pac_conf" > "$pac_base"' "$mkchroot"
fi

old_chroot_run='echo "Server = ${build_mirror}" > "$1/etc/pacman.d/mirrorlist"'
new_chroot_run='cp /etc/pacman.d/gitrepo-build-mirrors "$1/etc/pacman.d/mirrorlist"'
if ! grep -Fqx "            $new_chroot_run" "$chroot_run"; then
    grep -Fqx "            $old_chroot_run" "$chroot_run"
    sed -i '\|^[[:space:]]*echo "Server = \${build_mirror}" > "\$1/etc/pacman.d/mirrorlist"$|c\            cp /etc/pacman.d/gitrepo-build-mirrors "$1/etc/pacman.d/mirrorlist"' "$chroot_run"
fi

test "$(grep -c '^Server = ' "$mirror_file")" -eq """
            + str(len(self.build_mirrors))
            + r"""
grep -Fqx "    $new_mkchroot" "$mkchroot"
grep -Fqx "            $new_chroot_run" "$chroot_run"
"""
            + "GITREPO_BUILD_MIRRORS\n"
            + f"chmod +x {_CONTAINER_ROOT}/patch-build-mirrors.sh\n"
            + f'sed -i \'/^  patch_manjaro_tools$/a\\  sudo env MANJARO_BRANCH="$MANJARO_BRANCH" bash {_CONTAINER_ROOT}/patch-build-mirrors.sh || die "patch-build-mirrors.sh failed"\' {_CONTAINER_BUILD_REPO}/build-iso.sh\n'
            + f"grep -q '^  sudo env MANJARO_BRANCH=\"$MANJARO_BRANCH\" bash {_CONTAINER_ROOT}/patch-build-mirrors.sh || die' {_CONTAINER_BUILD_REPO}/build-iso.sh\n"
        )

    def _live_setup_check_commands(self) -> str:
        """Verify manjaro-live-setup actually produced a usable live home.

        manjaro-live-base 20260722 moved live-user creation out of the
        boot-time manjaro-live.service and into manjaro-live-setup, which
        manjaro-tools-iso-git r3071 runs inside the livefs chroot at build time.
        /usr/bin/manjaro-live now only handles console font, locale and samba,
        so skipping the build-time call would leave the ISO with no live user.

        The call is therefore kept, and checked. On the CI build filesystem
        `useradd -m` could not copy /etc/skel across the livefs overlayfs and
        said so without failing:

            useradd: /etc/skel/.bash_logout: Bad file descriptor
            Created user biglinux with password biglinux: 0.062ms

        The live home was left without the big-skel Plasma configuration, and
        the session booted to a black screen with no plasmashell. Re-sync skel
        afterwards and fail the build when the home still does not match, so a
        broken ISO is never published.
        """
        return (
            f"\ncat > {_CONTAINER_ROOT}/patch-live-setup.sh <<'GITREPO_LIVE_SETUP_PATCH'\n"
            + _LIVE_SETUP_PATCH
            + "GITREPO_LIVE_SETUP_PATCH\n"
            + f"chmod +x {_CONTAINER_ROOT}/patch-live-setup.sh\n"
            + f"""sed -i '/^  patch_manjaro_tools$/a\\  sudo bash {_CONTAINER_ROOT}/patch-live-setup.sh || die "patch-live-setup.sh failed"' """
            + f"{_CONTAINER_BUILD_REPO}/build-iso.sh\n"
            + f"grep -q '^  sudo bash {_CONTAINER_ROOT}/patch-live-setup.sh || die'"
            + f" {_CONTAINER_BUILD_REPO}/build-iso.sh\n"
        )

    def _manjaro_branch_commands(self) -> str:
        """Point the shipped CDN mirrors at the branch being built.

        The profile hardcodes stable in /etc/pacman.d/mirrorcdn, and its
        pacman.conf includes mirrorcdn ahead of mirrorlist. manjaro-tools writes
        the right branch into /etc/pacman-mirrors.conf, so mirrorlist is correct,
        but the hardcoded CDN entries win: a testing or unstable ISO would
        install and then update from stable, mixing branches on the user's disk.

        Rewrites the branch segment in the cloned profile before buildiso runs.
        With the stable branch it is a no-op.
        """
        return rf"""
cat > {_CONTAINER_ROOT}/set-manjaro-branch.sh <<'GITREPO_MANJARO_BRANCH'
{_MANJARO_BRANCH_PATCH}GITREPO_MANJARO_BRANCH
chmod +x {_CONTAINER_ROOT}/set-manjaro-branch.sh
sed -i '/^  clone_iso_profiles$/a\  bash {_CONTAINER_ROOT}/set-manjaro-branch.sh || die "set-manjaro-branch.sh failed"' {_CONTAINER_BUILD_REPO}/build-iso.sh
grep -q '^  bash {_CONTAINER_ROOT}/set-manjaro-branch.sh || die' {_CONTAINER_BUILD_REPO}/build-iso.sh
"""

    def _biglinux_branch_commands(self) -> str:
        """Ship the BigLinux testing repository when building from it.

        BigLinux branches are additive, unlike Manjaro's: testing is inserted
        above stable and stable stays, so testing wins where it has a package.
        build-iso.sh already does that for the build, but the profile's
        pacman.conf only ever ships [biglinux-stable], so a testing ISO would
        install and then update from stable alone -- never receiving the testing
        packages it was built with.

        With the stable branch it is a no-op.
        """
        return rf"""
cat > {_CONTAINER_ROOT}/set-biglinux-branch.sh <<'GITREPO_BIGLINUX_BRANCH'
{_BIGLINUX_BRANCH_PATCH}GITREPO_BIGLINUX_BRANCH
chmod +x {_CONTAINER_ROOT}/set-biglinux-branch.sh
sed -i '/^  clone_iso_profiles$/a\  bash {_CONTAINER_ROOT}/set-biglinux-branch.sh || die "set-biglinux-branch.sh failed"' {_CONTAINER_BUILD_REPO}/build-iso.sh
grep -q '^  bash {_CONTAINER_ROOT}/set-biglinux-branch.sh || die' {_CONTAINER_BUILD_REPO}/build-iso.sh
"""

    def _keep_man_pages_commands(self) -> str:
        """Stop the cleanup from deleting /usr/share/man from every image.

        mkiso_build_iso_cleanups() wipes man pages in rootfs, desktopfs and
        livefs. BigLinux ships them on purpose, so drop that one removal and
        leave the rest of the cleanup alone.
        """
        return rf"""
sed -i 's|^  rm -rf "\$cpath/usr/share/man"/\* 2> /dev/null$|  # man pages are kept on purpose|' \
    {_CONTAINER_BUILD_REPO}/build-iso.sh
! grep -q 'usr/share/man"/\*' {_CONTAINER_BUILD_REPO}/build-iso.sh
"""

    def _disable_extra_packages_commands(self) -> str:
        """Drop buildiso's -f flag so the build resolves extra=false.

        build-iso.sh always passes -f ("Build full ISO"), which makes
        manjaro-tools set extra=true and therefore install every `>extra` line
        of the profile's Packages-* files. The published pipeline builds without
        -f, so the two generators disagreed on the package set. Removing the
        flag here keeps a locally built ISO equal to the published one.
        """
        return rf"""
sed -i \
    -e 's|buildiso -d zstd -f |buildiso -d zstd |g' \
    -e 's|buildiso -f -p |buildiso -p |g' \
    {_CONTAINER_BUILD_REPO}/build-iso.sh
! grep -q 'buildiso \(-d zstd \)\?-f ' {_CONTAINER_BUILD_REPO}/build-iso.sh
"""

    def _build_setup_script(self) -> str:
        """Build setup script that runs inside container before build-iso.sh"""
        parts = [
            """
set -eo pipefail
umask 022
mkdir -p /root/gitrepo-build/work /root/gitrepo-build/output
git clone --depth 1 "$BUILD_ISO_REPO" /root/gitrepo-build/build-iso
echo "GITREPO-MANIFEST build-iso $(git -C /root/gitrepo-build/build-iso rev-parse HEAD)"
sed -i 's|git clone --depth 1 "$ISO_PROFILES_REPO" "$WORK_PATH_ISO_PROFILES" &>/dev/null|git clone --depth 1 "$ISO_PROFILES_REPO" "$WORK_PATH_ISO_PROFILES"|' /root/gitrepo-build/build-iso/build-iso.sh
"""
        ]

        parts.append(self._build_mirror_commands())
        parts.append(self._live_setup_check_commands())
        parts.append(self._manjaro_branch_commands())
        parts.append(self._biglinux_branch_commands())
        parts.append(self._keep_man_pages_commands())
        parts.append(self._disable_extra_packages_commands())

        if self.distroname == "bigcommunity":
            parts.append("""
echo "[community-extra]" | sudo tee -a /etc/pacman.conf
echo "SigLevel = PackageRequired" | sudo tee -a /etc/pacman.conf
echo "Server = https://repo.communitybig.org/extra/\\$arch" | sudo tee -a /etc/pacman.conf
echo "" | sudo tee -a /etc/pacman.conf
""")

        parts.append("""
cd /tmp
git clone --depth 1 https://github.com/biglinux/biglinux-key.git
sudo install -dm755 /etc/pacman.d/gnupg/
sudo install -m0644 biglinux-key/usr/share/pacman/keyrings/* /etc/pacman.d/gnupg/
rm -rf biglinux-key
""")

        if self.distroname == "bigcommunity":
            parts.append("""
cd /tmp
git clone --depth 1 https://github.com/big-comm/community-keyring.git
sudo install -m0644 community-keyring/community.gpg /usr/share/pacman/keyrings/
sudo install -m0644 community-keyring/community-trusted /usr/share/pacman/keyrings/
sudo install -m0644 community-keyring/community-revoked /usr/share/pacman/keyrings/
rm -rf community-keyring
""")

        # Rank mirrors by speed and initialize pacman keys
        parts.append("""
if command -v pacman-mirrors &>/dev/null; then
    sudo pacman-mirrors --fasttrack 5 2>/dev/null || true
fi
sudo pacman-key --init
sudo pacman-key --populate
sudo pacman -Sy --quiet --noconfirm
""")

        parts.append("sudo pacman -S --needed --noconfirm btrfs-progs")
        parts.append("sudo sed -i -e 's/File/Path/' /usr/share/libalpm/hooks/*hook* 2>/dev/null || true")
        parts.append("""
sudo mknod -m 660 /dev/sr0 b 11 0 2>/dev/null || true
for i in $(seq 0 7); do
    sudo mknod -m 660 /dev/loop$i b 7 $i 2>/dev/null || true
done
sudo mknod -m 660 /dev/loop-control c 10 237 2>/dev/null || true
""")

        # If using local iso-profiles, copy them before build-iso.sh runs
        # This prevents build-iso.sh from cloning over them
        if self.iso_profiles_source == "local" and self.iso_profiles_local_path:
            parts.append("""
if [[ "${USE_LOCAL_ISO_PROFILES:-}" == "true" ]] && [[ -d /root/gitrepo-input/iso-profiles ]]; then
    echo "Using local iso-profiles..."
    rm -rf /root/gitrepo-build/work/iso-profiles
    cp -a /root/gitrepo-input/iso-profiles /root/gitrepo-build/work/iso-profiles
    sed -i '/^clone_iso_profiles() {/,/^}/c\\clone_iso_profiles() { msg "Using local iso-profiles (clone skipped)"; git config --global --add safe.directory "$WORK_PATH_ISO_PROFILES" 2>/dev/null || true; }' /root/gitrepo-build/build-iso/build-iso.sh
fi
""")

        parts.append("""
cd /root/gitrepo-build/build-iso
bash ./build-iso.sh
{ [ -d "$WORK_PATH_ISO_PROFILES/.git" ] && echo "GITREPO-MANIFEST iso-profiles $(git -C "$WORK_PATH_ISO_PROFILES" rev-parse HEAD)"; } || true
find /root/gitrepo-build/work -maxdepth 1 -type f \\( -name '*.iso' -o -name '*.iso.pkgs' \\) -exec mv -t /root/gitrepo-build/output -- {} +
test "$(find /root/gitrepo-build/output -maxdepth 1 -type f -name '*.iso' | wc -l)" -eq 1
""")

        return "\n".join(cmd.strip() for cmd in parts)

    def _run_container(self) -> bool:
        volumes = []

        env_vars = [
            "-e",
            "USERNAME=root",
            "-e",
            f"BUILD_ISO_REPO={BUILD_ISO_REPO}",
            "-e",
            f"DISTRONAME={self.distroname}",
            "-e",
            f"EDITION={self.edition}",
            "-e",
            f"MANJARO_BRANCH={self.branches.get('manjaro', 'stable')}",
            "-e",
            f"BIGLINUX_BRANCH={self.branches.get('biglinux', 'stable')}",
            "-e",
            f"BIGCOMMUNITY_BRANCH={self.branches.get('community', '')}",
            "-e",
            f"KERNEL={self.kernel}",
            "-e",
            f"ISO_PROFILES_REPO={self.iso_profiles_repo}",
            "-e",
            f"RELEASE_TAG={self.release_tag}",
            "-e",
            "LOCAL_BUILD=true",
            "-e",
            "HOME_FOLDER=/root",
            "-e",
            f"WORK_PATH={_CONTAINER_WORK}",
            "-e",
            f"WORK_PATH_ISO_PROFILES={_CONTAINER_WORK}/iso-profiles",
            "-e",
            f"DISTRONAME_ISOPROFILES={self.build_dir}",
            "-e",
            f"PROFILE_PATH={_CONTAINER_WORK}/iso-profiles/{self.build_dir}",
            "-e",
            f"PROFILE_PATH_EDITION={_CONTAINER_WORK}/iso-profiles/{self.build_dir}/{self.edition}",
            "-e",
            "PATH_MANJARO_ISO_PROFILES=/usr/share/manjaro-tools/iso-profiles",
            "-e",
            "PATH_MANJARO_TOOLS=/usr/share/manjaro-tools",
            "-e",
            "VAR_CACHE_MANJARO_TOOLS=/var/cache/manjaro-tools",
            "-e",
            "VAR_CACHE_MANJARO_TOOLS_ISO=/var/cache/manjaro-tools/iso",
        ]

        # Mount local iso-profiles if using local source
        if self.iso_profiles_source == "local" and self.iso_profiles_local_path:
            local_path = str(Path(self.iso_profiles_local_path).expanduser().resolve())
            if os.path.isdir(local_path) and not os.path.islink(local_path):
                volumes.extend(["-v", f"{local_path}:{_CONTAINER_LOCAL_PROFILES}:ro"])
                env_vars.extend(["-e", "USE_LOCAL_ISO_PROFILES=true"])
                self._log("cyan", _("Using local iso-profiles: {0}").format(local_path))
            else:
                self._log("red", _("Local iso-profiles path not found: {0}").format(local_path))
                return False

        self._container_name = f"gitrepo-build-iso-{time.time_ns()}"

        cmd = (
            [
                self.container_engine,
                "run",
                "--label",
                ISO_BUILDER_LABEL,
                "--user",
                "0:0",
                "--cap-add",
                "SYS_ADMIN",
                "--security-opt",
                "apparmor=unconfined",
                "--device-cgroup-rule",
                "b 7:* rwm",
                "--device-cgroup-rule",
                "c 10:237 rwm",
                "--device-cgroup-rule",
                "b 11:* rwm",
                "--mount",
                "type=volume,destination=/var/lib/manjaro-tools/buildiso",
                "--mount",
                "type=volume,destination=/var/cache/manjaro-tools/iso",
                "--name",
                self._container_name,
            ]
            + volumes
            + env_vars
            + [
                "-w",
                "/root",
                self.container_image,
                "bash",
                "-c",
                self._build_setup_script(),
            ]
        )

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
        if not self._own_process(process):
            self._force_remove_container()
            return False

        try:
            for record, replaces_line in iter_terminal_records(process.stdout):
                self._handle_container_record(record, replaces_line)
                if self.is_cancelled:
                    break
            process.wait()
        finally:
            self._release_process(process)

        if self.is_cancelled:
            self._log("yellow", _("Stopping container..."))
            self._force_remove_container()
            return False
        return process.returncode == 0

    def _force_remove_container(self) -> None:
        """Stop and remove this build's container, bounded so it cannot hang."""
        if not self._container_name or not self.container_engine:
            return
        for argv in (
            [self.container_engine, "stop", "-t", "3", self._container_name],
            [self.container_engine, "rm", "-f", "-v", self._container_name],
        ):
            try:
                subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=60)
            except subprocess.SubprocessError:
                self._log("yellow", _("Could not remove the build container {0}.").format(self._container_name))

    def _publish_container_artifacts(self) -> str:
        """Copy validated artifacts to private staging and publish the ISO last."""
        output = Path(self.output_dir)
        output.mkdir(mode=0o755, parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".gitrepo-iso-", dir=output))
        try:
            result = subprocess.run(
                [self.container_engine, "cp", f"{self._container_name}:{_CONTAINER_OUTPUT}/.", str(staging)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self._log("red", result.stdout.strip() or _("Failed to copy ISO artifacts from container"))
                return ""
            validated = self._validate_staged_artifacts(staging)
            if validated is None:
                return ""
            iso_file, entries = validated
            iso_path, checksum = self._publish_staged_artifacts(output, iso_file, entries)
            self._log("green", _("ISO: {0}").format(Path(iso_path).name))
            self._log("cyan", f"MD5: {checksum}")
            return iso_path
        except (OSError, subprocess.SubprocessError, IndexError) as error:
            self._log("red", _("Failed to publish ISO artifacts: {0}").format(error))
            return ""
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _validate_staged_artifacts(self, staging: Path) -> tuple[Path, list[Path]] | None:
        entries = list(staging.iterdir())
        if any(entry.is_symlink() or not entry.is_file() for entry in entries):
            self._log("red", _("Container output contains an unsafe file"))
            return None
        if any(not (entry.name.endswith(".iso") or entry.name.endswith(".iso.pkgs")) for entry in entries):
            self._log("red", _("Container output contains an unexpected file"))
            return None
        iso_files = [entry for entry in entries if entry.name.endswith(".iso")]
        if len(iso_files) != 1:
            self._log("red", _("Container must produce exactly one ISO file"))
            return None
        allowed_names = {iso_files[0].name, f"{iso_files[0].name}.pkgs"}
        if any(entry.name not in allowed_names for entry in entries):
            self._log("red", _("Container output contains an unexpected file"))
            return None
        return iso_files[0], entries

    @staticmethod
    def _available_artifact_name(output: Path, iso_file: Path, entries: list[Path]) -> str:
        sequence = 0
        while True:
            suffix = "" if sequence == 0 else f"-{sequence}"
            candidate = f"{iso_file.stem}{suffix}{iso_file.suffix}"
            related_names = [f"{candidate}{entry.name.removeprefix(iso_file.name)}" for entry in entries]
            related_names.append(f"{candidate}.md5")
            if not any((output / name).exists() or (output / name).is_symlink() for name in related_names):
                return candidate
            sequence += 1

    @staticmethod
    def _file_checksum(path: Path) -> str:
        """Return the MD5 of *path* without depending on an external binary.

        MD5 is the checksum format the published ISO family already uses for
        transfer integrity. It is not a security control here, so it is
        declared as such rather than silenced.
        """
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _publish_one(source: Path, destination: Path) -> None:
        """Create *destination* from *source*, never overwriting an existing name.

        os.link is preferred: it costs nothing for a multi-gigabyte ISO and it
        fails outright on a name another process created in between, which a
        name check followed by os.replace() would silently clobber.

        Filesystems without hardlinks reject it -- exFAT and FAT, the obvious
        place to put a 4 GB ISO, and CIFS without unix extensions. Falling back
        to an exclusive create plus a copy keeps the same never-clobber
        guarantee, because O_EXCL is what refuses the existing name.
        """
        try:
            os.link(source, destination)
            return
        except FileExistsError:
            raise
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK}:
                raise

        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with open(descriptor, "wb", closefd=True) as target, source.open("rb") as stream:
                shutil.copyfileobj(stream, target, 4 * 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def _publish_staged_artifacts(self, output: Path, iso_file: Path, entries: list[Path]) -> tuple[str, str]:
        checksum = self._file_checksum(iso_file)
        artifact_name = self._available_artifact_name(output, iso_file, entries)
        checksum_file = iso_file.with_suffix(f"{iso_file.suffix}.md5")
        atomic_write_text(checksum_file, f"{checksum}  {artifact_name}\n", mode=0o644)
        files_to_publish = [entry for entry in entries if entry != iso_file] + [checksum_file, iso_file]
        destinations = [
            output / f"{artifact_name}{source.name.removeprefix(iso_file.name)}" for source in files_to_publish
        ]

        published: list[Path] = []
        try:
            for source, destination in zip(files_to_publish, destinations, strict=True):
                try:
                    os.chmod(source, 0o644)
                except OSError:
                    # A mode-less filesystem derives permissions from its mount
                    # options; that is not a reason to discard a finished ISO.
                    pass
                with source.open("rb") as stream:
                    os.fsync(stream.fileno())
                self._publish_one(source, destination)
                published.append(destination)

            # Sources are dropped only once the whole family is in place.
            # Unlinking as we went would make an already-published destination
            # the only copy of those bytes, which the rollback below would then
            # delete -- losing artifacts the build had actually produced.
            for source in files_to_publish:
                source.unlink(missing_ok=True)

            directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as error:
            self._rollback_published(published)
            raise FileExistsError(_("An ISO artifact with the same name already exists")) from error
        except Exception:
            self._rollback_published(published)
            raise
        return str(output / artifact_name), checksum

    @staticmethod
    def _rollback_published(published: list[Path]) -> None:
        """Remove only the paths this publication created."""
        for path in published:
            path.unlink(missing_ok=True)

    def _cleanup_containers(self):
        if not self._container_name:
            return
        try:
            subprocess.run(
                [self.container_engine, "rm", "-f", "-v", self._container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
