#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/iso_builder.py - ISO build orchestration adapted for GUI
#
# Wraps the existing local_builder.py logic with a GUI-friendly interface
# that reports progress via callbacks instead of direct console output.
#

import json
import os
import re
import subprocess
import shutil
import threading
import time
from datetime import datetime

from core.config import BUILD_ISO_REPO, CONTAINER_IMAGE, ISO_PROFILES_REPOS
from core.translation_utils import _

# Regex to strip ANSI escape codes from container output
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')


class ISOBuilder:
    """ISO build orchestration with callback-based progress reporting"""

    # Build phases for progress estimation
    # container_build is the longest phase (10-50 min), so it gets 10%-90% range
    PHASES = [
        ("check_engine", 0.02),
        ("check_storage", 0.03),
        ("pull_image", 0.06),
        ("prepare_dirs", 0.07),
        ("clone_build_repo", 0.09),
        ("container_build", 0.10),
        ("move_files", 0.95),
        ("cleanup", 1.0),
    ]

    def __init__(self, config: dict, callbacks: dict = None):
        """
        Args:
            config: Build configuration dict (from Settings.get_build_config())
            callbacks: Dict of callback functions:
                - on_log(color, message): Log message
                - on_progress(fraction, phase_text): Progress update 0.0-1.0
                - on_phase(phase_name): Phase change notification
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
        self.clean_cache = config.get("clean_cache", False)
        self.clean_cache_after = config.get("clean_cache_after_build", False)

        self.container_engine = self._resolve_engine(config.get("container_engine", "docker"))
        self.container_image = config.get("container_image", CONTAINER_IMAGE)

        self.release_tag = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.work_path = os.path.join(self.output_dir, "work")
        self.cache_path = os.path.join(self.output_dir, "cache")

        self._callbacks = callbacks or {}
        self._cancelled = threading.Event()
        self._container_name = ""
        self._build_process = None

    @staticmethod
    def _resolve_engine(engine: str) -> str:
        """Resolve 'auto' engine to actual docker/podman binary"""
        if engine in ("docker", "podman"):
            return engine
        # Auto-detect: prefer docker, fallback to podman
        for eng in ("docker", "podman"):
            if shutil.which(eng):
                return eng
        return "docker"  # fallback

    def _log(self, color: str, message: str):
        cb = self._callbacks.get("on_log")
        if cb:
            cb(color, message)

    def _progress(self, fraction: float, text: str = ""):
        cb = self._callbacks.get("on_progress")
        if cb:
            cb(fraction, text)

    def _phase(self, name: str):
        cb = self._callbacks.get("on_phase")
        if cb:
            cb(name)
        # Auto-set progress based on phase
        for phase_name, fraction in self.PHASES:
            if phase_name == name:
                self._progress(fraction, name)
                break

    def cancel(self):
        """Request build cancellation and stop running container"""
        self._cancelled.set()
        # Kill running container in a thread to avoid blocking UI
        if self._container_name and self.container_engine:
            def _stop():
                subprocess.run(
                    ["sudo", self.container_engine, "stop", "-t", "2", self._container_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
                subprocess.run(
                    ["sudo", self.container_engine, "rm", "-f", self._container_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
            threading.Thread(target=_stop, daemon=True).start()
        # Kill the subprocess if running
        if self._build_process and self._build_process.poll() is None:
            self._build_process.kill()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def execute(self) -> dict:
        """
        Execute the full build pipeline.
        Returns dict: {"success": bool, "iso_path": str, "error": str, "duration": int}
        """
        import getpass
        import re

        start_time = time.time()
        result = {"success": False, "iso_path": "", "error": "", "duration": 0}
        sudoers_file = "/etc/sudoers.d/build-iso-gui"

        try:
            # Get current username (sanitize for sudoers safety)
            username = getpass.getuser()
            if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
                result["error"] = _("Invalid username for sudo configuration")
                return result

            # Use pkexec to create temporary passwordless sudo entry
            # This gives the same behavior as CLI: authenticate once, sudo works for the session
            self._log("cyan", _("Requesting authentication for privileged operations..."))
            setup_cmd = (
                f"echo '{username} ALL=(ALL) NOPASSWD: ALL' > {sudoers_file} && "
                f"chmod 440 {sudoers_file}"
            )
            pkexec_proc = subprocess.Popen(
                ["pkexec", "bash", "-c", setup_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            while pkexec_proc.poll() is None:
                if self.is_cancelled:
                    pkexec_proc.kill()
                    result["error"] = _("Build cancelled")
                    result["duration"] = int(time.time() - start_time)
                    return result
                time.sleep(0.2)
            if pkexec_proc.returncode != 0:
                result["error"] = _("Authentication required for build operations")
                return result

            # Verify sudo now works without password
            sr = subprocess.run(["sudo", "-n", "true"], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if sr.returncode != 0:
                result["error"] = _("Failed to configure sudo access")
                return result

            self._log("green", _("Authentication successful"))

            # Start sudo keepalive (same as CLI version)
            sudo_stop = threading.Event()
            sudo_thread = threading.Thread(target=self._sudo_keepalive, args=(sudo_stop,), daemon=True)
            sudo_thread.start()

            try:
                # Phase: Check storage driver
                self._phase("check_storage")
                if self.container_engine == "docker":
                    if not self._check_and_fix_storage():
                        result["error"] = _("Failed to configure Docker storage driver")
                        return result

                if self.is_cancelled:
                    result["error"] = _("Build cancelled")
                    return result

                # Phase: Disk space
                self._log("cyan", _("Checking disk space..."))
                free_gb = shutil.disk_usage(self.output_dir).free / (1024 ** 3) if os.path.exists(self.output_dir) else 0
                os.makedirs(self.output_dir, exist_ok=True)
                free_gb = shutil.disk_usage(self.output_dir).free / (1024 ** 3)
                self._log("cyan", _("Disk space available: {0:.1f} GB").format(free_gb))
                if free_gb < 20:
                    self._log("yellow", _("Warning: Only {0:.1f} GB free. 20 GB recommended.").format(free_gb))

                if self.is_cancelled:
                    result["error"] = _("Build cancelled")
                    return result

                # Phase: Pull image
                self._phase("pull_image")
                self._log("cyan", _("Pulling container image: {0}").format(self.container_image))
                if not self._pull_image():
                    result["error"] = _("Failed to pull container image")
                    return result

                if self.is_cancelled:
                    result["error"] = _("Build cancelled")
                    return result

                # Phase: Prepare directories
                self._phase("prepare_dirs")
                if not self._prepare_directories():
                    result["error"] = _("Failed to prepare build directories")
                    return result

                # Phase: Clone build-iso repo
                self._phase("clone_build_repo")
                if not self._clone_build_repo():
                    result["error"] = _("Failed to clone build-iso repository")
                    return result

                if self.is_cancelled:
                    result["error"] = _("Build cancelled")
                    return result

                # Phase: Container build (the long one)
                self._phase("container_build")
                self._log("cyan", _("Starting container build..."))
                self._log("yellow", _("This may take 10-50 minutes depending on your hardware and network."))
                if not self._run_container():
                    result["error"] = _("Container build failed")
                    self._log("yellow", _("Work directory preserved for debugging: {0}").format(self.work_path))
                    return result

                # Phase: Move files
                self._phase("move_files")
                iso_path = self._move_iso_files()
                if not iso_path:
                    result["error"] = _("No ISO files found after build")
                    return result

                # Phase: Cleanup
                self._phase("cleanup")
                if self.clean_cache_after:
                    self._cleanup_cache()
                self._cleanup_containers()

                result["success"] = True
                result["iso_path"] = iso_path
                self._log("green", _("Build completed successfully!"))
                self._log("cyan", _("ISO saved to: {0}").format(iso_path))

            finally:
                sudo_stop.set()
                if sudo_thread.is_alive():
                    sudo_thread.join(timeout=2)
                # Remove temporary sudoers entry
                subprocess.run(["sudo", "rm", "-f", sudoers_file],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        except Exception as e:
            result["error"] = str(e)
            self._log("red", _("Unexpected error: {0}").format(str(e)))

        result["duration"] = int(time.time() - start_time)
        return result

    def _sudo_keepalive(self, stop_event: threading.Event):
        """Keep sudo credentials alive during the build"""
        while not stop_event.is_set():
            subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            stop_event.wait(60)

    def _check_and_fix_storage(self) -> bool:
        """Check Docker storage driver and auto-fix btrfs to overlay2"""
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.Driver}}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False,
            )
            driver = result.stdout.strip()
            if driver != "btrfs":
                return True

            self._log("yellow", _("Docker is using deprecated 'btrfs' storage driver"))
            self._log("cyan", _("Automatically switching to 'overlay2'..."))

            # Stop Docker
            subprocess.run(["sudo", "systemctl", "stop", "docker.socket"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run(["sudo", "systemctl", "stop", "docker"], check=True)

            # Write daemon.json
            daemon_json = "/etc/docker/daemon.json"
            existing = {}
            try:
                r = subprocess.run(["sudo", "cat", daemon_json], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
                if r.returncode == 0 and r.stdout.strip():
                    existing = json.loads(r.stdout)
            except Exception:
                pass
            existing["storage-driver"] = "overlay2"
            subprocess.run(["sudo", "tee", daemon_json], input=json.dumps(existing, indent=2) + "\n", text=True, stdout=subprocess.DEVNULL, check=True)

            # Remove old storage and restart
            subprocess.run(["sudo", "rm", "-rf", "/var/lib/docker"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "docker"], check=True)

            # Verify
            for _attempt in range(10):
                r = subprocess.run(["docker", "info", "--format", "{{.Driver}}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
                if r.returncode == 0 and r.stdout.strip() == "overlay2":
                    self._log("green", _("Docker switched to overlay2 successfully"))
                    return True
                time.sleep(1)

            self._log("red", _("Failed to switch Docker to overlay2"))
            return False

        except Exception as e:
            self._log("red", _("Error fixing Docker storage: {0}").format(str(e)))
            subprocess.run(["sudo", "systemctl", "start", "docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return False

    def _pull_image(self) -> bool:
        process = subprocess.Popen(
            [self.container_engine, "pull", self.container_image],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in process.stdout:
            line = line.rstrip()
            if line:
                self._log("dim", f"  {line}")
            if self.is_cancelled:
                process.kill()
                return False
        process.wait()
        if process.returncode == 0:
            self._log("green", _("Container image pulled successfully"))
            return True
        self._log("red", _("Failed to pull container image"))
        return False

    def _prepare_directories(self) -> bool:
        self._log("cyan", _("Preparing build directories..."))
        try:
            if os.path.exists(self.work_path):
                try:
                    shutil.rmtree(self.work_path)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-rf", self.work_path], check=True)

            if self.clean_cache and os.path.exists(self.cache_path):
                try:
                    shutil.rmtree(self.cache_path)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-rf", self.cache_path], check=True)

            for d in [
                self.work_path,
                self.cache_path,
                os.path.join(self.cache_path, "var_lib_manjaro_tools_buildiso"),
                os.path.join(self.cache_path, "var_cache_manjaro_tools_iso"),
            ]:
                os.makedirs(d, exist_ok=True)

            subprocess.run(["chmod", "-R", "777", self.work_path], check=False)
            subprocess.run(["chmod", "-R", "777", self.cache_path], check=False)
            return True
        except Exception as e:
            self._log("red", _("Error creating directories: {0}").format(str(e)))
            return False

    def _clone_build_repo(self) -> bool:
        self._log("cyan", _("Cloning build-iso repository..."))
        build_iso_path = os.path.join(self.work_path, "build-iso")
        if os.path.exists(build_iso_path):
            shutil.rmtree(build_iso_path, ignore_errors=True)

        result = subprocess.run(
            ["git", "clone", BUILD_ISO_REPO, build_iso_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )
        if result.returncode == 0:
            # Ensure container can write to cloned files (needed for sed -i inside container)
            subprocess.run(["chmod", "-R", "777", build_iso_path], check=False)
            self._log("green", _("Build script prepared"))
            return True
        self._log("red", _("Failed to clone build-iso repository"))
        return False

    def _build_setup_script(self) -> str:
        """Build setup script that runs inside container before build-iso.sh"""
        parts = []

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

        parts.append("""
