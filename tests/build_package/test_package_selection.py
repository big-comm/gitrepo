"""Several packages of one repository are marked together and built one by one.

big-comm/big-kernel keeps linux-big and fifteen linux-big-* modules side by
side. The user marks the ones to build; the commit and the branch are
prepared once, and each marked package gets its own dispatch naming its
pkgbuild_dir. The modules build against the linux-big-headers already
published, so building the kernel with them is never done without asking.

The GTK side is checked against a recording double: the package is built
with no display, where constructing a real widget segfaults inside pango.
"""

import ast
import io
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from rich.console import Console

from gitrepo.build_package.cli import cli_menu
from gitrepo.build_package.core import package_operations, package_selection
from gitrepo.build_package.core.git_utils import GitUtils
from gitrepo.build_package.core.package_selection import (
    PackageChoice,
    PackageSelection,
    main_package,
    ordered_directories,
    package_choices,
)

DIALOG = Path(__file__).parents[2] / "usr/share/gitrepo/build_package/gui/dialogs/package_selection_dialog.py"

MODULES = [
    "linux-big-acpi_call",
    "linux-big-bbswitch",
    "linux-big-broadcom-wl",
    "linux-big-nvidia",
    "linux-big-nvidia-390xx",
    "linux-big-nvidia-470xx",
    "linux-big-nvidia-580xx",
    "linux-big-nvidia-580xx-open",
    "linux-big-nvidia-open",
    "linux-big-r8168",
    "linux-big-rtl8723bu",
    "linux-big-tp_smapi",
    "linux-big-vhba-module",
    "linux-big-virtualbox-host-modules",
    "linux-big-zfs",
]
BIG_KERNEL = ["linux-big", *MODULES]

KERNEL = """pkgbase=linux-big
pkgver=6.17.1
package_linux-big() {
  pkgdesc="The BigCommunity kernel and modules"
}
package_linux-big-headers() {
  pkgdesc="Headers and scripts for building modules for the BigCommunity kernel"
}
pkgname=("$pkgbase" "$pkgbase-headers")
"""


@pytest.fixture(autouse=True)
def untranslated(monkeypatch):
    # The assertions read the English source text, whatever the test locale.
    for module in (package_operations, package_selection, cli_menu):
        monkeypatch.setattr(module, "_", lambda message: message)


def module_pkgbuild(name):
    return f'pkgname={name}\npkgdesc="A module for linux-big, packaged as {name}"\n'


class Logger:
    def __init__(self):
        self.messages = []
        self.summaries = []

    def log(self, style, message):
        self.messages.append((style, message))

    def display_summary(self, title, data):
        self.summaries.append((title, data))

    def draw_app_header(self):
        pass

    def text(self):
        return "\n".join(message for _style, message in self.messages)


def selection_of(directories=BIG_KERNEL, main="linux-big"):
    return PackageSelection([PackageChoice(directory, f"about {directory}") for directory in directories], main)


# -- the model both interfaces share ----------------------------------------


def test_the_main_package_is_the_prefix_of_every_other():
    assert main_package(sorted(BIG_KERNEL, reverse=True), "big-comm/big-kernel") == "linux-big"


def test_the_package_named_after_the_repository_is_the_main_one():
    assert main_package(["docs", "gitrepo", "helper"], "big-comm/gitrepo") == "gitrepo"


def test_unrelated_packages_have_no_main_one():
    assert main_package(["alpha", "beta"], "big-comm/tools") == ""


def test_the_main_package_comes_first_and_the_rest_in_alphabetical_order():
    shuffled = list(reversed(BIG_KERNEL))

    assert ordered_directories(shuffled, "linux-big") == ["linux-big", *sorted(MODULES)]
    assert ordered_directories(["b", "a"], "") == ["a", "b"]


def test_select_all_marks_every_package_and_counts_them():
    selection = selection_of()

    selection.select_all()

    assert selection.selected_directories() == BIG_KERNEL
    assert selection.count_text() == "16 of 16 selected"
    assert selection.can_confirm


def test_nothing_marked_cannot_be_confirmed():
    selection = selection_of()
    selection.select_all()

    selection.clear()

    assert selection.selected_directories() == []
    assert selection.count_text() == "0 of 16 selected"
    assert not selection.can_confirm


