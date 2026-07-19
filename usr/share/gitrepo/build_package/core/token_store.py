"""Compatibility facade for the shared atomic GitHub token store."""

import os

from gitrepo.common.token_store import GitHubTokenStore

from .config import TOKEN_FILE, TOKEN_FILE_LEGACY


def _store() -> GitHubTokenStore:
    return GitHubTokenStore(os.path.expanduser(TOKEN_FILE), os.path.expanduser(TOKEN_FILE_LEGACY))


class TokenStore:
    """Preserve the historic static API while delegating to one owner."""

    @staticmethod
    def migrate_if_needed() -> None:
        _store().migrate_if_needed()

    @staticmethod
    def read_all() -> list[tuple[str, str]]:
        return _store().read_all()

    @staticmethod
    def write_all(entries: list[tuple[str, str]]) -> bool:
        return _store().write_all(entries)

    @staticmethod
    def get_token(organization: str) -> str:
        return _store().get_token(organization)

    @staticmethod
    def upsert(organization: str, token: str) -> bool:
        return _store().upsert(organization, token)

    @staticmethod
    def delete(organization: str) -> bool:
        return _store().delete(organization)
