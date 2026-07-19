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
