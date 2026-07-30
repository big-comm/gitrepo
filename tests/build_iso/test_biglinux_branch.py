import subprocess
from pathlib import Path

import pytest

from gitrepo.build_iso.core.iso_builder import ISOBuilder

# The tail of the profile's pacman.conf: BigLinux repositories sit around the
# Manjaro ones, and only stable is ever shipped.
PACMAN_CONF = """[biglinux-update-stable]
SigLevel = PackageRequired
Server = https://repo.biglinux.com.br/update-stable/$arch

[core]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[extra]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[multilib]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[biglinux-stable]
SigLevel = PackageRequired
Server = https://repo.biglinux.com.br/stable/$arch
"""


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def _script(tmp_path: Path) -> Path:
    commands = _builder(tmp_path)._biglinux_branch_commands()
    body = commands.split("<<'GITREPO_BIGLINUX_BRANCH'\n", 1)[1].split("\nGITREPO_BIGLINUX_BRANCH\n", 1)[0]
    path = tmp_path / "set-biglinux-branch.sh"
    path.write_text(body + "\n", encoding="utf-8")
    return path


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    for overlay in ("root", "live"):
        target = profile / f"{overlay}-overlay" / "etc"
        target.mkdir(parents=True)
        (target / "pacman.conf").write_text(PACMAN_CONF, encoding="utf-8")
    return profile


def _run(script: Path, profile: Path, branch: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        env={"PATH": "/usr/bin:/bin", "BIGLINUX_BRANCH": branch, "PROFILE_PATH_EDITION": str(profile)},
        capture_output=True,
        text=True,
        check=False,
    )


def _sections(conf: Path) -> list[str]:
    return [line for line in conf.read_text(encoding="utf-8").splitlines() if line.startswith("[")]


def test_the_patch_runs_before_build_iso(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("set-biglinux-branch.sh") < script.index("bash ./build-iso.sh")
    assert "/^  clone_iso_profiles$/a" in script
    # build-iso.sh has no `set -e` and no ERR trap: a bare call would be ignored.
    assert 'set-biglinux-branch.sh || die "set-biglinux-branch.sh failed"' in script


def test_stable_changes_nothing(tmp_path):
    script, profile = _script(tmp_path), _profile(tmp_path)

    assert _run(script, profile, "stable").returncode == 0

    for overlay in ("root", "live"):
        assert (profile / f"{overlay}-overlay/etc/pacman.conf").read_text(encoding="utf-8") == PACMAN_CONF


def test_testing_is_inserted_above_stable_and_stable_stays(tmp_path):
    script, profile = _script(tmp_path), _profile(tmp_path)

    assert _run(script, profile, "testing").returncode == 0

    for overlay in ("root", "live"):
        conf = profile / f"{overlay}-overlay/etc/pacman.conf"
        sections = _sections(conf)
        # Additive: stable survives, testing precedes it so testing wins.
        assert "[biglinux-stable]" in sections
        assert sections.index("[biglinux-testing]") < sections.index("[biglinux-stable]")
        # And below the Manjaro repositories, as the build-time order has it.
        assert sections.index("[multilib]") < sections.index("[biglinux-testing]")
        assert "Server = https://repo.biglinux.com.br/testing/$arch" in conf.read_text(encoding="utf-8")


def test_running_twice_inserts_one_section(tmp_path):
    script, profile = _script(tmp_path), _profile(tmp_path)

    _run(script, profile, "testing")
    once = (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8")
    assert _run(script, profile, "testing").returncode == 0

    assert (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8") == once
    assert once.count("[biglinux-testing]") == 1


def test_an_unsupported_branch_fails_the_build(tmp_path):
    # build-iso.sh only knows stable and testing; anything else would build with
    # no BigLinux repository at all.
    result = _run(_script(tmp_path), _profile(tmp_path), "unstable")

    assert result.returncode != 0
    assert "unsupported BigLinux branch" in result.stderr


def test_a_conf_without_the_stable_section_fails_the_build(tmp_path):
    profile = _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.conf"
    conf.write_text(PACMAN_CONF.split("[biglinux-stable]")[0], encoding="utf-8")

    result = _run(_script(tmp_path), profile, "testing")

    assert result.returncode != 0
    assert "no [biglinux-stable] section" in result.stderr


def test_a_profile_without_pacman_conf_fails_the_build(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(_script(tmp_path), empty, "testing")

    assert result.returncode != 0
    assert "no pacman.conf found" in result.stderr


@pytest.mark.parametrize("branch", ["stable", "testing"])
def test_the_manjaro_and_biglinux_patches_are_independent(tmp_path, branch):
    # Both edit the same overlays; neither may undo the other.
    profile = _profile(tmp_path)
    for overlay in ("root", "live"):
        pacman_d = profile / f"{overlay}-overlay" / "etc" / "pacman.d"
        pacman_d.mkdir()
        (pacman_d / "mirrorcdn").write_text(
            "Server = https://mirrors2.manjaro.org/stable/$repo/$arch\nInclude=/etc/pacman.d/mirrorlist\n",
            encoding="utf-8",
        )

    manjaro = _builder(tmp_path)._manjaro_branch_commands()
    manjaro_body = manjaro.split("<<'GITREPO_MANJARO_BRANCH'\n", 1)[1].split("\nGITREPO_MANJARO_BRANCH\n", 1)[0]
    manjaro_script = tmp_path / "manjaro.sh"
    manjaro_script.write_text(manjaro_body + "\n", encoding="utf-8")

    assert _run(_script(tmp_path), profile, branch).returncode == 0
    assert (
        subprocess.run(
            ["bash", str(manjaro_script)],
            env={"PATH": "/usr/bin:/bin", "MANJARO_BRANCH": "testing", "PROFILE_PATH_EDITION": str(profile)},
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )

    conf = (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8")
    mirrorcdn = (profile / "root-overlay/etc/pacman.d/mirrorcdn").read_text(encoding="utf-8")
    assert "/testing/$repo/$arch" in mirrorcdn
    assert ("[biglinux-testing]" in conf) is (branch == "testing")
    assert "[biglinux-stable]" in conf