sudo pacman-key --init
sudo pacman-key --populate
sudo pacman -Sy --quiet --noconfirm
""")

        parts.append("sudo pacman -S --needed --noconfirm btrfs-progs")
        parts.append("sudo sed -i -e 's/File/Path/' /usr/share/libalpm/hooks/*hook* 2>/dev/null || true")
        parts.append("""
sudo mknod /dev/sr0 b 11 0 2>/dev/null || true
sudo chmod 660 /dev/sr0 2>/dev/null || true
sudo chown root:root /dev/sr0 2>/dev/null || true
for i in $(seq 0 7); do
    sudo mknod -m 660 /dev/loop$i b 7 $i 2>/dev/null || true
done
sudo mknod -m 660 /dev/loop-control c 10 237 2>/dev/null || true
""")

        # If using local iso-profiles, copy them before build-iso.sh runs
        # This prevents build-iso.sh from cloning over them
        if self.iso_profiles_source == "local" and self.iso_profiles_local_path:
            parts.append("""
if [[ "${USE_LOCAL_ISO_PROFILES:-}" == "true" ]] && [[ -d /work/local-iso-profiles ]]; then
    echo "Using local iso-profiles..."
    rm -rf /work/iso-profiles 2>/dev/null || true
    cp -a /work/local-iso-profiles /work/iso-profiles
    # Override clone_iso_profiles function in build-iso.sh to skip cloning
    sed -i '/^clone_iso_profiles() {/,/^}/c\\clone_iso_profiles() { msg "Using local iso-profiles (clone skipped)"; git config --global --add safe.directory /work/iso-profiles 2>/dev/null || true; }' /work/build-iso/build-iso.sh
