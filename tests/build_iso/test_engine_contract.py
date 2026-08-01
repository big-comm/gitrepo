# The build itself lives in iso-profiles/build-iso/build-iso.sh -- the same
# engine the GitLab pipeline and the GitHub workflow run, tested in that
# repository. What gitrepo owns is the contract: clone the right checkouts and
# hand the engine the right environment.

import unittest.mock as mock
from pathlib import Path

import pytest

import gitrepo.build_iso.core.iso_builder as iso_builder_module
from gitrepo.build_iso.core.iso_builder import BUILD_ENGINE_REPO, ISOBuilder


def _builder(tmp_path: Path, **extra) -> ISOBuilder:
    config = {"container_engine": "docker", "output_dir": str(tmp_path)}
    config.update(extra)
    return ISOBuilder(config)


def _env(builder: ISOBuilder) -> dict[str, str]:
    """The -e assignments _run_container passes to the engine."""
    argv = []
    builder_env = {}
    # The env pairs are built inline in _run_container, so read them off the
    # command it would launch rather than starting a container.
    process = mock.Mock()
    process.stdout = mock.Mock()
    process.stdout.read = mock.Mock(return_value=b"")
    process.wait = mock.Mock()
    process.returncode = 0
    with mock.patch.object(
        iso_builder_module.subprocess, "Popen", side_effect=lambda a, **k: argv.append(a) or process
    ):
        assert builder._run_container() is True
    cmd = argv[0]
    for i, item in enumerate(cmd):
        if item == "-e" and "=" in cmd[i + 1]:
            key, value = cmd[i + 1].split("=", 1)
            builder_env[key] = value
    return builder_env


def test_the_engine_checkout_is_cloned_and_recorded(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert 'git clone --depth 1 "$ENGINE_REPO"' in script
    assert "GITREPO-MANIFEST iso-profiles" in script
    assert "bash /root/gitrepo-build/iso-profiles/build-iso/build-iso.sh" in script
    # Exactly one ISO must come out, or the build failed.
    assert "-name '*.iso' | wc -l" in script


def test_biglinux_builds_from_the_engine_checkout_itself(tmp_path):
    builder = _builder(
        tmp_path,
        distroname="biglinux",
        iso_profiles_repo="https://github.com/biglinux/iso-profiles",
    )

    assert builder._uses_separate_profiles() is False
    assert "PROFILES_ROOT" not in _env(builder)
    # One clone only: the engine checkout is the profiles checkout.
    assert builder._build_setup_script().count("git clone") == 1


def test_bigcommunity_brings_its_own_profiles_checkout(tmp_path):
    builder = _builder(
        tmp_path,
        distroname="bigcommunity",
        iso_profiles_repo="https://github.com/big-comm/iso-profiles",
        branches={"manjaro": "stable", "community": "testing", "biglinux": "stable"},
    )

    assert builder._uses_separate_profiles() is True
    script = builder._build_setup_script()
    assert 'git clone --depth 1 "$ISO_PROFILES_REPO"' in script
    assert "GITREPO-MANIFEST profiles" in script

    env = _env(builder)
    assert env["PROFILES_ROOT"] == "/root/gitrepo-build/profiles"
    assert env["DISTRONAME"] == "bigcommunity"
    assert env["BIGCOMMUNITY_BRANCH"] == "testing"


def test_local_profiles_are_copied_not_edited_in_place(tmp_path):
    profiles = tmp_path / "my-profiles"
    profiles.mkdir()
    builder = _builder(
        tmp_path,
        iso_profiles_source="local",
        iso_profiles_local_path=str(profiles),
    )

    script = builder._build_setup_script()
    # The mount is read-only and the engine edits profiles in place, so the
    # script must copy before building.
    assert "cp -a /root/gitrepo-input/iso-profiles /root/gitrepo-build/profiles" in script
    assert _env(builder)["PROFILES_ROOT"] == "/root/gitrepo-build/profiles"


def test_the_engine_env_contract_is_complete(tmp_path):
    env = _env(
        _builder(
            tmp_path,
            distroname="biglinux",
            edition="kde",
            kernel="lts",
            branches={"manjaro": "testing", "biglinux": "testing", "community": ""},
        )
    )

    assert env["ENGINE_REPO"] == BUILD_ENGINE_REPO
    assert env["EDITION"] == "kde"
    assert env["KERNEL"] == "lts"
    assert env["MANJARO_BRANCH"] == "testing"
    assert env["BIGLINUX_BRANCH"] == "testing"
    # An empty community branch must not reach the engine, which validates it.
    assert env["BIGCOMMUNITY_BRANCH"] == "stable"
    assert env["WORK_PATH"] == "/root/gitrepo-build/output"
    assert "BUILD_MIRROR" not in env


def test_the_engine_owns_the_default_mirror(tmp_path):
    # Leaving this unset lets the checked-out iso-profiles engine choose its
    # own default, keeping local, CI and GUI builds in sync.
    assert "BUILD_MIRROR" not in _env(_builder(tmp_path))


def test_a_configured_mirror_overrides_the_default(tmp_path):
    builder = _builder(tmp_path, build_mirror="https://linorg.usp.br/manjaro")

    assert _env(builder)["BUILD_MIRROR"] == "https://linorg.usp.br/manjaro"


@pytest.mark.parametrize(
    "mirror",
    [
        "https://example.org/m; rm -rf /",
        "https://example.org/$(id)",
        "https://example.org/`id`",
        "https://example.org/m'\nbuild_mirror=evil",
        "ftp://example.org/manjaro",
        "not-a-url",
    ],
)
def test_an_unsafe_mirror_is_refused(tmp_path, mirror):
    # The mirror becomes an environment value the engine writes into
    # manjaro-tools.conf, which the build sources; shell syntax must never
    # get that far.
    with pytest.raises(ValueError):
        _builder(tmp_path, build_mirror=mirror)._build_setup_script()


def test_no_generator_logic_is_duplicated_from_the_engine(tmp_path):
    # The seds, patches and repository setup all live in the engine now; a
    # copy here would be the drift the migration removed.
    script = _builder(tmp_path)._build_setup_script()
    source = Path(iso_builder_module.__file__).read_text(encoding="utf-8")

    assert "talesam/build-iso" not in source
    for marker in ("pacman-key", "mknod", "sed -i", "buildiso -"):
        assert marker not in script, f"engine responsibility leaked into the setup script: {marker}"
