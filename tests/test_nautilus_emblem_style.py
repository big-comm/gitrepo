"""Only GitRepo badges bypass inherited grid-emblem dimming."""

from gi.repository import Gio

from gitrepo.file_manager import nautilus_style


class Widget:
    def __init__(self, *classes):
        self.classes = set(classes)
        self.sibling = None

    def get_next_sibling(self):
        return self.sibling

    def has_css_class(self, name):
        return name in self.classes

    def add_css_class(self, name):
        self.classes.add(name)

    def remove_css_class(self, name):
        self.classes.discard(name)


class Image(Widget):
    def __init__(self, icon):
        super().__init__()
        self.icon = Gio.ThemedIcon.new(icon)

    def get_gicon(self):
        return self.icon


class Box(Widget):
    def __init__(self, images):
        super().__init__("dim-label")
        self.images = images
        for first, second in zip(images, images[1:]):
            first.sibling = second

    def get_first_child(self):
        return self.images[0] if self.images else None


def test_gitrepo_colors_are_restored_without_undimming_other_badges(monkeypatch):
    monkeypatch.setattr(nautilus_style.Gtk, "Image", Image)
    style = nautilus_style.EmblemStyle.__new__(nautilus_style.EmblemStyle)
    ours = Image("emblem-gitrepo-modified")
    unrelated = Image("emblem-readonly-symbolic")
    box = Box([ours, unrelated])
    style._style_box(box)
    assert box.has_css_class("gitrepo-emblems")
    assert not ours.has_css_class("dim-label")
    assert unrelated.has_css_class("dim-label")

    ours.icon = Gio.ThemedIcon.new("starred-symbolic")
    style._style_box(box)
    assert not box.has_css_class("gitrepo-emblems")
    assert not unrelated.has_css_class("dim-label")


def test_unrelated_emblems_keep_existing_styles(monkeypatch):
    monkeypatch.setattr(nautilus_style.Gtk, "Image", Image)
    style = nautilus_style.EmblemStyle.__new__(nautilus_style.EmblemStyle)
    image = Image("emblem-readonly-symbolic")
    image.add_css_class("dim-label")
    box = Box([image])
    style._style_box(box)
    assert box.classes == {"dim-label"}
    assert image.classes == {"dim-label"}
