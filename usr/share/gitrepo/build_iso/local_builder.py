"""CLI adapter for the canonical container-owned ISO build pipeline."""

import shutil

from gitrepo.build_iso.core.iso_builder import ISOBuilder
from gitrepo.common.translation import _


class LocalBuilder:
    """Expose the shared ISO builder through the legacy CLI logger contract."""

    def __init__(self, logger, config: dict):
        self.logger = logger
        self.config = dict(config)
        self.container_engine = self._resolve_engine(self.config.get("container_engine", "auto"))
        self.config["container_engine"] = self.container_engine
        self.output_dir = self.config.get("output_dir", "~/ISO")

    @staticmethod
    def _resolve_engine(requested: str) -> str:
        if requested in ("docker", "podman"):
            return requested
        return next((engine for engine in ("docker", "podman") if shutil.which(engine)), "docker")

    def check_container_engine(self) -> bool:
        """Verify that the selected unprivileged container client is available."""
        if not shutil.which(self.container_engine):
            self.logger.log("red", _("No supported container engine was found."))
            return False
        self.logger.log("green", _("Container engine found: {0}").format(self.container_engine))
        return True

    def execute_build(self) -> bool:
        """Run the canonical pipeline and adapt its result to the CLI boolean API."""
        if not self.check_container_engine():
            return False
        builder = ISOBuilder(
            self.config,
            callbacks={"on_log": self.logger.log},
        )
        result = builder.execute()
        if result["success"]:
            self.logger.log("cyan", _("ISO saved to: {0}").format(result["iso_path"]))
            return True
        self.logger.log("red", result["error"] or _("ISO build failed."))
        return False

    @property
    def console(self):
        """Access the CLI logger console."""
        return self.logger.console
