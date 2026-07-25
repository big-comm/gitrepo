from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
GUI_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_package/gui"
CORE_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_package/core"


def _source(relative_path: str) -> str:
    return (GUI_ROOT / relative_path).read_text(encoding="utf-8")


def test_dashboard_teaches_real_update_and_publish_commands():
    source = _source("widgets/overview_widget.py")

    assert '_("Learn Git while managing this repository")' not in source
    assert '_("Download updates")' in source
    assert "Downloads and combines the remote branch. Local changes are preserved." in source
    # Commands are shown as code, in their own monospace block.
    assert 'command_label.add_css_class("build-package-command-block")' in source
    assert "self.quick_actions_flow.set_min_children_per_line(2)" in source
    assert "self.quick_actions_flow.set_max_children_per_line(2)" in source
    assert '"git fetch origin BRANCH"' in source
    assert '"git merge --no-edit origin/BRANCH"' in source
    assert '_("Publish changes")' in source
    assert "Records and sends pending changes." in source
    assert '"git add -A"' in source
    assert 'git commit -m "MESSAGE"' in source
    assert '"git push -u origin BRANCH"' in source


def test_branch_and_maintenance_pages_distinguish_git_from_github_actions():
    branch_source = _source("widgets/branch_widget.py")
    maintenance_source = _source("widgets/advanced_widget.py")

    assert '"git checkout main"' in branch_source
    assert '_("Open Pull Request")' in branch_source
    assert "github_action_description" in branch_source
    assert '"git branch -D BRANCH"' in maintenance_source
    assert '"git push origin --delete BRANCH"' in maintenance_source
    assert '_("delete failed GitHub Actions runs; no Git command is used")' in maintenance_source
    assert '_("delete refs/tags through the GitHub API; local tags are unchanged")' in maintenance_source


def test_recovery_page_exposes_the_commands_for_both_methods():
    source = _source("widgets/advanced_widget.py")

    assert '"git checkout COMMIT -- ."' in source
    assert '"git reset --hard COMMIT"' in source
    assert '"git push origin BRANCH --force (if remote)"' in source


def test_aur_page_does_not_claim_to_create_a_local_branch():
    source = _source("widgets/aur_widget.py")

    assert '_("GitHub Actions workflow — no local branch is created")' in source
    assert '_("• No local Git command or branch will be created")' in source
    assert "Create branch:" not in source


def test_cli_confirmation_uses_the_same_didactic_publish_vocabulary():
    operations_source = (CORE_ROOT / "commit_operations.py").read_text(encoding="utf-8")
    handler_source = (CORE_ROOT / "commit_handler.py").read_text(encoding="utf-8")

    assert "Publish these changes?" in operations_source
    assert 'git commit -m "MESSAGE"' in operations_source
    assert "Use 'Download updates' first" in handler_source
    assert "Pull Latest" not in handler_source
