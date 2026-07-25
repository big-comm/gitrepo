import os
from pathlib import Path
import subprocess
import sys

SOURCE_TEXT = "Build and publish a package"
EXPECTED_PT_BR = "Compilar e publicar um pacote"


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


def test_catalogs_are_valid_and_do_not_contain_literal_newline_markers() -> None:
    for catalog_path in sorted(Path("locale").glob("*.po")):
        catalog_text = catalog_path.read_text(encoding="utf-8")
        assert "<NL>" not in catalog_text, f"literal <NL> marker in {catalog_path}"
        subprocess.run(
            ["msgfmt", "--check", "--output-file=/dev/null", catalog_path],
            check=True,
            capture_output=True,
            text=True,
        )
