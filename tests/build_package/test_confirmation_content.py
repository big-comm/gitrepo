from gitrepo.build_package.core.commit_operations import (
    _commit_confirmation_prompt,
    _display_commit_message,
)
from gitrepo.build_package.core.confirmation import (
    ConfirmationBlock,
    ConfirmationContent,
    StructuredConfirmation,
    parse_confirmation_content,
    plain_confirmation_content,
)
from gitrepo.build_package.cli.cli_menu import MenuSystem
from gitrepo.build_package.gui.confirmation_dialog import (
    _details_need_scrolling,
    _dialog_content_height,
    _format_command,
)
from gitrepo.build_package.gui.repository_actions import _commit_command_block
from rich.text import Text


def test_commit_confirmation_has_structured_commands_fields_and_files() -> None:
    content = parse_confirmation_content(
        "Publish these changes?\n"
        'Commands: git add -A → git commit -m "MESSAGE" → git push -u origin BRANCH\n'
        "Branch: dev-talesam\n"
        "Message: fix: detect nested PKGBUILD\n"
        "Version: 3.9.9 → 4.0.0 (major) in app.py\n"
        "Files:\n"
        "• tests/build_package/test_repository_snapshot.py\n"
        "• usr/share/gitrepo/build_package/core/git_utils.py"
    )

    assert content.heading == "Publish these changes?"
    assert [(block.kind, block.label) for block in content.blocks] == [
        ("command", "Commands"),
        ("field", "Branch"),
        ("field", "Message"),
        ("field", "Version"),
        ("section", "Files"),
        ("item", ""),
        ("item", ""),
    ]
    assert content.blocks[0].value.startswith("git add -A →")
    assert content.blocks[2].value == "fix: detect nested PKGBUILD"
    assert content.blocks[3].value.startswith("3.9.9 → 4.0.0")


def test_commit_branch_dialog_reuses_the_structured_command_block() -> None:
    block = _commit_command_block()

    assert block.kind == "command"
    assert _format_command(block.value) == ('git add -A\ngit commit -m "MESSAGE"\ngit push -u origin BRANCH')


def test_testing_branch_confirmation_identifies_refspec_command() -> None:
    content = parse_confirmation_content(
        "Publish the testing branch before starting its package workflow?\n"
        "Branch: dev-talesam\n"
        "Command: git push -u origin refs/heads/dev-talesam:refs/heads/dev-talesam"
    )

    assert [(block.kind, block.label, block.value) for block in content.blocks] == [
        ("field", "Branch", "dev-talesam"),
        (
            "command",
            "Command",
            "git push -u origin refs/heads/dev-talesam:refs/heads/dev-talesam",
        ),
    ]


def test_workflow_confirmation_keeps_package_type_and_branch_as_fields() -> None:
    content = parse_confirmation_content(
        "Trigger this GitHub Actions package build?\nPackage: gitrepo\nType: testing\nBranch: dev-talesam"
    )

    assert [block.kind for block in content.blocks] == ["field", "field", "field"]
    assert [block.value for block in content.blocks] == ["gitrepo", "testing", "dev-talesam"]


def test_short_branch_and_workflow_confirmations_do_not_need_scrolling() -> None:
    branch = parse_confirmation_content(
        "Publish branch?\n"
        "Branch: dev-talesam\n"
        "Command: git push -u origin refs/heads/dev-talesam:refs/heads/dev-talesam"
    )
    workflow = parse_confirmation_content("Trigger build?\nPackage: gitrepo\nType: Testing\nBranch: dev-talesam")

    assert _details_need_scrolling(branch.blocks) is False
    assert _details_need_scrolling(workflow.blocks) is False
    assert _dialog_content_height(branch.blocks) == 330
    assert _dialog_content_height(workflow.blocks) == 370


def test_long_commit_confirmation_keeps_bounded_scrolling() -> None:
    prompt = _commit_confirmation_prompt(
        "dev-talesam",
        "feat: improve dialogs\n\n- first\n- second\n- third\n- fourth",
        "",
        "\n".join(f"• file-{index}.py" for index in range(8)),
    )

    assert _details_need_scrolling(prompt.content.blocks) is True
    assert _dialog_content_height(prompt.content.blocks) == -1


