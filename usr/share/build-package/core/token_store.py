#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/token_store.py - Token file read/write abstraction
#
# Single source of truth for all ~/.config/gitrepo/github_token operations.
# Both gui/dialogs/preferences_dialog.py and core/github_api.py delegate here.

import os
import shutil

from .config import TOKEN_FILE, TOKEN_FILE_LEGACY


class TokenStore:
    """Read/write GitHub tokens from the XDG config file.

    File format — one entry per line:
        org=ghp_token      # token for a specific organization
        ghp_token          # "default" token (no org prefix)
        # comment lines are ignored
    """

    @staticmethod
    def _path() -> str:
        return os.path.expanduser(TOKEN_FILE)

    @staticmethod
    def migrate_if_needed() -> None:
        """One-time migration: copy ~/.GITHUB_TOKEN → TOKEN_FILE and remove legacy."""
        new_path = os.path.expanduser(TOKEN_FILE)
        old_path = os.path.expanduser(TOKEN_FILE_LEGACY)
        if not os.path.exists(new_path) and os.path.exists(old_path):
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.copy2(old_path, new_path)
                os.chmod(new_path, 0o600)
                os.remove(old_path)
            except Exception:
                pass

    @staticmethod
    def read_all() -> list[tuple[str, str]]:
        """Return all `(org, token)` pairs from the token file.

        Bare tokens (no ``org=`` prefix) are returned with org ``"default"``.
        """
        TokenStore.migrate_if_needed()
        token_file = TokenStore._path()
        entries: list[tuple[str, str]] = []
        if not os.path.exists(token_file):
            return entries
        try:
            with open(token_file) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        org, tok = line.split('=', 1)
                        entries.append((org.strip(), tok.strip()))
                    else:
                        entries.append(("default", line))
        except Exception:
            pass
        return entries

    @staticmethod
    def write_all(entries: list[tuple[str, str]]) -> bool:
        """Overwrite the token file with *entries* and set permissions 600.

        Returns ``True`` on success, ``False`` on any write error.
        """
        token_file = TokenStore._path()
        try:
            os.makedirs(os.path.dirname(token_file), exist_ok=True)
            with open(token_file, 'w') as f:
                for org, tok in entries:
                    f.write(f"{tok}\n" if org == "default" else f"{org}={tok}\n")
            os.chmod(token_file, 0o600)
            return True
        except Exception:
            return False

    @staticmethod
    def get_token(organization: str) -> str:
        """Return token for *organization*, falling back to the first default token.

        Returns an empty string when no matching token is found.
        """
        entries = TokenStore.read_all()
        default = ""
        for org, tok in entries:
            if org.lower() == organization.lower():
                return tok
            if org == "default" and not default:
                default = tok
        return default

    @staticmethod
    def upsert(organization: str, token: str) -> bool:
        """Add or update the token for *organization*.

        Returns ``True`` on success.
        """
        entries = TokenStore.read_all()
        key = "default" if not organization else organization
        updated = [(o, t) for o, t in entries if o.lower() != key.lower()]
        updated.append((key, token))
        return TokenStore.write_all(updated)

    @staticmethod
    def delete(organization: str) -> bool:
        """Remove the entry for *organization*.

        Returns ``True`` on success.
        """
        entries = TokenStore.read_all()
        filtered = [(o, t) for o, t in entries if o.lower() != organization.lower()]
        return TokenStore.write_all(filtered)
