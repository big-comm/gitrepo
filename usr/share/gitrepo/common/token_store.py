"""Libsecret-backed GitHub credential storage shared by both applications."""

from __future__ import annotations

import json
import os
from pathlib import Path

import gi

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret  # noqa: E402


_SCHEMA_NAME = "org.biglinux.GitRepo.GitHubTokens"
_SCHEMA_ATTRIBUTES = {"application": Secret.SchemaAttributeType.STRING}
_ATTRIBUTES = {"application": "gitrepo"}
_ITEM_LABEL = "GitRepo GitHub tokens"


class GitHubTokenStore:
    """Store all organization-scoped tokens as one atomic secret item."""

    def __init__(self, path: str | Path | None = None, legacy_path: str | Path | None = None):
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = Path(path) if path is not None else xdg_config / "gitrepo" / "github_token"
        self.legacy_path = Path(legacy_path) if legacy_path is not None else Path.home() / ".GITHUB_TOKEN"
        self.last_read_error = ""

    @staticmethod
    def _schema() -> Secret.Schema:
        return Secret.Schema.new(_SCHEMA_NAME, Secret.SchemaFlags.NONE, _SCHEMA_ATTRIBUTES)

    @staticmethod
    def _normalize(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
        tokens: dict[str, tuple[str, str]] = {}
        for organization, token in entries:
            key = organization.strip() or "default"
            value = token.strip()
            if value:
                tokens[key.lower()] = (key, value)
        return [tokens[key] for key in sorted(tokens)]

    @classmethod
    def _decode(cls, payload: str | None) -> list[tuple[str, str]]:
        if not payload:
            return []
        document = json.loads(payload)
        if document.get("version") != 1 or not isinstance(document.get("tokens"), dict):
            raise ValueError("unsupported credential format")
        return cls._normalize([(str(key), str(value)) for key, value in document["tokens"].items()])

    @classmethod
    def _encode(cls, entries: list[tuple[str, str]]) -> str:
        tokens = {organization: token for organization, token in cls._normalize(entries)}
        return json.dumps({"version": 1, "tokens": tokens}, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _is_migratable(path: Path) -> bool:
        """Report whether *path* is a plain file this process may read.

        A FIFO left at either location would block read_text() forever with no
        timeout, and a symlink would import whatever it points at. Anything that
        is not a regular file is not a credential file we wrote.
        """
        try:
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    @staticmethod
    def _read_legacy_file(path: Path) -> list[tuple[str, str]]:
        entries = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                organization, token = line.split("=", 1)
                if organization.strip() and token.strip():
                    entries.append((organization.strip(), token.strip()))
            else:
                entries.append(("default", line))
        return entries

    def _lookup_secret(self) -> list[tuple[str, str]]:
        payload = Secret.password_lookup_sync(self._schema(), _ATTRIBUTES, None)
        return self._decode(payload)

    def migrate_if_needed(self) -> bool:
        """Move cleartext credentials only after a verified libsecret write.

        An unreadable legacy file is skipped rather than failed on. Failing
        would make read_all() return nothing, so a root-owned or corrupt
        ~/.GITHUB_TOKEN hid every token libsecret already held and left no way
        to enter a new one from the interface.
        """
        sources = [path for path in (self.path, self.legacy_path) if self._is_migratable(path)]
        if not sources:
            return True
        try:
            legacy: list[tuple[str, str]] = []
            for source in sources:
                try:
                    legacy.extend(self._read_legacy_file(source))
                except (OSError, UnicodeError) as error:
                    self.last_read_error = str(error)
                    return True
            # Keyring entries win: the cleartext file is the older copy, and it
            # is about to be deleted.
            normalized = self._normalize(legacy + self._lookup_secret())
            if not self.write_all(normalized) or self._lookup_secret() != normalized:
                raise OSError("credential migration could not be verified")
            for source in sources:
                source.unlink()
            return True
        except (OSError, UnicodeError, ValueError, GLib.Error) as error:
            self.last_read_error = str(error)
            return False

    def read_all(self) -> list[tuple[str, str]]:
        """Return tokens from libsecret, importing any old cleartext files first."""
        self.last_read_error = ""
        if not self.migrate_if_needed():
            return []
        try:
            return self._lookup_secret()
        except (ValueError, GLib.Error) as error:
            self.last_read_error = str(error)
            return []

    def write_all(self, entries: list[tuple[str, str]]) -> bool:
        """Atomically replace the versioned token map in libsecret."""
        self.last_read_error = ""
        try:
            return bool(
                Secret.password_store_sync(
                    self._schema(),
                    _ATTRIBUTES,
                    Secret.COLLECTION_DEFAULT,
                    _ITEM_LABEL,
                    self._encode(entries),
                    None,
                )
            )
        except (ValueError, GLib.Error) as error:
            self.last_read_error = str(error)
            return False

    def get_token(self, organization: str) -> str:
        """Return the matching token, falling back to the first default."""
        default = ""
        for candidate, token in self.read_all():
            if candidate.lower() == organization.lower():
                return token
            if candidate == "default" and not default:
                default = token
        return default

    def upsert(self, organization: str, token: str) -> bool:
        """Add or replace one organization token."""
        key = organization.strip() or "default"
        entries = [(candidate, value) for candidate, value in self.read_all() if candidate.lower() != key.lower()]
        if self.last_read_error:
            return False
        entries.append((key, token))
        return self.write_all(entries)

    def delete(self, organization: str) -> bool:
        """Delete only the selected organization entry."""
        entries = [
            (candidate, token) for candidate, token in self.read_all() if candidate.lower() != organization.lower()
        ]
        return not self.last_read_error and self.write_all(entries)
