from core.config import APP_NAME
from gui.main_window import MainWindow


class RefreshTarget:
    def __init__(self):
        self.status_refreshes = 0
        self.badge_refreshes = 0

    def refresh_status(self):
        self.status_refreshes += 1

    def update_nav_badges(self):
        self.badge_refreshes += 1


def test_refresh_all_widgets_includes_window_status():
    target = RefreshTarget()

    MainWindow.refresh_all_widgets(target)

    assert target.status_refreshes == 1
    assert target.badge_refreshes == 1


def test_application_name_is_gitrepo():
    assert APP_NAME == "GitRepo"
