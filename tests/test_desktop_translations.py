from pathlib import Path


DESKTOP_LANGUAGES = {
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "et",
    "fi",
    "fr",
    "he",
    "hr",
    "hu",
    "is",
    "it",
    "ja",
    "ko",
    "nl",
    "no",
    "pl",
    "pt",
    "pt_BR",
    "ro",
    "ru",
    "sk",
    "sv",
    "tr",
    "uk",
    "zh",
}

TRANSLATED_FIELDS = {
    Path("usr/share/applications/org.bigcommunity.buildiso.desktop"): {
        "Desktop Entry": {"Name", "GenericName", "Comment"},
    },
    Path("usr/share/applications/org.bigcommunity.gitrepo.desktop"): {
        "Desktop Entry": {"Name", "GenericName", "Comment"},
    },
    Path("usr/share/kio/servicemenus/gitrepo.desktop"): {
        "Desktop Entry": {"Name"},
        "Desktop Action OpenInGitRepo": {"Name"},
    },
    Path("usr/share/thunar/sendto/gitrepo.desktop"): {
        "Desktop Entry": {"Name", "GenericName", "Comment"},
    },
}


def parse_desktop_fields(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current_section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            sections[current_section] = {}
            continue
        key, value = line.split("=", 1)
        assert key not in sections[current_section], f"duplicate {key} in {path}"
        sections[current_section][key] = value
    return sections


def test_desktop_files_cover_every_shipped_language() -> None:
    for path, required_sections in TRANSLATED_FIELDS.items():
        sections = parse_desktop_fields(path)
        for section_name, base_fields in required_sections.items():
            fields = sections[section_name]
            for base_field in base_fields:
                assert fields[base_field]
                localized_languages = {
                    key.removeprefix(f"{base_field}[").removesuffix("]")
                    for key, value in fields.items()
                    if key.startswith(f"{base_field}[") and value
                }
                assert localized_languages == DESKTOP_LANGUAGES, (
                    f"{path} [{section_name}] {base_field} has an incomplete language set"
                )


def test_desktop_language_set_matches_packaged_catalogs() -> None:
    catalog_languages = {path.stem.replace("-", "_") for path in Path("locale").glob("*.po") if path.stem != "en"}

    assert DESKTOP_LANGUAGES == catalog_languages
