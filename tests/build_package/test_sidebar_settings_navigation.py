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
    # Four destinations: three local journeys plus the GitHub packaging one.
    assert '_("Publish Changes"), "build-package-commit", "local"' in source
    assert '_("Organize Branches"), "build-package-branches", "local"' in source
    assert '_("Packages"), "build-package-package", "github"' in source
    assert '_("Settings"), "build-package-advanced", "local"' in source


def test_optional_workflows_stay_discoverable_when_disabled():
    source = _source("main_window.py")

    # Both workflows are built unconditionally and hosted by the Packages page.
    assert "self.package_widget = PackageWidget(self.build_package, self.settings, show_hero=False)" in source
    assert "self.aur_widget = AURWidget(self.build_package, self.settings, show_hero=False)" in source
    assert '("repository", _("This repository"), "build-package-package", self.package_widget)' in source
    assert '("aur", _("AUR"), "build-package-aur", self.aur_widget)' in source
    assert 'if self.settings.get("package_features_enabled"' not in source
    assert 'if self.settings.get("aur_features_enabled"' not in source
    assert "_rebuild_nav_list" not in source


def test_feature_pages_explain_state_and_token_dependency():
    package_source = _source("widgets/package_widget.py")
    aur_source = _source("widgets/aur_widget.py")

    assert '_("Enable package generation")' in package_source
    # The token dependency is stated once on the row, not repeated by the
    # group description and the empty state as well.
    assert "Requires a GitHub access token." in package_source
    assert "needs an access token" in package_source
    assert "self.workflow_content.set_visible(enabled)" in package_source
    assert '_("Enable AUR package builds")' in aur_source
    assert "requires a GitHub access token" in aur_source
    assert "self.workflow_content.set_visible(enabled)" in aur_source


def test_tokens_and_behavior_are_reachable_contexts_not_hamburger_entries():
    window_source = _source("main_window.py")
    app_source = _source("main_gui.py")
    settings_source = _source("widgets/settings_widgets.py")

    # They are sections of the Settings destination, not menu items or tabs.
    assert "self.settings_page = StackedPage(" in window_source
    assert "[self.behavior_widget, self.tokens_widget, self.advanced_widget]" in window_source
    assert 'tools_section.append(_("Preferences")' not in window_source
    assert 'app_section.append(_("Preferences")' not in app_source
    assert 'self.main_window.switch_to_page("settings")' in app_source
    assert "Local Git commands do not need a token." in settings_source
    assert "for organization, _token in entries:" in settings_source
    assert "set_subtitle(token)" not in settings_source


def test_feature_refresh_preserves_sidebar_and_reconciles_visible_state():
    source = _source("main_window.py")
    refresh_body = source.split("    def refresh_features(self):", 1)[1].split("    def refresh_all_widgets(self):", 1)[
        0
    ]

    assert "sync_feature_enabled()" in refresh_body
    assert "sync_from_settings()" in refresh_body
    assert "package_widget.sync_from_settings()" not in refresh_body
    assert "content_stack.remove" not in refresh_body
    assert "nav_list.remove" not in refresh_body


def test_a_repeated_row_subtitle_does_not_restate_the_group_description():
    source = _source("widgets/branch_widget.py")

    # The group already says selecting a branch runs git checkout; repeating it
    # on every row turned the list into one sentence printed many times.
    assert '_("Select to run git checkout")' not in source
    assert '_("Only on origin; created locally on first checkout")' in source
    assert "Selecting another branch runs git checkout BRANCH" in source


def test_pending_work_is_not_presented_as_a_warning():
    source = _source("widgets/commit_widget.py")

    # Having changes to publish is the reason this page exists.
    assert '_("Uncommitted changes present")' not in source
    assert '_("Ready to publish")' in source


def test_a_required_choice_is_stated_in_words_not_in_amber_text():
    source = _source("widgets/commit_widget.py")

    assert 'self.commit_type_expander.add_css_class("warning")' not in source
    assert 'self.commit_type_expander.remove_css_class("warning")' not in source
    assert '_("Required — select the type of change")' in source
