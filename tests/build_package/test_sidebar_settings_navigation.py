from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
GUI_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_package/gui"


def _source(relative_path: str) -> str:
    return (GUI_ROOT / relative_path).read_text(encoding="utf-8")


def test_sidebar_separates_local_git_from_github_automation():
    source = _source("main_window.py")

    assert "self.github_nav_list = Gtk.ListBox()" in source
    assert 'github_group.set_title(_("GitHub"))' in source
    assert "github_group.set_description" not in source
    assert 'sidebar_box.add_css_class("build-package-sidebar")' in source
    assert "button = Gtk.Button(child=content)" in source
    assert 'button.add_css_class("navigation-button")' in source
    assert '_("Behavior"), "preferences-system-symbolic", "local"' in source
    assert '_("Package Generation")' in source
    assert '_("AUR Packages")' in source
    assert '_("Access Tokens")' in source
    assert '"security-high-symbolic",\n                "github",' in source


def test_optional_workflows_stay_discoverable_when_disabled():
    source = _source("main_window.py")

    assert "self.package_widget = PackageWidget(self.build_package, self.settings)" in source
    assert "self.aur_widget = AURWidget(self.build_package, self.settings)" in source
    assert 'if self.settings.get("package_features_enabled"' not in source
    assert 'if self.settings.get("aur_features_enabled"' not in source
    assert "_rebuild_nav_list" not in source


def test_feature_pages_explain_state_and_token_dependency():
    package_source = _source("widgets/package_widget.py")
    aur_source = _source("widgets/aur_widget.py")

    assert '_("Enable package generation")' in package_source
    assert "Access Tokens page" in package_source
    assert "self.workflow_content.set_visible(enabled)" in package_source
    assert '_("Enable AUR package builds")' in aur_source
    assert "requires a GitHub access token" in aur_source
    assert "self.workflow_content.set_visible(enabled)" in aur_source


def test_tokens_and_behavior_are_full_pages_not_hamburger_entries():
    window_source = _source("main_window.py")
    app_source = _source("main_gui.py")
    settings_source = _source("widgets/settings_widgets.py")

    assert "self.tokens_widget = TokenSettingsWidget(self)" in window_source
    assert "self.behavior_widget = BehaviorSettingsWidget(self, self.settings)" in window_source
    assert 'tools_section.append(_("Preferences")' not in window_source
    assert 'app_section.append(_("Preferences")' not in app_source
    assert 'self.main_window.switch_to_page("behavior")' in app_source
    assert "Local Git commands do not need a token." in settings_source
    assert "for organization, _token in entries:" in settings_source
    assert "set_subtitle(token)" not in settings_source
    assert "Adw.ActionRow(title=title)" not in window_source


def test_feature_refresh_preserves_sidebar_and_reconciles_visible_state():
    source = _source("main_window.py")
    refresh_body = source.split("    def refresh_features(self):", 1)[1].split("    def refresh_all_widgets(self):", 1)[
        0
    ]

    assert "sync_feature_enabled()" in refresh_body
    assert "refresh_quick_actions()" in refresh_body
    assert "content_stack.remove" not in refresh_body
    assert "nav_list.remove" not in refresh_body
