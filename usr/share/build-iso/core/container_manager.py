#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/container_manager.py - Container engine detection and management
#

import subprocess
import time

from core.translation_utils import _


class ContainerManager:
    """Manages Docker/Podman container engine detection, images, and storage driver"""

    def __init__(self, preference="auto"):
        self.engine = None
        self.preference = preference

    def detect_engine(self) -> str | None:
        """Detect available container engine based on preference"""
        if self.preference != "auto":
            if self._engine_available(self.preference):
                self.engine = self.preference
                return self.engine

        for engine in ["docker", "podman"]:
            if self._engine_available(engine):
                self.engine = engine
                return self.engine
        return None

    def _engine_available(self, engine: str) -> bool:
        try:
            result = subprocess.run(
                ["which", engine],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_engine_version(self) -> str:
        if not self.engine:
            return ""
        try:
            result = subprocess.run(
                [self.engine, "version", "--format", "{{.Server.Version}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_storage_driver(self) -> str:
        if self.engine != "docker":
            return "n/a"
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.Driver}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def needs_storage_fix(self) -> bool:
        """Check if Docker needs btrfs → overlay2 migration"""
        return self.get_storage_driver() == "btrfs"

    def image_exists(self, image: str) -> bool:
        if not self.engine:
            return False
        try:
            result = subprocess.run(
                [self.engine, "image", "inspect", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_image_info(self, image: str) -> dict:
        """Get image size and creation date"""
        if not self.engine:
            return {}
        try:
            result = subprocess.run(
                [self.engine, "image", "inspect", image, "--format",
                 "{{.Size}} {{.Created}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(" ", 1)
                size_bytes = int(parts[0]) if parts else 0
                created = parts[1] if len(parts) > 1 else ""
                return {
                    "size_gb": round(size_bytes / (1024 ** 3), 2),
                    "created": created[:19] if created else "",
                }
        except Exception:
            pass
        return {}

    def pull_image(self, image: str, progress_callback=None) -> bool:
        """Pull container image with progress callback"""
        if not self.engine:
            return False

        process = subprocess.Popen(
            [self.engine, "pull", image],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in process.stdout:
            line = line.rstrip()
            if line and progress_callback:
                progress_callback(line)

        process.wait()
        return process.returncode == 0

    def cleanup_old_containers(self, image: str):
        """Remove stopped containers for a given image"""
        if not self.engine:
            return
        try:
            result = subprocess.run(
                [self.engine, "ps", "-a", "-q", "--filter", f"ancestor={image}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            if result.stdout.strip():
                ids = result.stdout.strip().split("\n")
                subprocess.run([self.engine, "stop"] + ids, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30)
                subprocess.run([self.engine, "rm"] + ids, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass

    def get_disk_space(self, path: str) -> float:
        """Get available disk space in GB for a path"""
        import shutil
        try:
            stat = shutil.disk_usage(path)
            return round(stat.free / (1024 ** 3), 1)
        except Exception:
            return 0.0
