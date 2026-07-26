import gettext
import os
from pathlib import Path
import re
import subprocess
import sys

SOURCE_TEXT = "Build and publish a package"
EXPECTED_PT_BR = "Compilar e publicar um pacote"
FORBIDDEN_TRANSLATION_MARKERS = (
    "<NL",
    "<x",
    "<br",
    "|NL|",
    "|NEXT|",
    "|||",
    "<>",
    "](commit)[",
)
PROTECTED_LITERALS = (
    "GitRepo",
    "BigLinux",
    "BigCommunity",
    "GitHub",
    "Docker",
    "Podman",
    "Manjaro",
    "Arch Linux",
    "tmate",
    "AUR",
    "PKGBUILD",
    "APP_VERSION",
    "APP_NAME",
    "MIT",
    "git add",
    "git commit",
    "git push",
    "git pull",
    "git fetch",
    "git checkout",
    "git merge",
    "git reset",
    "git diff",
    "git stash",
    "git branch",
    "makepkg",
)
PROTECTED_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])origin(?:/\{\d+\}|/main)?"),
    re.compile(r"refs/[A-Za-z0-9_{}^*/.:-]+"),
    re.compile(r"backup/[A-Za-z0-9_{}^*/.:-]*[A-Za-z0-9_{}*]"),
    re.compile(r"HEAD(?:\^\d+)?"),
    re.compile(r"(?<![A-Za-z0-9_])(?:MESSAGE|BRANCH|FILE)(?![A-Za-z0-9_])"),
    re.compile(r"--[a-z][a-z-]*"),
    re.compile(r"(?<![\w])-A\b"),
    re.compile(r"(?<![\w])-u\b"),
    re.compile(r"github\.com/[A-Za-z0-9_./-]+"),
    re.compile(r"dev-[A-Za-z0-9_{}-]+"),
)


def test_pt_br_translation_uses_packaged_catalog() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "LANGUAGE": "pt_BR",
            "LC_ALL": "C.UTF-8",
            "PYTHONPATH": "usr/share",
        }
    )
    command = (
        "import importlib; module = importlib.import_module('gitrepo.common.translation'); "
        f"assert module._({SOURCE_TEXT!r}) == {EXPECTED_PT_BR!r}"
    )

    subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _translated_messages(mo_bytes: bytes, tmp_path: Path) -> str:
    """Return the messages a compiled catalog actually ships, header excluded."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    compiled = tmp_path / "catalog.mo"
    compiled.write_bytes(mo_bytes)
    dumped = subprocess.run(
        ["msgunfmt", "--no-wrap", str(compiled)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    body = dumped.split('msgid ""\n', 1)[-1]
    return body.split("\n\n", 1)[-1].strip()


def _runtime_messages(path: Path) -> dict[str, str]:
    with path.open("rb") as handle:
        catalog = gettext.GNUTranslations(handle)._catalog
    return {
        source: target
        for source, target in catalog.items()
        if isinstance(source, str) and source and isinstance(target, str)
    }


def _protected_terms(source: str) -> set[str]:
    terms = {term for term in PROTECTED_LITERALS if term in source}
    for pattern in PROTECTED_PATTERNS:
        terms.update(pattern.findall(source))
    return terms


def test_shipped_catalogs_match_their_sources(tmp_path) -> None:
    """A stale .mo shows a mixed-language interface even with a complete .po."""
    for catalog_path in sorted(Path("locale").glob("*.po")):
        language = catalog_path.stem.replace("-", "_")
        installed = Path("usr/share/locale") / language / "LC_MESSAGES/gitrepo.mo"
        assert installed.is_file(), f"missing compiled catalog for {catalog_path}"

        rebuilt = subprocess.run(
            ["msgfmt", "--check", "--output-file=-", str(catalog_path)],
            check=True,
            capture_output=True,
        ).stdout

        assert _translated_messages(installed.read_bytes(), tmp_path / language) == _translated_messages(
            rebuilt, tmp_path / f"{language}-rebuilt"
        ), f"{installed} is out of date; recompile it from {catalog_path}"


def test_catalogs_are_valid_and_reproducible() -> None:
    template_text = Path("locale/gitrepo.pot").read_text(encoding="utf-8")
    assert "Project-Id-Version: GitRepo 3.8.1" in template_text
    assert not any(line.startswith("#: /") for line in template_text.splitlines())

    for catalog_path in sorted(Path("locale").glob("*.po")):
        catalog_text = catalog_path.read_text(encoding="utf-8")
        assert "Project-Id-Version: GitRepo 3.8.1" in catalog_text
        assert "#~ " not in catalog_text, f"obsolete entry in {catalog_path}"
        assert not any(line.startswith("#: /") for line in catalog_text.splitlines()), (
            f"absolute source reference in {catalog_path}"
        )
        subprocess.run(
            ["msgfmt", "--check", "--check-format", "--output-file=/dev/null", catalog_path],
            check=True,
            capture_output=True,
            text=True,
        )


def test_runtime_translations_preserve_structure_and_identifiers() -> None:
    for catalog_path in sorted(Path("locale").glob("*.po")):
        language = catalog_path.stem.replace("-", "_")
        installed = Path("usr/share/locale") / language / "LC_MESSAGES/gitrepo.mo"

        for source, target in _runtime_messages(installed).items():
            assert source.count("\n") == target.count("\n"), f"newline structure changed in {catalog_path}: {source!r}"
            assert source[:1].isspace() == target[:1].isspace(), (
                f"leading whitespace changed in {catalog_path}: {source!r}"
            )
            assert source[-1:].isspace() == target[-1:].isspace(), (
                f"trailing whitespace changed in {catalog_path}: {source!r}"
            )

            if "|" not in source:
                assert "|" not in target, f"unexpected protocol delimiter in {catalog_path}: {source!r}"
            if not any(character in source for character in "<>[]"):
                assert not any(character in target for character in "<>[]"), (
                    f"unexpected markup delimiter in {catalog_path}: {source!r}"
                )
            for marker in FORBIDDEN_TRANSLATION_MARKERS:
                assert marker not in target, f"translation protocol marker {marker!r} in {catalog_path}: {source!r}"
            for term in _protected_terms(source):
                assert term in target, f"protected term {term!r} changed in {catalog_path}: {source!r}"
