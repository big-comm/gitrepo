from gitrepo.build_package.core.github_api import GitHubAPI
from gitrepo.build_package.core.token_store import TokenStore


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


def _enter_token(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "tester")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "secret-token")


def test_failed_keyring_write_aborts_token_setup(monkeypatch):
    _enter_token(monkeypatch)
    monkeypatch.setattr(TokenStore, "get_token", staticmethod(lambda _organization: ""))
    monkeypatch.setattr(TokenStore, "upsert", staticmethod(lambda _organization, _token: False))
    api = GitHubAPI("", "biglinux")
    logger = Logger()

    assert api.ensure_github_token(logger) is False
    assert api.token == ""
    assert api.headers == {}
    assert logger.messages[-1][0] == "red"
    assert all("600" not in message for _style, message in logger.messages)


def test_successful_keyring_write_enables_the_token(monkeypatch):
    _enter_token(monkeypatch)
    monkeypatch.setattr(TokenStore, "get_token", staticmethod(lambda _organization: ""))
    monkeypatch.setattr(TokenStore, "upsert", staticmethod(lambda _organization, _token: True))
    api = GitHubAPI("", "biglinux")
    logger = Logger()

    assert api.ensure_github_token(logger) is True
    assert api.token == "secret-token"
    assert api.headers["Authorization"] == "token secret-token"
    assert logger.messages[-1][0] == "green"
    assert all("600" not in message for _style, message in logger.messages)
