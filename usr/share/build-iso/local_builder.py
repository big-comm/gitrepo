#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# local_builder.py - Local ISO builder using Docker/Podman containers
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import pwd
import re
import shutil
import subprocess
import threading
from datetime import datetime

from config import BUILD_ISO_REPO, CONTAINER_IMAGE
from translation_utils import _


class LocalBuilder:
    """Executes local ISO builds using Docker/Podman containers"""

    # ANSI escape code pattern for removal
    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*[mGKHJA-Z]')

    @staticmethod
    def strip_ansi_codes(text: str) -> str:
        """Remove ANSI escape codes from text"""
        return LocalBuilder.ANSI_ESCAPE_PATTERN.sub('', text)

    def __init__(self, logger, config: dict):
        """
        Initialize LocalBuilder with configuration

        Args:
            logger: RichLogger instance for output
            config: Dictionary with build configuration:
                - distroname: "bigcommunity" or "biglinux"
                - edition: "gnome", "kde", "xfce", etc.
                - branches: Dict with manjaro, biglinux, community branches
                - kernel: "latest", "lts", "oldlts", "xanmod"
                - iso_profiles_repo: URL of ISO profiles repository
                - build_dir: Directory in repo (e.g., "bigcommunity")
                - output_dir: Output directory (e.g., ~/ISO)
        """
        self.logger = logger
        self.distroname = config.get("distroname", "bigcommunity")
        self.edition = config.get("edition", "gnome")
        self.branches = config.get("branches", {})
        self.kernel = config.get("kernel", "lts")
        self.iso_profiles_repo = config.get("iso_profiles_repo", "")
        self.build_dir = config.get("build_dir", "bigcommunity")
        self.output_dir = os.path.expanduser(config.get("output_dir", "~/ISO"))

        # Generate release tag
        self.release_tag = datetime.now().strftime("%Y-%m-%d_%H-%M")

        # Work paths
        self.work_path = os.path.join(self.output_dir, "work")
        self.cache_path = os.path.join(self.output_dir, "cache")

        # Clean cache flags
        self.clean_cache = config.get("clean_cache", False)  # Before build
        self.clean_cache_after_build = config.get("clean_cache_after_build", False)  # After build

        # Container settings
        self.container_engine = None
        self.container_image = CONTAINER_IMAGE
        self.build_iso_repo = BUILD_ISO_REPO

    def check_container_engine(self) -> bool:
        """
        Detect available container engine (docker or podman)
        Also cleanup any old containers from previous builds

        Returns:
            bool: True if engine found, False otherwise
        """
        for engine in ["docker", "podman"]:
            try:
                result = subprocess.run(
                    ["which", engine],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False
                )
                if result.returncode == 0:
                    self.container_engine = engine
                    self.logger.log("green", _("Container engine found: {0}").format(engine))

                    # Cleanup old containers from previous builds
                    try:
                        # Get list of container IDs with our image
                        result = subprocess.run(
                            [engine, "ps", "-a", "-q", "--filter", f"ancestor={self.container_image}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            text=True,
                            check=False
                        )

                        if result.stdout.strip():
                            container_ids = result.stdout.strip().split('\n')
                            self.logger.log("cyan", _("Stopping {0} old container(s)...").format(len(container_ids)))

                            # Stop containers
                            subprocess.run(
                                [engine, "stop"] + container_ids,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=False,
                                timeout=30
                            )

                            # Remove containers
                            subprocess.run(
                                [engine, "rm"] + container_ids,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=False
                            )
                    except Exception:
                        pass  # Ignore cleanup errors

                    return True
            except Exception:
                continue

        return False

    def check_disk_space(self) -> bool:
        """
        Check if there's enough disk space (~20GB required)

        Returns:
            bool: True if enough space, False otherwise
        """
        try:
            stat = shutil.disk_usage(self.output_dir)
            free_gb = stat.free / (1024**3)

            if free_gb < 20:
                self.logger.log("yellow", _("Warning: Only {0:.1f} GB free. 20 GB recommended.").format(free_gb))
                return False

            self.logger.log("cyan", _("Disk space available: {0:.1f} GB").format(free_gb))
            return True
        except Exception as e:
            self.logger.log("yellow", _("Could not check disk space: {0}").format(str(e)))
            return True  # Don't fail on check error

    def pull_container_image(self) -> bool:
        """
        Pull container image from registry

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Pulling container image: {0}").format(self.container_image))

        cmd = [self.container_engine, "pull", self.container_image]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False
            )

            if result.returncode == 0:
                self.logger.log("green", _("Container image pulled successfully"))
                return True
            else:
                self.logger.log("red", _("Failed to pull container image"))
                if result.stdout:
                    self.logger.log("red", result.stdout)

                # Retry once
                self.logger.log("yellow", _("Retrying..."))
                result = subprocess.run(cmd, check=False)
                return result.returncode == 0

        except Exception as e:
            self.logger.log("red", _("Error pulling container image: {0}").format(str(e)))
            return False

    def prepare_directories(self) -> bool:
        """
        Create work and cache directories
        - Always cleans work/ (temporary files only)
        - Cleans cache/ only if --clean flag is set

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Preparing build directories..."))

        try:
            # Always clean work directory (temporary files)
            if os.path.exists(self.work_path):
                self.logger.log("yellow", _("Cleaning work directory..."))
                try:
                    shutil.rmtree(self.work_path)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-rf", self.work_path], check=True)

            # Clean cache only if --clean flag is set
            if self.clean_cache and os.path.exists(self.cache_path):
                self.logger.log("yellow", _("Cleaning cache directory (--clean flag)..."))
                try:
                    shutil.rmtree(self.cache_path)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-rf", self.cache_path], check=True)
            elif os.path.exists(self.cache_path):
                # Even if not cleaning cache, remove subdirectories to avoid permission issues
                cache_subdirs = [
                    os.path.join(self.cache_path, "var_lib_manjaro_tools_buildiso"),
                    os.path.join(self.cache_path, "var_cache_manjaro_tools_iso")
                ]
                for subdir in cache_subdirs:
                    if os.path.exists(subdir):
                        try:
                            shutil.rmtree(subdir)
                        except PermissionError:
                            subprocess.run(["sudo", "rm", "-rf", subdir], check=True)

            # Create all directories with proper permissions
            directories = [
                self.work_path,
                self.cache_path,
                os.path.join(self.cache_path, "var_lib_manjaro_tools_buildiso"),
                os.path.join(self.cache_path, "var_cache_manjaro_tools_iso")
            ]

            for directory in directories:
                os.makedirs(directory, exist_ok=True)
                self.logger.log("cyan", _("Created: {0}").format(directory))

            # Set permissions (try without sudo first)
            try:
                subprocess.run(["chmod", "-R", "777", self.work_path], check=True)
                subprocess.run(["chmod", "-R", "777", self.cache_path], check=True)
            except subprocess.CalledProcessError:
                # If fails, use sudo
                subprocess.run(["sudo", "chmod", "-R", "777", self.work_path], check=True)
                subprocess.run(["sudo", "chmod", "-R", "777", self.cache_path], check=True)

            return True
        except Exception as e:
            self.logger.log("red", _("Error creating directories: {0}").format(str(e)))
            return False

    def prepare_build_script(self) -> bool:
        """
        Clone build-iso repository to get build-iso.sh script

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Cloning build-iso repository..."))

        build_iso_path = os.path.join(self.work_path, "build-iso")

        # Remove existing clone if present
        if os.path.exists(build_iso_path):
            try:
                shutil.rmtree(build_iso_path)
            except Exception as e:
                self.logger.log("yellow", _("Could not remove old build-iso: {0}").format(str(e)))

        # Clone repository
        cmd = ["git", "clone", self.build_iso_repo, build_iso_path]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False
            )

            if result.returncode == 0:
                self.logger.log("green", _("Build script prepared"))
                return True
            else:
                self.logger.log("red", _("Failed to clone build-iso repository"))
                if result.stdout:
                    self.logger.log("red", result.stdout)

                # Retry once
                self.logger.log("yellow", _("Retrying..."))
                result = subprocess.run(cmd, check=False)
                return result.returncode == 0

        except Exception as e:
            self.logger.log("red", _("Error cloning repository: {0}").format(str(e)))
            return False

    def _build_setup_script(self) -> str:
        """
        Build setup script that runs inside container before build-iso.sh
        This replicates what GitHub Actions does in action.yml lines 142-189

        Returns:
            str: Complete bash script to execute
        """
        setup_commands = []

        # 1. Add community repository if bigcommunity
        if self.distroname == "bigcommunity":
            setup_commands.append("""
echo "[community-extra]" | sudo tee -a /etc/pacman.conf
echo "SigLevel = PackageRequired" | sudo tee -a /etc/pacman.conf
echo "Server = https://repo.communitybig.org/extra/\\$arch" | sudo tee -a /etc/pacman.conf
echo "" | sudo tee -a /etc/pacman.conf
""")

        # 2. Install cryptographic keys
        setup_commands.append("""
# Install BigLinux keys (clone in /tmp to avoid permission issues)
cd /tmp
git clone --depth 1 https://github.com/biglinux/biglinux-key.git
sudo install -dm755 /etc/pacman.d/gnupg/
sudo install -m0644 biglinux-key/usr/share/pacman/keyrings/* /etc/pacman.d/gnupg/
rm -rf biglinux-key
""")

        if self.distroname == "bigcommunity":
            setup_commands.append("""
# Install Community keys (clone in /tmp to avoid permission issues)
cd /tmp
git clone --depth 1 https://github.com/big-comm/community-keyring.git
sudo install -m0644 community-keyring/community.gpg /usr/share/pacman/keyrings/
sudo install -m0644 community-keyring/community-trusted /usr/share/pacman/keyrings/
sudo install -m0644 community-keyring/community-revoked /usr/share/pacman/keyrings/
rm -rf community-keyring
""")

        # 3. Initialize pacman keys and update
        setup_commands.append("""
sudo pacman-key --init
sudo pacman-key --populate
sudo pacman -Sy --quiet --noconfirm
""")

        # 4. Install btrfs-progs
        setup_commands.append("""
sudo pacman -S --needed --noconfirm btrfs-progs
""")

        # 5. Adjust mkinitcpio hooks (from action.yml line 182-183)
        setup_commands.append("""
sudo sed -i -e 's/File/Path/' /usr/share/libalpm/hooks/*hook* 2>/dev/null || true
""")

        # 6. Create device nodes (from action.yml line 186-189)
        setup_commands.append("""
sudo mknod /dev/sr0 b 11 0 2>/dev/null || true
sudo chmod 660 /dev/sr0 2>/dev/null || true
sudo chown root:root /dev/sr0 2>/dev/null || true

# Create loop devices (needed by buildiso for EFI image mounting)
for i in $(seq 0 7); do
    sudo mknod -m 660 /dev/loop$i b 7 $i 2>/dev/null || true
done
sudo mknod -m 660 /dev/loop-control c 10 237 2>/dev/null || true
""")

        # 7. Return to build-iso directory and execute build-iso.sh
        setup_commands.append("cd /work/build-iso && bash ./build-iso.sh")

        # Join all commands
        return " && ".join(cmd.strip() for cmd in setup_commands)

    def run_container_build(self) -> bool:
        """
        Execute Docker/Podman container to build ISO

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Starting container build..."))
        self.logger.log("yellow", _("This may take 10-50 minutes depending on your hardware and network."))

        # Build command following edition.yml:87-93 and action.yml:191-224
        cmd = [
            self.container_engine, "run",
            "--privileged",
            "--rm",
            "--network=host",
            "-v", f"{self.work_path}:/work",
            "-v", f"{os.path.join(self.cache_path, 'var_lib_manjaro_tools_buildiso')}:/var/lib/manjaro-tools/buildiso",
            "-v", f"{os.path.join(self.cache_path, 'var_cache_manjaro_tools_iso')}:/var/cache/manjaro-tools/iso",
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
            "-w", "/work/build-iso",
            self.container_image,
            "bash", "-c", self._build_setup_script()
        ]

        try:
            # Run with direct output to terminal (no processing - works best)
            result = subprocess.run(cmd, check=False)

            if result.returncode == 0:
                self.logger.log("green", _("Container build completed successfully"))
                return True
            else:
                self.logger.log("red", _("Container build failed with exit code {0}").format(result.returncode))
                return False

        except Exception:
            self.logger.log("red", _("Error running container"))
            return False

    def move_iso_files(self) -> bool:
        """
        Move generated ISO files from work directory to output directory,
        generate MD5 checksums, fix permissions, and cleanup temporary files

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Moving ISO files to output directory..."))

        try:
            # Find ISO files in work directory (where build-iso.sh puts them)
            iso_files = []
            for file in os.listdir(self.work_path):
                if file.endswith(".iso"):
                    iso_files.append(os.path.join(self.work_path, file))

            if not iso_files:
                self.logger.log("yellow", _("No ISO files found in work directory"))
                return False

            # Move each ISO file, generate MD5, fix permissions
            username = pwd.getpwuid(os.getuid()).pw_name
            for iso_file in iso_files:
                filename = os.path.basename(iso_file)
                dest = os.path.join(self.output_dir, filename)

                # Move ISO file
                self.logger.log("cyan", _("Moving: {0}").format(filename))
                try:
                    shutil.move(iso_file, dest)
                except PermissionError:
                    subprocess.run(["sudo", "mv", iso_file, dest], check=True)

                # Always fix ownership (file may be owned by container user)
                try:
                    # Check if we're the owner
                    file_stat = os.stat(dest)
                    if file_stat.st_uid != os.getuid():
                        # Need to change owner
                        subprocess.run(["sudo", "chown", f"{username}:{username}", dest], check=True)
                except Exception:
                    # If stat fails, try chown anyway
                    try:
                        subprocess.run(["sudo", "chown", f"{username}:{username}", dest], check=False)
                    except Exception:
                        pass

                # Set permissions (should work now that we own the file)
                try:
                    os.chmod(dest, 0o644)
                except PermissionError:
                    subprocess.run(["sudo", "chmod", "644", dest], check=True)

                # Generate MD5 checksum
                self.logger.log("cyan", _("Generating MD5 checksum..."))
                md5_file = f"{dest}.md5"
                result = subprocess.run(
                    ["md5sum", dest],
                    capture_output=True,
                    text=True,
                    check=True
                )
                md5_hash = result.stdout.split()[0]
                with open(md5_file, 'w') as f:
                    f.write(f"{md5_hash}  {filename}\n")

                self.logger.log("green", _("Moved: {0}").format(filename))
                self.logger.log("green", _("MD5: {0}").format(md5_hash))

            # Cleanup work directory completely (remove everything including .pkgs)
            self.logger.log("cyan", _("Cleaning up work directory..."))
            try:
                shutil.rmtree(self.work_path)
                self.logger.log("green", _("Work directory removed"))
            except PermissionError:
                subprocess.run(["sudo", "rm", "-rf", self.work_path], check=True)
                self.logger.log("green", _("Work directory removed"))

            self.logger.log("green", _("Cleanup completed"))
            return True

        except Exception as e:
            self.logger.log("red", _("Error moving ISO files: {0}").format(str(e)))
            return False

    def cleanup_cache(self) -> bool:
        """
        Clean up cache directories (optional)

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.log("cyan", _("Cleaning up cache directories..."))

        try:
            if os.path.exists(self.cache_path):
                shutil.rmtree(self.cache_path)
                self.logger.log("green", _("Cache cleaned"))

            if os.path.exists(self.work_path):
                shutil.rmtree(self.work_path)
                self.logger.log("green", _("Work directory cleaned"))

            return True

        except Exception as e:
            self.logger.log("yellow", _("Could not clean cache: {0}").format(str(e)))
            return False

    def _sudo_keepalive_loop(self, stop_event: threading.Event):
        """
        Background thread to keep sudo session alive.
        Runs in the same process as main thread, ensuring sudo timestamps
        are refreshed for the correct PID/tty context.
        """
        while not stop_event.is_set():
            subprocess.run(
                ["sudo", "-n", "-v"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
            stop_event.wait(60)

    def execute_build(self) -> bool:
        """
        Main orchestrator for local build process

        Returns:
            bool: True if successful, False otherwise
        """
        sudo_stop_event = None
        sudo_thread = None

        try:
            # Step 0: Get sudo access upfront (ask password once)
            self.logger.log("cyan", _("Requesting sudo access for file operations..."))
            result = subprocess.run(["sudo", "-v"], check=False)  # Ask for password
            if result.returncode != 0:
                self.logger.log("red", _("Sudo access required for local builds"))
                return False

            # Start sudo keep-alive as a background thread (same process = same sudo context)
            sudo_stop_event = threading.Event()
            sudo_thread = threading.Thread(
                target=self._sudo_keepalive_loop,
                args=(sudo_stop_event,),
                daemon=True
            )
            sudo_thread.start()

            # Step 1: Check container engine
            if not self.check_container_engine():
                self.logger.log("red", _("Docker or Podman not found"))
                self.logger.log("yellow", _("Install with: sudo pacman -S docker"))
                self.logger.log("yellow", _("Or install Podman: sudo pacman -S podman"))
                return False

            # Step 2: Check disk space
            self.check_disk_space()  # Warning only, don't fail

            # Step 3: Pull container image
            if not self.pull_container_image():
                return False

            # Step 4: Prepare directories
            if not self.prepare_directories():
                return False

            # Step 5: Clone build-iso repository
            if not self.prepare_build_script():
                return False

            # Step 6: Run container build
            if not self.run_container_build():
                self.logger.log("red", _("Build failed inside container"))
                self.logger.log("yellow", _("Work directory preserved for debugging: {0}").format(self.work_path))
                return False

            # Step 7: Move ISO files
            move_success = self.move_iso_files()
            if not move_success:
                self.logger.log("yellow", _("Could not move ISO files, check manually"))

            # Step 8: Clean cache if requested (always runs even if move failed)
            if self.clean_cache_after_build:
                self.logger.log("cyan", _("Cleaning package cache..."))
                try:
                    shutil.rmtree(self.cache_path)
                    self.logger.log("green", _("Cache cleaned successfully"))
                except PermissionError:
                    try:
                        subprocess.run(["sudo", "rm", "-rf", self.cache_path], check=True)
                        self.logger.log("green", _("Cache cleaned successfully"))
                    except Exception as e:
                        self.logger.log("yellow", _("Could not clean cache: {0}").format(str(e)))
                except Exception as e:
                    self.logger.log("yellow", _("Could not clean cache: {0}").format(str(e)))

            # Return error if move failed
            if not move_success:
                return False

            # Step 9: Clean up stopped containers
            self.logger.log("cyan", _("Cleaning up containers..."))
            try:
                # Remove stopped containers with our image
                subprocess.run(
                    [self.container_engine, "container", "prune", "-f", "--filter", f"ancestor={self.container_image}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            except Exception:
                pass  # Ignore errors in cleanup

            # Step 10: Display success message
            self.logger.log("green", _("Local build completed successfully!"))
            self.logger.log("cyan", _("ISO files saved to: {0}").format(self.output_dir))

            return True

        except Exception as e:
            self.logger.log("red", _("Unexpected error: {0}").format(str(e)))
            self.logger.log("yellow", _("Work directory preserved at: {0}").format(self.work_path))
            return False

        finally:
            # Stop sudo keep-alive thread
            if sudo_stop_event:
                sudo_stop_event.set()
            if sudo_thread and sudo_thread.is_alive():
                sudo_thread.join(timeout=2)

    @property
    def console(self):
        """Access logger's console for output streaming"""
        return self.logger.console
