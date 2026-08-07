"""Parse plain confirmation prompts into presentation-safe blocks."""

import re
from dataclasses import dataclass
from typing import Literal


BlockKind = Literal["command", "field", "item", "section", "text"]

_BULLET_PATTERN = re.compile(r"^[•*-]\s+(?P<value>.+)$")
_ASCII_FIELD_PATTERN = re.compile(r"^(?P<label>[^:：\n]{1,48}):(?:[ \t]+(?P<value>.*)|[ \t]*)$")
_FULLWIDTH_FIELD_PATTERN = re.compile(r"^(?P<label>[^:：\n]{1,48})：[ \t]*(?P<value>.*)$")
_COMMAND_PATTERN = re.compile(
    r"^(?:sudo\s+)?(?:git|gh|makepkg|python3?|pytest|ruff|docker|podman|flatpak|bash|sh)(?:\s|$)|^\./"
)


@dataclass(frozen=True, slots=True)
class ConfirmationBlock:
    """One semantic line in a confirmation prompt."""

    kind: BlockKind
    value: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class ConfirmationContent:
    """Heading and structured details extracted from a plain prompt."""

    heading: str
    blocks: tuple[ConfirmationBlock, ...]


class StructuredConfirmation(str):
    """Plain CLI text carrying trusted semantic blocks for graphical clients."""

    def __new__(cls, question: str):
        instance = super().__new__(cls, question)
        instance.content = parse_confirmation_content(question)
        return instance

    @classmethod
    def from_content(cls, question: str, content: ConfirmationContent):
        """Carry explicit graphical content without reparsing dynamic values."""
        instance = str.__new__(cls, question)
        instance.content = content
        return instance


def _looks_like_command(value: str) -> bool:
    return bool(_COMMAND_PATTERN.match(value.strip()))


def parse_confirmation_content(question: str) -> ConfirmationContent:
    """Preserve prompt text while identifying fields, commands, and lists."""
    lines = [line.strip() for line in str(question).splitlines() if line.strip()]
    if not lines:
        return ConfirmationContent("", ())

    blocks: list[ConfirmationBlock] = []
    for line in lines[1:]:
        bullet = _BULLET_PATTERN.match(line)
        if bullet:
            blocks.append(ConfirmationBlock("item", bullet.group("value")))
            continue

        field = _ASCII_FIELD_PATTERN.match(line) or _FULLWIDTH_FIELD_PATTERN.match(line)
        if field:
            label = field.group("label").strip()
            value = (field.group("value") or "").strip()
            if not value:
                blocks.append(ConfirmationBlock("section", label=label))
            elif _looks_like_command(value):
                blocks.append(ConfirmationBlock("command", value=value, label=label))
            else:
                blocks.append(ConfirmationBlock("field", value=value, label=label))
            continue

        kind: BlockKind = "command" if _looks_like_command(line) else "text"
        blocks.append(ConfirmationBlock(kind, value=line))

    return ConfirmationContent(lines[0], tuple(blocks))


def plain_confirmation_content(question: str) -> ConfirmationContent:
    """Keep an unstructured prompt literal instead of inferring dynamic data."""
    text = str(question).strip()
    if not text:
        return ConfirmationContent("", ())

    heading, separator, body = text.partition("\n")
    blocks = (ConfirmationBlock("text", body.strip()),) if separator and body.strip() else ()
    return ConfirmationContent(heading.strip(), blocks)
