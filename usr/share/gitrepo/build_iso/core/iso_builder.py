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

from gitrepo.build_iso.core.config import BUILD_ENGINE_REPO, CONTAINER_IMAGE
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
_CONTAINER_OUTPUT = f"{_CONTAINER_ROOT}/output"
# The build engine is iso-profiles/build-iso/build-iso.sh -- the same code the
# GitLab pipeline and the GitHub workflow run. For BigLinux the engine checkout
# also provides the profiles; other distributions bring their own profiles
# checkout (see _CONTAINER_PROFILES and PROFILES_ROOT in the engine).
_CONTAINER_ENGINE = f"{_CONTAINER_ROOT}/iso-profiles"
_CONTAINER_PROFILES = f"{_CONTAINER_ROOT}/profiles"
_CONTAINER_LOCAL_PROFILES = "/root/gitrepo-input/iso-profiles"


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
    if any(marker in normalized for marker in ("buildiso -p", "start building [")):
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
        # The engine owns the default. Keep this only for a caller that
        # explicitly asks to override it.
        self.build_mirror = config.get("build_mirror") or None

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

    def _uses_local_profiles(self) -> bool:
        """Whether the profiles come from a directory on this machine."""
        return self.iso_profiles_source == "local" and bool(self.iso_profiles_local_path)

    def _uses_separate_profiles(self) -> bool:
        """Whether the profiles come from somewhere other than the engine checkout.

        The engine lives inside biglinux/iso-profiles, which for BigLinux is
        also the profiles repository. A local profiles directory or another
        distribution's repository (bigcommunity) is built via the engine's
        PROFILES_ROOT override.
        """
        if self._uses_local_profiles():
            return True
        repo = (self.iso_profiles_repo or "").rstrip("/").removesuffix(".git")
        engine = BUILD_ENGINE_REPO.rstrip("/").removesuffix(".git")
        return bool(repo) and repo != engine

    def _build_setup_script(self) -> str:
        """Setup script that runs inside the container.

        The build itself is iso-profiles/build-iso/build-iso.sh -- the same
        engine the GitLab pipeline and the GitHub workflow run. This script
        only fetches it, decides which profiles checkout it builds from, and
        asserts the output.
        """
        if self.build_mirror is not None and not BUILD_MIRROR_URL.match(self.build_mirror):
            raise ValueError(f"refusing an unsafe build mirror URL: {self.build_mirror!r}")

        parts = [
            f"""
set -eo pipefail
umask 022
mkdir -p {_CONTAINER_OUTPUT}
git clone --depth 1 "$ENGINE_REPO" {_CONTAINER_ENGINE}
echo "GITREPO-MANIFEST iso-profiles $(git -C {_CONTAINER_ENGINE} rev-parse HEAD)"
"""
        ]

        if self._uses_local_profiles():
            # The engine edits the profiles in place, so it gets a copy of the
            # read-only mount.
            parts.append(f"""
echo "Using local iso-profiles..."
rm -rf {_CONTAINER_PROFILES}
cp -a {_CONTAINER_LOCAL_PROFILES} {_CONTAINER_PROFILES}
""")
        elif self._uses_separate_profiles():
            parts.append(f"""
git clone --depth 1 "$ISO_PROFILES_REPO" {_CONTAINER_PROFILES}
echo "GITREPO-MANIFEST profiles $(git -C {_CONTAINER_PROFILES} rev-parse HEAD)"
""")

        parts.append(f"""
bash {_CONTAINER_ENGINE}/build-iso/build-iso.sh
test "$(find {_CONTAINER_OUTPUT} -maxdepth 1 -type f -name '*.iso' | wc -l)" -eq 1
""")

        return "\n".join(cmd.strip() for cmd in parts)

    def _run_container(self) -> bool:
        volumes = []

        # Environment contract of iso-profiles/build-iso/build-iso.sh; see the
        # engine's header for every variable and its default.
        env_vars = [
            "-e",
            f"ENGINE_REPO={BUILD_ENGINE_REPO}",
            "-e",
            f"ISO_PROFILES_REPO={self.iso_profiles_repo}",
            "-e",
            f"DISTRONAME={self.distroname}",
            "-e",
            f"EDITION={self.edition}",
            "-e",
            f"KERNEL={self.kernel}",
            "-e",
            f"MANJARO_BRANCH={self.branches.get('manjaro') or 'stable'}",
            "-e",
            f"BIGLINUX_BRANCH={self.branches.get('biglinux') or 'stable'}",
            "-e",
            f"BIGCOMMUNITY_BRANCH={self.branches.get('community') or 'stable'}",
            "-e",
            f"RELEASE_TAG={self.release_tag}",
            "-e",
            f"WORK_PATH={_CONTAINER_OUTPUT}",
        ]
        if self.build_mirror is not None:
            env_vars.extend(["-e", f"BUILD_MIRROR={self.build_mirror}"])
        if self._uses_separate_profiles():
            env_vars.extend(["-e", f"PROFILES_ROOT={_CONTAINER_PROFILES}"])

        # Mount local iso-profiles if using local source
        if self._uses_local_profiles():
            local_path = str(Path(self.iso_profiles_local_path).expanduser().resolve())
            if os.path.isdir(local_path) and not os.path.islink(local_path):
                volumes.extend(["-v", f"{local_path}:{_CONTAINER_LOCAL_PROFILES}:ro"])
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
