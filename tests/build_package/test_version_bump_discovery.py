"""APP_VERSION alone is enough; ownership only settles a genuine ambiguity."""

from types import SimpleNamespace

from gitrepo.build_package.core import version_bumper


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


def _bumper(tmp_path):
    return SimpleNamespace(
        repo_path=str(tmp_path),
        _app_version_cache=None,
        _app_version_warning_shown=False,
        logger=Logger(),
    )


def _repository(tmp_path, pkgname="jellyfix"):
    (tmp_path / "PKGBUILD").write_text(f"pkgname={pkgname}\n", encoding="utf-8")
    return tmp_path


def test_a_lone_app_version_needs_no_ownership_marker(tmp_path):
    """The common case: one app, one constant, no extra declaration."""
    repository = _repository(tmp_path)
    source = repository / "config.py"
    source.write_text('APP_VERSION = "2.9.2"\n', encoding="utf-8")

    plan = version_bumper.plan_version_bump(_bumper(repository), "fix: correct a thing")

    assert plan is not None
    assert plan.current_version == "2.9.2"
    assert plan.new_version == "2.9.3"
    assert plan.relative_path == "config.py"


def test_a_lone_app_version_is_bumped_even_when_named_after_another_project(tmp_path):
    """Ownership is irrelevant while there is nothing to disambiguate."""
    repository = _repository(tmp_path, pkgname="widgets")
    source = repository / "config.py"
    source.write_text('APP_NAME = "Something Else"\nAPP_VERSION = "1.0.0"\n', encoding="utf-8")

    plan = version_bumper.plan_version_bump(_bumper(repository), "feat: add a thing")

    assert plan is not None
    assert plan.new_version == "1.1.0"


def test_a_vendored_version_is_never_bumped_in_place_of_the_owned_one(tmp_path):
    """Two constants, one marked: the marked one wins and the vendor is safe."""
    repository = _repository(tmp_path)
    owned = repository / "config.py"
    owned.write_text('APP_VERSION_OWNER = "jellyfix"\nAPP_VERSION = "2.9.2"\n', encoding="utf-8")
    vendored = repository / "vendor" / "libfoo"
    vendored.mkdir(parents=True)
    untouched = vendored / "version.py"
    untouched.write_text('APP_VERSION = "3.7.2"\n', encoding="utf-8")
    before = untouched.read_bytes()

    context = _bumper(repository)
    plan = version_bumper.plan_version_bump(context, "fix: correct a thing")

    assert plan is not None
    assert plan.relative_path == "config.py"
    assert plan.new_version == "2.9.3"
    assert version_bumper.publish_version_bump(context, plan) is True
    assert untouched.read_bytes() == before


def test_two_unmarked_versions_are_left_alone_and_both_are_named(tmp_path):
    """Refusing is right, but the user must learn which files caused it."""
    repository = _repository(tmp_path)
    first = repository / "config.py"
    first.write_text('APP_VERSION = "2.9.2"\n', encoding="utf-8")
    second = repository / "other.py"
    second.write_text('APP_VERSION = "3.7.2"\n', encoding="utf-8")
    untouched = (first.read_bytes(), second.read_bytes())

    context = _bumper(repository)
    plan = version_bumper.plan_version_bump(context, "fix: correct a thing")

    assert plan is None
    assert (first.read_bytes(), second.read_bytes()) == untouched
    warning = " ".join(message for _style, message in context.logger.messages)
    assert "config.py" in warning and "other.py" in warning
    assert "APP_VERSION_OWNER" in warning


def test_an_empty_repository_still_reports_the_missing_constant(tmp_path):
    repository = _repository(tmp_path)
    (repository / "README.md").write_text("no version here\n", encoding="utf-8")

    context = _bumper(repository)

    assert version_bumper.plan_version_bump(context, "fix: correct a thing") is None
    assert any("APP_VERSION" in message for _style, message in context.logger.messages)