fi
""")

        parts.append("cd /work/build-iso && bash ./build-iso.sh")

        return " && ".join(cmd.strip() for cmd in parts)

    def _run_container(self) -> bool:
        volumes = [
            "-v", f"{self.work_path}:/work",
            "-v", f"{os.path.join(self.cache_path, 'var_lib_manjaro_tools_buildiso')}:/var/lib/manjaro-tools/buildiso",
            "-v", f"{os.path.join(self.cache_path, 'var_cache_manjaro_tools_iso')}:/var/cache/manjaro-tools/iso",
        ]

        env_vars = [
            "-e", "USERNAME=builduser",
            "-e", f"DISTRONAME={self.distroname}",
            "-e", f"EDITION={self.edition}",
            "-e", f"MANJARO_BRANCH={self.branches.get('manjaro', 'stable')}",
            "-e", f"BIGLINUX_BRANCH={self.branches.get('biglinux', 'stable')}",
            "-e", f"BIGCOMMUNITY_BRANCH={self.branches.get('community', '')}",
            "-e", f"KERNEL={self.kernel}",
            "-e", f"ISO_PROFILES_REPO={self.iso_profiles_repo}",
            "-e", f"RELEASE_TAG={self.release_tag}",
            "-e", "LOCAL_BUILD=true",
            "-e", "HOME_FOLDER=/home/builduser",
            "-e", "WORK_PATH=/work",
            "-e", "WORK_PATH_ISO_PROFILES=/work/iso-profiles",
            "-e", f"DISTRONAME_ISOPROFILES={self.build_dir}",
            "-e", f"PROFILE_PATH=/work/iso-profiles/{self.build_dir}",
            "-e", f"PROFILE_PATH_EDITION=/work/iso-profiles/{self.build_dir}/{self.edition}",
            "-e", "PATH_MANJARO_ISO_PROFILES=/usr/share/manjaro-tools/iso-profiles",
            "-e", "PATH_MANJARO_TOOLS=/usr/share/manjaro-tools",
            "-e", "VAR_CACHE_MANJARO_TOOLS=/var/cache/manjaro-tools",
            "-e", "VAR_CACHE_MANJARO_TOOLS_ISO=/var/cache/manjaro-tools/iso",
        ]

        # Mount local iso-profiles if using local source
        if self.iso_profiles_source == "local" and self.iso_profiles_local_path:
            local_path = os.path.abspath(self.iso_profiles_local_path)
            if os.path.isdir(local_path):
                volumes.extend(["-v", f"{local_path}:/work/local-iso-profiles:ro"])
                env_vars.extend(["-e", "USE_LOCAL_ISO_PROFILES=true"])
                self._log("cyan", _("Using local iso-profiles: {0}").format(local_path))
            else:
                self._log("red", _("Local iso-profiles path not found: {0}").format(local_path))
                return False

        self._container_name = f"build-iso-{int(time.time())}"

        cmd = [
            self.container_engine, "run",
            "--privileged", "--rm", "--network=host",
            "--name", self._container_name,
        ] + volumes + env_vars + [
            "-w", "/work/build-iso",
            self.container_image,
            "bash", "-c", self._build_setup_script(),
        ]

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self._build_process = process

        # Progress tracking for the container build phase (10% → 90%)
        # Uses exponential decay curve: starts slow, approaches 85% asymptotically
        # Only late-stage milestones (squashfs, xorriso) trigger jumps
        import math
        build_start = time.time()
        last_progress = 0.10
        # Time constant: at 600s (10min) ~47%, at 1200s (20min) ~72%, at 1800s (30min) ~85%
        tau = 900.0

        for line in process.stdout:
            raw_line = line.rstrip()
            clean_line = _ANSI_RE.sub('', raw_line)
            if clean_line:
                self._log("white", raw_line)

                elapsed = time.time() - build_start
                lower = clean_line.lower()

                # Only trigger milestones for unique build-iso.sh stages
                if "mksquashfs" in lower or "creating squashfs" in lower:
                    target = max(last_progress, 0.70)
                elif "xorriso" in lower or "genisoimage" in lower or "mkisofs" in lower:
                    target = max(last_progress, 0.82)
                else:
                    # Exponential decay: progress = 0.10 + 0.75 * (1 - e^(-t/tau))
                    target = 0.10 + 0.75 * (1.0 - math.exp(-elapsed / tau))

                # Only increase, never decrease
                if target > last_progress:
                    last_progress = target
                    self._progress(min(target, 0.90), _("Building ISO in container..."))

            if self.is_cancelled:
                self._log("yellow", _("Stopping container..."))
                process.kill()
                # Force stop the Docker/Podman container
                subprocess.run(
                    ["sudo", self.container_engine, "stop", "-t", "3", self._container_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
                subprocess.run(
                    ["sudo", self.container_engine, "rm", "-f", self._container_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
                return False

        process.wait()
        return process.returncode == 0

    def _move_iso_files(self) -> str:
        """Move ISO files to output dir. Returns path to first ISO or empty string."""
        import pwd
        self._log("cyan", _("Moving ISO files to output directory..."))

        iso_files = [f for f in os.listdir(self.work_path) if f.endswith(".iso")] if os.path.isdir(self.work_path) else []
        if not iso_files:
            return ""

        username = pwd.getpwuid(os.getuid()).pw_name
        first_iso = ""

        for filename in iso_files:
            src = os.path.join(self.work_path, filename)
            dest = os.path.join(self.output_dir, filename)

            try:
                shutil.move(src, dest)
            except PermissionError:
                subprocess.run(["sudo", "mv", src, dest], check=True)

            try:
                subprocess.run(["sudo", "chown", f"{username}:{username}", dest], check=False)
                os.chmod(dest, 0o644)
            except Exception:
                pass

            # Generate MD5
            result = subprocess.run(["md5sum", dest], capture_output=True, text=True, check=True)
            md5 = result.stdout.split()[0]
            with open(f"{dest}.md5", "w") as f:
                f.write(f"{md5}  {filename}\n")

            self._log("green", _("ISO: {0}").format(filename))
            self._log("cyan", f"MD5: {md5}")

            if not first_iso:
                first_iso = dest

        # Cleanup work
        try:
            shutil.rmtree(self.work_path)
        except PermissionError:
            subprocess.run(["sudo", "rm", "-rf", self.work_path], check=False)

        return first_iso

    def _cleanup_cache(self):
        try:
            if os.path.exists(self.cache_path):
                shutil.rmtree(self.cache_path)
        except PermissionError:
            subprocess.run(["sudo", "rm", "-rf", self.cache_path], check=False)
        except Exception:
            pass

    def _cleanup_containers(self):
        try:
            subprocess.run(
                [self.container_engine, "container", "prune", "-f", "--filter", f"ancestor={self.container_image}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except Exception:
            pass
