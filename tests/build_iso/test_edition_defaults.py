from gitrepo.build_iso.gui.widgets.build_widget import _edition_for_distro


EDITIONS = ("cinnamon", "gnome", "kde", "xfce")


def test_each_distribution_has_its_own_default_edition() -> None:
    assert _edition_for_distro("bigcommunity", EDITIONS, {}) == "gnome"
    assert _edition_for_distro("biglinux", EDITIONS, {}) == "kde"


def test_saved_and_session_choices_override_the_distribution_default() -> None:
    assert _edition_for_distro("bigcommunity", EDITIONS, {"bigcommunity": "xfce"}) == "xfce"
    assert _edition_for_distro("biglinux", EDITIONS, {"biglinux": "gnome"}) == "gnome"


def test_pending_external_choice_has_highest_priority() -> None:
    preferences = {"bigcommunity": "xfce"}

    assert _edition_for_distro("bigcommunity", EDITIONS, preferences, "kde") == "kde"


def test_missing_default_uses_first_available_edition() -> None:
    assert _edition_for_distro("bigcommunity", ("cinnamon", "xfce"), {}) == "cinnamon"
    assert _edition_for_distro("unknown", (), {}) == ""