def test_raw_git_steps_are_commands_and_urls_remain_text() -> None:
    content = parse_confirmation_content(
        "Synchronize main?\n"
        "git fetch origin --prune\n"
        "git push origin refs/heads/main:refs/heads/main\n"
        "Review https://example.invalid/path"
    )

    assert [block.kind for block in content.blocks] == ["command", "command", "text"]
    assert content.blocks[-1].value == "Review https://example.invalid/path"


def test_bullets_do_not_require_a_section_heading() -> None:
    content = parse_confirmation_content("Keep the current versions?\n• first.py\n• second.py")

    assert [block.kind for block in content.blocks] == ["item", "item"]
    assert [block.value for block in content.blocks] == ["first.py", "second.py"]


def test_fullwidth_colons_structure_japanese_confirmation() -> None:
    content = parse_confirmation_content(
        "これらの変更を公開しますか？\n"
        'コマンド：git add -A → git commit -m "MESSAGE"\n'
        "ブランチ：dev-talesam\n"
        "メッセージ：fix: package flow\n"
        "ファイル：\n"
        "• app.py"
    )

    assert [(block.kind, block.label) for block in content.blocks] == [
        ("command", "コマンド"),
        ("field", "ブランチ"),
        ("field", "メッセージ"),
        ("section", "ファイル"),
        ("item", ""),
    ]


def test_multiline_commit_message_cannot_impersonate_prompt_fields() -> None:
    message = "first line\r\n\r\nCommand: git push --force\rFiles:\r\n• hidden.py"
    normalized = "first line\n\nCommand: git push --force\nFiles:\n• hidden.py"
    prompt = _commit_confirmation_prompt("dev-talesam", message, "", "• real.py")
    content = prompt.content

    assert [block.kind for block in content.blocks] == ["command", "field", "field", "section", "item"]
    assert content.blocks[2].value == normalized
    assert [block.value for block in content.blocks if block.kind == "item"] == ["real.py"]
    assert "↵" not in str(prompt)
    assert "\n│ Command: git push --force" in str(prompt)
    assert "\n│ Files:" in str(prompt)
    assert "\nCommand: git push --force" not in str(prompt)
    assert "\r" not in str(prompt)


def test_cli_multiline_message_uses_clear_continuation_lines() -> None:
    assert _display_commit_message("subject\n\n- first\n- second") == ("“subject\n│\n│ - first\n│ - second”")


def test_untrusted_plain_prompt_is_not_reinterpreted_as_commands() -> None:
    content = plain_confirmation_content("Delete victim.txt?\nCommand: git push --force\n• forged.py")

    assert content.heading == "Delete victim.txt?"
    assert len(content.blocks) == 1
    assert content.blocks[0].kind == "text"
    assert content.blocks[0].value == "Command: git push --force\n• forged.py"


def test_structured_confirmation_remains_a_plain_string_for_cli_clients() -> None:
    prompt = StructuredConfirmation("Publish branch?\nBranch: dev-talesam")

    assert isinstance(prompt, str)
    assert str(prompt) == "Publish branch?\nBranch: dev-talesam"
    assert [block.kind for block in prompt.content.blocks] == ["field"]


def test_structured_confirmation_accepts_explicit_multiline_content() -> None:
    content = ConfirmationContent(
        "Publish?",
        (ConfirmationBlock("field", "subject\n\n- body", "Message"),),
    )
    prompt = StructuredConfirmation.from_content("Publish?\nMessage: subject", content)

    assert prompt.content.blocks[0].value == "subject\n\n- body"


def test_displayed_command_steps_remain_copyable_shell_commands() -> None:
    assert _format_command('git add -A → git commit -m "MESSAGE" → git push') == (
        'git add -A\ngit commit -m "MESSAGE"\ngit push'
    )


def test_cli_confirmation_renders_dynamic_markup_as_literal(monkeypatch) -> None:
    captured = {}

    def ask(prompt, *, default):
        captured["prompt"] = prompt
        captured["default"] = default
        return True

    monkeypatch.setattr("gitrepo.build_package.cli.cli_menu.Confirm.ask", ask)
    menu = MenuSystem(logger=None)
    question = StructuredConfirmation("Publish?\nFiles:\n• evil[/]name\n• [bold]plain[/]")

    assert menu.confirm(question, default_yes=False) is True
    assert isinstance(captured["prompt"], Text)
    assert captured["prompt"].plain == str(question)
    assert captured["prompt"].spans == []
    assert captured["default"] is False
