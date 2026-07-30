import subprocess
from pathlib import Path

import pytest

from gitrepo.build_iso.core.iso_builder import ISOBuilder

# The three CDN entries the profile ships, each with the branch hardcoded and in
# a different position, plus the mirrorlist Include that must survive.
MIRRORCDN = """## Static mirrors from CDNs

## CDN from CDN77
Server = https://mirrors2.manjaro.org/stable/$repo/$arch

## CDN from cloudflare
Server = https://mirrors.cicku.me/manjaro/stable/$repo/$arch

## CDN from CDN77 too
Server = http://mirrors.manjaro.org/repo/stable/$repo/$arch

Include=/etc/pacman.d/mirrorlist
"""


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def _script(tmp_path: Path) -> Path:
    commands = _builder(tmp_path)._manjaro_branch_commands()
    body = commands.split("<<'GITREPO_MANJARO_BRANCH'\n", 1)[1].split("\nGITREPO_MANJARO_BRANCH\n", 1)[0]
    path = tmp_path / "set-manjaro-branch.sh"
    path.write_text(body + "\n", encoding="utf-8")
    return path


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    for overlay in ("root", "live"):
        target = profile / f"{overlay}-overlay" / "etc" / "pacman.d"
        target.mkdir(parents=True)
        (target / "mirrorcdn").write_text(MIRRORCDN, encoding="utf-8")
    return profile


def _run(script: Path, profile: Path, branch: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        env={"PATH": "/usr/bin:/bin", "MANJARO_BRANCH": branch, "PROFILE_PATH_EDITION": str(profile)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_patch_runs_before_build_iso(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("set-manjaro-branch.sh") < script.index("bash ./build-iso.sh")
    assert "/^  clone_iso_profiles$/a" in script
    # build-iso.sh has no `set -e` and no ERR trap: a bare call would be ignored.
    assert 'set-manjaro-branch.sh || die "set-manjaro-branch.sh failed"' in script


@pytest.mark.parametrize("branch", ["stable", "testing", "unstable"])
def test_every_cdn_entry_follows_the_branch(tmp_path, branch):
    script, profile = _script(tmp_path), _profile(tmp_path)

    assert _run(script, profile, branch).returncode == 0

    for overlay in ("root", "live"):
        text = (profile / f"{overlay}-overlay/etc/pacman.d/mirrorcdn").read_text(encoding="utf-8")
        assert text.count(f"/{branch}/$repo/$arch") == 3
        # The generic mirrorlist Include has to stay, and no other branch may remain.
        assert "Include=/etc/pacman.d/mirrorlist" in text
        for other in {"stable", "testing", "unstable"} - {branch}:
            assert f"/{other}/$repo/$arch" not in text


def test_switching_branches_is_reversible(tmp_path):
    script, profile = _script(tmp_path), _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.d/mirrorcdn"

    for branch in ("unstable", "testing", "stable"):
        assert _run(script, profile, branch).returncode == 0

    assert conf.read_text(encoding="utf-8") == MIRRORCDN


def test_running_twice_does_not_duplicate(tmp_path):
    script, profile = _script(tmp_path), _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.d/mirrorcdn"

    _run(script, profile, "testing")
    first = conf.read_text(encoding="utf-8")
    _run(script, profile, "testing")

    assert conf.read_text(encoding="utf-8") == first


def test_an_unknown_branch_fails_the_build(tmp_path):
    result = _run(_script(tmp_path), _profile(tmp_path), "experimental")

    assert result.returncode != 0
    assert "unknown Manjaro branch" in result.stderr


def test_a_profile_without_mirrorcdn_fails_the_build(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(_script(tmp_path), empty, "testing")

    assert result.returncode != 0
    assert "no mirrorcdn found" in result.stderr
