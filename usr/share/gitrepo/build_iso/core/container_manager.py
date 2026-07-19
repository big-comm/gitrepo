#
# core/container_manager.py - Container engine detection and management
#

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from gitrepo.common import child_process as subprocess
from gitrepo.common.translation import _


ISO_BUILDER_LABEL = "org.biglinux.gitrepo.role=iso-builder"


@dataclass(frozen=True)
class ContainerStatus:
    """Container runtime state captured by one probe."""

    engine: str | None
    version: str = ""
    engine_error: str = ""
    driver: str = ""
    driver_error: str = ""
    image_size_gb: float | None = None
    image_created: str = ""
    image_error: str = ""

    @property
    def is_engine_ready(self) -> bool:
        return bool(self.engine and not self.engine_error and self.driver)

    @property
    def is_image_available(self) -> bool:
        return self.image_size_gb is not None


class ContainerManager:
    """Manages Docker/Podman container engine detection, images, and storage driver"""

    def __init__(self, preference: str = "auto") -> None:
        self.engine: str | None = None
        self.preference = preference

    def detect_engine(self) -> str | None:
        """Detect available container engine based on preference"""
        if self.preference != "auto":
            if self._engine_available(self.preference):
                self.engine = self.preference
                return self.engine
            return None

        for engine in ["docker", "podman"]:
            if self._engine_available(engine):
                self.engine = engine
                return self.engine
        return None

    def _engine_available(self, engine: str) -> bool:
        return shutil.which(engine) is not None

    def capture_status(self, image: str) -> ContainerStatus:
        """Capture runtime and image state without repeating probes."""
        engine = self.detect_engine()
        if not engine:
            return ContainerStatus(
                engine=None,
                engine_error=_("Docker or Podman is not installed or is not available in PATH."),
            )

        try:
            version_result = subprocess.run(
                [engine, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception as error:
            return ContainerStatus(engine=engine, engine_error=str(error))

        if version_result.returncode != 0:
            diagnostic = version_result.stderr.strip() or _("The container engine did not respond.")
            return ContainerStatus(engine=engine, engine_error=diagnostic)

        version_lines = version_result.stdout.strip().splitlines()
        if not version_lines:
            return ContainerStatus(engine=engine, engine_error=_("The container engine did not respond."))
        version = version_lines[0]
        driver = self.get_storage_driver()
        driver_error = ""
        if not driver:
            driver_error = _("The storage driver probe failed. Check the engine service, then refresh.")

        try:
            image_result = subprocess.run(
                [engine, "image", "inspect", image, "--format", "{{.Size}} {{.Created}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as error:
            return ContainerStatus(
                engine=engine,
                version=version,
                driver=driver,
                driver_error=driver_error,
                image_error=str(error),
            )

        image_size_gb = None
        image_created = ""
        image_error = ""
        if image_result.returncode == 0 and image_result.stdout.strip():
            size, separator, created = image_result.stdout.strip().partition(" ")
            try:
                image_size_gb = int(size) / (1024**3)
                image_created = created[:19] if separator else ""
            except ValueError:
                image_error = _("The image metadata could not be read. Refresh or pull the image again.")
        else:
            image_error = image_result.stderr.strip() or _("The image is not downloaded. Pull it, then refresh.")

        return ContainerStatus(
            engine=engine,
            version=version,
            driver=driver,
            driver_error=driver_error,
            image_size_gb=image_size_gb,
            image_created=image_created,
            image_error=image_error,
        )

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

    def pull_image(self, image: str, progress_callback: Callable[[str], None] | None = None) -> bool:
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

        if process.stdout is None:
            process.wait()
            return False

        for line in process.stdout:
            line = line.rstrip()
            if line and progress_callback:
                progress_callback(line)

        process.wait()
        return process.returncode == 0

    def list_stopped_containers(self, image: str) -> list[str]:
        """Return stopped container IDs for an exact ancestor image."""
        if not self.engine:
            return []
        try:
            result = subprocess.run(
                [
                    self.engine,
                    "ps",
                    "-a",
                    "-q",
                    "--filter",
                    f"ancestor={image}",
                    "--filter",
                    f"label={ISO_BUILDER_LABEL}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            return [container_id for container_id in result.stdout.splitlines() if self._is_container_id(container_id)]
        except Exception:
            return []

    def remove_stopped_containers(self, container_ids: list[str]) -> bool:
        """Remove only the validated IDs previously shown to the user."""
        if not self.engine or not container_ids or not all(self._is_container_id(value) for value in container_ids):
            return False
        try:
            result = subprocess.run(
                [self.engine, "rm", *container_ids],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _is_container_id(value: str) -> bool:
        return re.fullmatch(r"[0-9a-f]{12,64}", value) is not None