def test_several_marked_keep_the_display_order():
    selection = selection_of()

    for directory in ("linux-big-zfs", "linux-big-acpi_call", "linux-big-r8168"):
        selection.toggle(directory)

    assert selection.selected_directories() == ["linux-big-acpi_call", "linux-big-r8168", "linux-big-zfs"]
    assert selection.count_text() == "3 of 16 selected"
    assert not selection.needs_order_warning


def test_toggling_twice_unmarks_and_unknown_directories_are_ignored():
    selection = selection_of()

    selection.toggle("linux-big-zfs")
    selection.toggle("linux-big-zfs")
    selection.set_selected("../elsewhere", True)

    assert selection.selected_directories() == []


def test_the_main_package_with_others_warns_and_offers_it_alone():
    selection = selection_of()
    selection.toggle("linux-big")
    assert not selection.needs_order_warning

    selection.toggle("linux-big-zfs")

    assert selection.needs_order_warning
    assert "linux-big" in selection.order_warning_text()
    assert selection.only_main_label() == "Build only linux-big"


def test_names_with_underscores_are_kept_exactly():
    selection = selection_of()
    selection.toggle("linux-big-tp_smapi")
    selection.toggle("linux-big-acpi_call")

    assert selection.selected_directories() == ["linux-big-acpi_call", "linux-big-tp_smapi"]
    assert "linux-big-tp_smapi" in [choice.directory for choice in selection.choices]


# -- descriptions read as text ----------------------------------------------


@pytest.fixture
def repository(tmp_path, monkeypatch):
    for directory in BIG_KERNEL:
        (tmp_path / directory).mkdir()
        content = KERNEL if directory == "linux-big" else module_pkgbuild(directory)
        (tmp_path / directory / "PKGBUILD").write_text(content, encoding="utf-8")
    monkeypatch.setattr(GitUtils, "get_repo_root_path", staticmethod(lambda: str(tmp_path)))
    monkeypatch.setattr(GitUtils, "get_repo_name", staticmethod(lambda: "big-comm/big-kernel"))
    return tmp_path


def test_a_top_level_pkgdesc_describes_the_package(repository):
    assert GitUtils.read_package_description("linux-big-tp_smapi") == (
        "A module for linux-big, packaged as linux-big-tp_smapi"
    )


def test_a_split_package_is_described_by_its_first_package_function(repository):
    assert GitUtils.read_package_description("linux-big") == "The BigCommunity kernel and modules"


def test_reading_a_description_never_executes_the_pkgbuild(repository):
    marker = repository / "executed"
    (repository / "linux-big-zfs" / "PKGBUILD").write_text(
        f'pkgname=linux-big-zfs\ntouch {marker}\npkgdesc="$(touch {marker})"\n', encoding="utf-8"
    )

    GitUtils.read_package_description("linux-big-zfs")

    assert not marker.exists()


def test_the_choices_list_the_repository_main_first_with_descriptions(repository):
    choices, main = package_choices(GitUtils.list_package_directories())

    assert main == "linux-big"
    assert [choice.directory for choice in choices] == ["linux-big", *MODULES]
    assert choices[0].description == "The BigCommunity kernel and modules"


# -- the journey -------------------------------------------------------------


class Menu:
    def __init__(self, chosen, confirm=True):
        self.chosen = chosen
        self.answer = confirm
        self.questions = []

    def choose_packages(self, _selection):
        return self.chosen

    def confirm(self, question, default_yes=True):
        self.questions.append(str(question))
        return self.answer


class GitHubAPI:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.dispatches = []

    @staticmethod
    def ensure_github_token(_logger):
        return True

    def trigger_workflow(self, package_name, branch_type, new_branch, is_aur, tmate, logger, package_directory=""):
        self.dispatches.append((package_name, branch_type, new_branch, package_directory))
        return package_directory not in self.failing


