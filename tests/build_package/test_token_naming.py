"""A token saved under the wrong name used to be silently ignored, ending in an unexplained 403."""

import importlib

import pytest


@pytest.fixture
def modules(build_package_modules, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")
    api = importlib.import_module("gitrepo.build_package.core.github_api")
    monkeypatch.setattr(api.GitUtils, "get_repo_name", staticmethod(lambda: "biglinux/bigocrpdf"))
    return importlib.import_module("gitrepo.build_package.core.destination"), api


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


def test_only_destination_names_and_default_are_ever_used(modules):
    destination, _api = modules
    assert destination.token_usage("biglinux")[0]
    assert destination.token_usage("BIG-COMM")[0]
    assert destination.token_usage("default")[0]
    used, why = destination.token_usage("bigbruno")
    assert not used and "Never used" in why


def test_the_entry_used_is_the_organization_then_default(modules):
    destination, _api = modules
    assert destination.token_source("biglinux", [("bigbruno", "a"), ("biglinux", "b")]) == "biglinux"
    assert destination.token_source("biglinux", [("bigbruno", "a"), ("default", "b")]) == "default"
    assert destination.token_source("biglinux", [("bigbruno", "a")]) == ""


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.text = "x" if payload else ""

    def json(self):
        return self.payload


def _dispatch(api_module, monkeypatch, response, entries):
    monkeypatch.setattr(api_module.TokenStore, "read_all", staticmethod(lambda: entries))
    monkeypatch.setattr(api_module.requests, "post", lambda url, **kwargs: response)
    monkeypatch.setattr(api_module.GitHubAPI, "_report_dispatched_run", lambda *a, **k: None)
    logger = Logger()
    ok = api_module.GitHubAPI("old-token", "biglinux").trigger_workflow(
        "bigocrpdf", "testing", "dev-bigbruno", False, False, logger
    )
    return ok, logger


def test_a_refused_dispatch_names_the_token_used_and_what_to_check(modules, monkeypatch):
    _destination, api = modules
    refused = Response(403, {"message": "Resource not accessible by personal access token"})

    ok, logger = _dispatch(api, monkeypatch, refused, [("bigbruno", "new-token"), ("default", "old-token")])

    text = logger.text()
    assert not ok
    assert "No access token is saved for biglinux; using the one saved as default." in text
    assert "GitHub says: Resource not accessible by personal access token" in text
    assert "it is saved for biglinux" in text and "repo and workflow scopes" in text
    assert "new-token" not in text and "old-token" not in text


def test_an_accepted_dispatch_only_names_the_entry(modules, monkeypatch):
    _destination, api = modules

    ok, logger = _dispatch(api, monkeypatch, Response(204), [("biglinux", "tok")])

    assert ok
    assert "Using the access token saved for biglinux." in logger.text()
    assert "Check the access token" not in logger.text()


def test_the_settings_form_saves_for_the_chosen_organization(build_package_modules, monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gtk

    # Without a display GTK 4 still answers init_check() with True, and the
    # first widget then crashes the whole run; only a real display is enough.
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("no display for GTK widgets")
    monkeypatch.setenv("LANGUAGE", "en")
    widgets = importlib.import_module("gitrepo.build_package.gui.widgets.settings_widgets")
    saved = []
    monkeypatch.setattr(widgets.TokenStore, "read_all", staticmethod(lambda: [("bigbruno", "x")]))
    monkeypatch.setattr(
        widgets.TokenStore, "upsert", staticmethod(lambda org, token: saved.append((org, token)) or True)
    )
    monkeypatch.setattr(widgets.TokenStore, "get_token", staticmethod(lambda org: "ghp_new"))
    monkeypatch.setattr(
        widgets.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})()
    )
    monkeypatch.setattr(widgets.GLib, "idle_add", lambda function, *args: function(*args))

    class Window:
        build_package = type("Bp", (), {"organization": "biglinux", "github_api": None})()

        def show_toast(self, message):
            pass

        def show_error_toast(self, message):
            raise AssertionError(message)

    form = widgets.TokenSettingsWidget(Window(), show_hero=False)
    assert form._selected_token_org() == "biglinux"
    form.token_value_entry.set_text("ghp_new")
    form._on_save_token(None)

    assert saved == [("biglinux", "ghp_new")]
