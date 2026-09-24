"""The BigCommunity kernel is offered, and flagged while its channel lacks it.

linux-big is published in the community repositories, testing first and
stable later. Choosing it for a channel that does not carry it yet is not
refused -- the channel may be about to receive it -- but it is reported,
since the ISO would otherwise fail an hour into the build. A channel that
cannot be read says nothing: an unverifiable choice is not a broken one.

The GTK methods are read out of the widget module and run against doubles:
the package is built with no display, where constructing a widget segfaults.
"""

import ast
import io
import tarfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from gitrepo.build_iso import build_iso as cli
from gitrepo.build_iso.config import (
    BRANCH_DISPLAY_NAMES,
    COMMUNITY_KERNEL_PACKAGES,
    KERNEL_DISPLAY_NAMES,
    VALID_KERNELS,
)
from gitrepo.build_iso.core import community_packages
from gitrepo.build_iso.core.community_packages import (
    available_kernels,
    channel_packages,
    database_url,
    kernel_notice,
    package_names,
)

WIDGET = Path(__file__).parents[2] / "usr/share/gitrepo/build_iso/gui/widgets/build_widget.py"


@pytest.fixture(autouse=True)
def untranslated(monkeypatch):
    # The assertions read the English source text, whatever the test locale.
    monkeypatch.setattr(community_packages, "_", lambda message: message)
    monkeypatch.setattr(cli, "_", lambda message: message)
    monkeypatch.setattr(community_packages, "_cache", {})


def database(*directories):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for directory in directories:
            content = f"%NAME%\n{directory}\n".encode()
            info = tarfile.TarInfo(f"{directory}/desc")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


TESTING = database("linux-big-7.2.7-2", "linux-big-headers-7.2.7-2", "big-store-1.0.3-1")
STABLE = database("linux-big-headers-7.1.0-1", "big-store-1.0.3-1")


# -- the choices ----------------------------------------------------------------


def test_the_big_kernel_is_offered_by_name():
    assert "big" in VALID_KERNELS
    assert KERNEL_DISPLAY_NAMES["big"] == "BigCommunity"
    assert COMMUNITY_KERNEL_PACKAGES == {"big": "linux-big"}


def test_only_bigcommunity_is_offered_the_community_kernel():
    assert available_kernels(VALID_KERNELS, "bigcommunity") == VALID_KERNELS
    assert available_kernels(VALID_KERNELS, "biglinux") == ["latest", "lts", "oldlts", "xanmod"]


# -- reading a channel ------------------------------------------------------------


def test_package_names_ignore_version_and_similar_names():
    assert package_names(TESTING) == {"linux-big", "linux-big-headers", "big-store"}
    # linux-big-headers alone does not make linux-big published.
    assert "linux-big" not in package_names(STABLE)


def test_the_database_url_is_the_community_channel():
    assert database_url("stable") == "https://repo.communitybig.org/stable/x86_64/community-stable.db"


@pytest.mark.parametrize(
    "failure",
    [
        OSError("offline"),
        urllib.error.HTTPError("url", 403, "Forbidden", None, None),
        ValueError("package database is too large"),
    ],
)
def test_an_unreadable_channel_is_unknown_not_empty(failure):
    def download(_url):
        raise failure

    assert channel_packages("stable", download) is None


def test_a_garbled_database_is_unknown():
    assert channel_packages("stable", lambda _url: b"not a tar archive") is None


def test_a_channel_is_read_once_and_then_remembered():
    downloads = []

    def download(url):
        downloads.append(url)
        return TESTING

    assert "linux-big" in channel_packages("testing", download)
    assert "linux-big" in channel_packages("testing", download)
    assert len(downloads) == 1


# -- the notice -------------------------------------------------------------------


def lookup(channels):
    return lambda branch: channels.get(branch)


def test_a_manjaro_kernel_is_never_flagged():
    assert kernel_notice("lts", "bigcommunity", "stable", lookup({})) == ""


def test_the_kernel_missing_from_the_channel_is_reported():
    notice = kernel_notice("big", "bigcommunity", "stable", lookup({"stable": package_names(STABLE)}))

    assert "linux-big" in notice
    # Channel names are translated when the configuration loads.
    assert f"Community {BRANCH_DISPLAY_NAMES['stable']}" in notice
    assert "Testing" in notice


def test_the_kernel_published_in_the_channel_is_not_reported():
    assert kernel_notice("big", "bigcommunity", "testing", lookup({"testing": package_names(TESTING)})) == ""


def test_once_stable_publishes_it_the_notice_goes_away():
    published = database("linux-big-7.2.7-2", "linux-big-headers-7.2.7-2")

    assert kernel_notice("big", "bigcommunity", "stable", lookup({"stable": package_names(published)})) == ""


def test_an_unreadable_channel_raises_no_notice():
    assert kernel_notice("big", "bigcommunity", "stable", lookup({"stable": None})) == ""