@pytest.fixture
def journey(repository, monkeypatch):
    calls = {"commit": 0, "prepare": 0}

    def commit(_bp, _message):
        calls["commit"] += 1
        return True

    def prepare(_bp, _branch_type, _expected):
        calls["prepare"] += 1
        return "dev-tester"

    monkeypatch.setattr(package_operations, "_commit_pending_changes", commit)
    monkeypatch.setattr(package_operations, "_prepare_working_branch", prepare)
    monkeypatch.setattr(package_operations, "_testing_branch_for_current", lambda _bp, _expected="": "dev-tester")
    monkeypatch.setattr(GitUtils, "get_package_name", staticmethod(lambda directory="": directory or "demo"))

    def run(chosen, failing=(), confirm=True):
        bp = SimpleNamespace(
            is_git_repo=True,
            menu=Menu(chosen, confirm),
            logger=Logger(),
            github_api=GitHubAPI(failing),
            organization="big-comm",
            github_user_name="tester",
            dry_run_mode=False,
        )
        return package_operations.commit_and_generate_package(bp, "testing"), bp, calls

    return run


def test_each_marked_package_is_dispatched_with_its_own_directory(journey):
    chosen = ["linux-big-acpi_call", "linux-big-tp_smapi", "linux-big-zfs"]

    result, bp, calls = journey(chosen)

    assert result is True
    assert bp.github_api.dispatches == [(directory, "testing", "dev-tester", directory) for directory in chosen]
    assert calls == {"commit": 1, "prepare": 1}
    assert len(bp.menu.questions) == 1
    assert all(f"{directory}/" in bp.menu.questions[0] for directory in chosen)


def test_a_failed_dispatch_does_not_stop_the_others(journey):
    chosen = ["linux-big-acpi_call", "linux-big-r8168", "linux-big-zfs"]

    result, bp, _calls = journey(chosen, failing={"linux-big-r8168"})

    assert result is False
    assert [dispatch[3] for dispatch in bp.github_api.dispatches] == chosen
    log = bp.logger.text()
    assert "Package workflows started: linux-big-acpi_call/, linux-big-zfs/" in log
    assert "Package workflows that failed: linux-big-r8168/" in log


def test_declining_the_confirmation_dispatches_nothing(journey):
    result, bp, _calls = journey(["linux-big-zfs", "linux-big-r8168"], confirm=False)

    assert result is False
    assert bp.github_api.dispatches == []


def test_one_marked_package_keeps_the_single_build_flow(journey):
    result, bp, _calls = journey(["linux-big-tp_smapi"])

    assert result is True
    assert bp.github_api.dispatches == [("linux-big-tp_smapi", "testing", "dev-tester", "linux-big-tp_smapi")]
    assert "Directory: linux-big-tp_smapi/" in bp.menu.questions[0]


def test_cancelling_the_selection_commits_nothing_further(journey):
    result, bp, calls = journey(None)

    assert result is False
    assert calls["prepare"] == 0
    assert bp.github_api.dispatches == []


# -- the terminal menu --------------------------------------------------------


def terminal_menu(monkeypatch, keys):
    monkeypatch.setattr(cli_menu.subprocess, "run", lambda *_args, **_kwargs: None)
    menu = cli_menu.MenuSystem(Logger())
    menu.console = Console(file=io.StringIO(), width=100, height=60)
    pending = list(keys)
    monkeypatch.setattr(menu, "_getch", lambda: pending.pop(0))
    return menu


DOWN = [b"\x1b", b"[", b"B"]


def test_the_terminal_marks_with_space_and_confirms_with_enter(monkeypatch):
    menu = terminal_menu(monkeypatch, [*DOWN, b" ", *DOWN, *DOWN, b" ", b"\r"])

    assert menu.choose_packages(selection_of()) == ["linux-big-acpi_call", "linux-big-broadcom-wl"]


def test_the_terminal_ignores_enter_with_nothing_marked(monkeypatch):
    menu = terminal_menu(monkeypatch, [b"\r", b"a", b"n", b"\r", *DOWN, b" ", b"\r"])

    assert menu.choose_packages(selection_of()) == ["linux-big-acpi_call"]


def test_the_terminal_cancels_with_escape(monkeypatch):
    menu = terminal_menu(monkeypatch, [b"\x1b", b"\x1b"])

    assert menu.choose_packages(selection_of()) is None


