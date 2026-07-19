import re
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
SYSTEM_ICON_ROOT = PROJECT_ROOT / "usr/share/icons/hicolor/scalable"
PRIVATE_ICON_ROOT = PROJECT_ROOT / "usr/share/gitrepo/icons"
GUI_ROOTS = (
    PROJECT_ROOT / "usr/share/gitrepo/build_iso/gui",
    PROJECT_ROOT / "usr/share/gitrepo/build_package/gui",
)

EXPECTED_PRIVATE_ICONS = {
    "build-iso-build-image.svg",
    "build-iso-create.svg",
    "build-iso-dashboard.svg",
    "build-iso-engine.svg",
    "build-iso-environment.svg",
    "build-iso-history.svg",
    "build-iso-profile.svg",
    "build-iso-profiles.svg",
    "build-iso-settings.svg",
    "build-iso-source.svg",
    "build-iso-storage.svg",
    "build-package-advanced.svg",
    "build-package-aur.svg",
    "build-package-branches.svg",
    "build-package-cleanup.svg",
    "build-package-commit.svg",
    "build-package-extra.svg",
    "build-package-overview.svg",
    "build-package-package.svg",
    "build-package-pull.svg",
    "build-package-repository.svg",
    "build-package-revert.svg",
    "build-package-stable.svg",
    "build-package-testing.svg",
    "gitrepo-status-checking-symbolic.svg",
    "gitrepo-status-error-symbolic.svg",
    "gitrepo-status-ready-symbolic.svg",
    "gitrepo-status-warning-symbolic.svg",
    "org.bigcommunity.buildpackage.svg",
}


def test_system_icon_theme_contains_only_desktop_application_icons():
    installed_icons = {
        icon_path.relative_to(SYSTEM_ICON_ROOT).as_posix() for icon_path in SYSTEM_ICON_ROOT.rglob("*.svg")
    }

    assert installed_icons == {"apps/build-iso.svg", "apps/gitrepo.svg"}


def test_private_icons_are_flat_complete_and_valid_svg():
    assert {path.name for path in PRIVATE_ICON_ROOT.glob("*.svg")} == EXPECTED_PRIVATE_ICONS
    assert not [path for path in PRIVATE_ICON_ROOT.iterdir() if path.is_dir()]

    for icon_name in EXPECTED_PRIVATE_ICONS:
        root = ET.parse(PRIVATE_ICON_ROOT / icon_name).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_gui_and_private_icon_catalog_have_no_missing_or_unused_icons():
    referenced_names = set()
    icon_pattern = re.compile(
        r'"(build-iso(?:-(?:build-image|create|dashboard|engine|environment|history|profile|profiles|settings|source|storage))?'
        r"|build-package-(?:advanced|aur|branches|cleanup|commit|extra|overview|package|pull|repository|revert|stable|testing)"
        r'|gitrepo-status-(?:checking|error|ready|warning)-symbolic|org\.bigcommunity\.buildpackage)"'
    )
    for gui_root in GUI_ROOTS:
        for source_path in gui_root.rglob("*.py"):
            referenced_names.update(icon_pattern.findall(source_path.read_text(encoding="utf-8")))

    installed_names = {
        "build-iso",
        "gitrepo",
        *(Path(icon_name).stem for icon_name in EXPECTED_PRIVATE_ICONS),
    }
    assert referenced_names <= installed_names, (
        "GUI references icons missing from the system or private icon trees: "
        f"{sorted(referenced_names - installed_names)}"
    )
    private_icon_names = {Path(icon_name).stem for icon_name in EXPECTED_PRIVATE_ICONS}
    assert private_icon_names <= referenced_names, (
        f"Private icons have no GUI consumer: {sorted(private_icon_names - referenced_names)}"
    )


def test_both_applications_register_the_shared_private_icon_root():
    for gui_root in GUI_ROOTS:
        application_source = (gui_root / "main_gui.py").read_text(encoding="utf-8")
        assert 'os.path.join(os.path.dirname(__file__), "..", "..")' in application_source
        assert 'icons_dir = os.path.join(project_root, "icons")' in application_source
        assert '"/usr/share/icons"' not in application_source


def test_build_iso_dashboard_hero_uses_dashboard_icon():
    dashboard_source = (GUI_ROOTS[0] / "widgets/dashboard_widget.py").read_text(encoding="utf-8")

    assert 'PageHero(\n            "build-iso-dashboard",' in dashboard_source