def test_biglinux_is_told_the_kernel_is_not_for_it():
    notice = kernel_notice("big", "biglinux", "", lookup({}))

    assert "BigCommunity" in notice


# -- the terminal -------------------------------------------------------------------


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


class Menu:
    def __init__(self, pick):
        self.pick = pick
        self.options = None

    def show_menu(self, _title, options):
        self.options = options
        return self.pick(options)


def test_the_terminal_offers_linux_big_to_bigcommunity_only():
    for distro, expected in (("bigcommunity", True), ("biglinux", False)):
        menu = Menu(lambda options: (0, options[0]))
        cli.BuildISO.get_kernel(SimpleNamespace(menu=menu, distroname=distro, kernel="lts"))
        assert ("big" in menu.options) is expected


def test_the_terminal_picks_from_the_filtered_list():
    menu = Menu(lambda options: (options.index("big"), "big"))
    builder = SimpleNamespace(menu=menu, distroname="bigcommunity", kernel="lts")

    assert cli.BuildISO.get_kernel(builder) is True
    assert builder.kernel == "big"


def terminal(kernel, distro, community, notice, monkeypatch):
    monkeypatch.setattr(cli, "kernel_notice", lambda *_args: notice)
    builder = SimpleNamespace(kernel=kernel, distroname=distro, branches={"community": community}, logger=Logger())
    return cli.BuildISO._kernel_is_buildable(builder), builder.logger.messages


def test_the_terminal_warns_but_builds_when_the_channel_lacks_it(monkeypatch):
    buildable, messages = terminal("big", "bigcommunity", "stable", "not published yet", monkeypatch)

    assert buildable is True
    assert messages == [("yellow", "not published yet")]


def test_the_terminal_stops_a_biglinux_build_with_linux_big(monkeypatch):
    buildable, messages = terminal("big", "biglinux", "", "only for BigCommunity", monkeypatch)

    assert buildable is False
    assert messages == [("red", "only for BigCommunity")]


def test_the_terminal_is_silent_when_nothing_is_wrong(monkeypatch):
    assert terminal("lts", "bigcommunity", "stable", "", monkeypatch) == (True, [])


# -- the window, against doubles ------------------------------------------------------


def widget_methods(*names):
    tree = ast.parse(WIDGET.read_text(encoding="utf-8"))
    widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BuildWidget")
    methods = [node for node in widget.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for method in methods:
        method.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(WIDGET), "exec"), namespace)
    return namespace


class Row:
    def __init__(self):
        self.subtitle = ""
        self.classes = set()

    def set_subtitle(self, text):
        self.subtitle = text

    def add_css_class(self, name):
        self.classes.add(name)

    def remove_css_class(self, name):
        self.classes.discard(name)


def window(request=1):
    toasts = []
    root = SimpleNamespace(show_toast=toasts.append)
    widget = SimpleNamespace(
        _kernel_notice_request=request,
        _kernel_notice="",
        kernel_row=Row(),
        _kernel_subtitle=lambda: "default subtitle",
        get_root=lambda: root,
    )
    return widget, toasts


def test_the_window_flags_the_row_and_announces_it_once():
    show = widget_methods("_show_kernel_notice")["_show_kernel_notice"]
    widget, toasts = window()

    show(widget, 1, "not published yet", True)
    show(widget, 1, "not published yet", True)

    assert widget.kernel_row.subtitle == "not published yet"
    assert "warning" in widget.kernel_row.classes
    assert toasts == ["not published yet"]


def test_the_window_clears_the_notice_when_it_no_longer_applies():
    show = widget_methods("_show_kernel_notice")["_show_kernel_notice"]
    widget, _toasts = window()
    show(widget, 1, "not published yet", True)

    show(widget, 1, "", True)

    assert widget.kernel_row.subtitle == "default subtitle"
    assert "warning" not in widget.kernel_row.classes


def test_the_window_ignores_a_stale_answer():
    show = widget_methods("_show_kernel_notice")["_show_kernel_notice"]
    widget, toasts = window(request=2)

    show(widget, 1, "not published yet", True)

    assert widget.kernel_row.subtitle == ""
    assert toasts == []


def test_a_choice_restored_at_startup_is_shown_without_a_toast():
    show = widget_methods("_show_kernel_notice")["_show_kernel_notice"]
    widget, toasts = window()

    show(widget, 1, "not published yet", False)

    assert widget.kernel_row.subtitle == "not published yet"
    assert toasts == []


def test_the_build_button_is_never_disabled_by_the_notice():
    tree = ast.parse(WIDGET.read_text(encoding="utf-8"))
    widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BuildWidget")
    notice_methods = [
        ast.unparse(node) for node in widget.body if isinstance(node, ast.FunctionDef) and "kernel_notice" in node.name
    ]

    assert notice_methods
    assert not any("build_button" in source for source in notice_methods)