def test_the_terminal_offers_only_the_main_package_before_building_all(monkeypatch):
    menu = terminal_menu(monkeypatch, [b"a", b"\r"])
    asked = []

    def show_menu(title, options, **kwargs):
        asked.append((title, options, str(kwargs.get("additional_content"))))
        return 0, options[0]

    monkeypatch.setattr(menu, "show_menu", show_menu)

    assert menu.choose_packages(selection_of()) == ["linux-big"]
    assert asked[0][1][:2] == ["Build only linux-big", "Build all anyway"]
    assert "linux-big" in asked[0][2]


def test_the_terminal_builds_all_only_when_explicitly_confirmed(monkeypatch):
    menu = terminal_menu(monkeypatch, [b"a", b"\r"])
    monkeypatch.setattr(menu, "show_menu", lambda _title, options, **_kwargs: (1, options[1]))

    assert menu.choose_packages(selection_of()) == BIG_KERNEL


def test_the_terminal_shows_underscored_names_as_they_are(monkeypatch):
    menu = terminal_menu(monkeypatch, [b"\x1b", b"\x1b"])

    menu.choose_packages(selection_of())

    output = menu.console.file.getvalue()
    assert "linux-big-tp_smapi" in output
    assert "linux-big-acpi_call" in output


# -- the GTK dialog, against a recording double ----------------------------------


class Recorder:
    def __init__(self, **properties):
        self.properties = properties
        self.calls = {}

    def __getattr__(self, attribute):
        def record(*args):
            self.calls.setdefault(attribute, []).append(args)

        return record


class FakeGtk:
    @staticmethod
    def Label(**properties):
        return Recorder(**properties)


class FakePango:
    class EllipsizeMode:
        END = "end"

    class WrapMode:
        WORD_CHAR = "word-char"


def dialog_helpers():
    tree = ast.parse(DIALOG.read_text(encoding="utf-8"))
    wanted = ("_package_name_label", "_package_description_label")
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"Gtk": FakeGtk, "Pango": FakePango, "_": lambda text: text}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(DIALOG), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("directory", ["linux-big-tp_smapi", "linux-big-acpi_call"])
def test_the_dialog_shows_underscored_names_without_mnemonics(directory):
    label = dialog_helpers()["_package_name_label"](PackageChoice(directory, "about it"))

    assert label.properties["label"] == directory
    assert label.calls["set_use_underline"] == [(False,)]
    assert label.calls["set_use_markup"] == [(False,)]


def test_the_dialog_describes_each_package_below_its_name():
    label = dialog_helpers()["_package_description_label"](PackageChoice("linux-big-zfs", "ZFS for linux-big"))

    assert label.properties["label"] == "ZFS for linux-big"
    assert label.calls["set_use_underline"] == [(False,)]


def test_the_dialog_has_a_fixed_wider_size_and_no_back_button():
    source = DIALOG.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sizes = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("_DIALOG_")
    }

    assert sizes == {"_DIALOG_WIDTH": 600, "_DIALOG_HEIGHT": 620}
    assert "set_follows_content_size(False)" in source
    footer = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_build_footer")
    assert "Back" not in ast.unparse(footer)


def test_the_build_button_follows_whether_anything_is_marked():
    tree = ast.parse(DIALOG.read_text(encoding="utf-8"))
    refresh = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_refresh")

    assert "self.build_button.set_sensitive(self.selection.can_confirm)" in ast.unparse(refresh)
    assert "self.warning.set_reveal_child(self.selection.needs_order_warning)" in ast.unparse(refresh)


def test_building_the_main_package_with_others_asks_first():
    tree = ast.parse(DIALOG.read_text(encoding="utf-8"))
    clicked = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_on_build_clicked"
    )
    source = ast.unparse(clicked)

    # The only finish before the question is the one guarded by "no warning".
    assert source.index("if not self.selection.needs_order_warning") < source.index("self._finish(")
    assert "Adw.AlertDialog" in source


def test_a_single_package_repository_is_never_asked(tmp_path, monkeypatch):
    (tmp_path / "PKGBUILD").write_text("pkgname=demo\n", encoding="utf-8")
    monkeypatch.setattr(GitUtils, "get_repo_root_path", staticmethod(lambda: str(tmp_path)))
    menu = mock.Mock()

    assert package_operations._choose_package_directories(mock.Mock(menu=menu, logger=Logger())) == [""]
    menu.choose_packages.assert_not_called()
