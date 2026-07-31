import subprocess

import pytest

from gitrepo.build_iso.core.config import BUILD_MIRROR, BUILD_MIRRORS
from gitrepo.build_iso.core.iso_builder import ISOBuilder


def _builder(tmp_path, **extra):
    config = {"container_engine": "docker", "output_dir": str(tmp_path)}
    config.update(extra)
    return ISOBuilder(config)


def _patch_script(tmp_path):
    commands = _builder(tmp_path)._build_mirror_commands()
    body = commands.split("<<'GITREPO_BUILD_MIRRORS'\n", 1)[1].split("\nGITREPO_BUILD_MIRRORS\n", 1)[0]
    script = tmp_path / "patch-build-mirrors.sh"
    script.write_text(body + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def _manjaro_tools_scripts(tmp_path):
    mkchroot = tmp_path / "mkchroot"
    mkchroot.write_text(
        """#!/bin/bash
if true; then
    pac_base="$working_dir/pacman-basestrap.conf"
    sed "s#Include = /etc/pacman.d/mirrorlist#Server = ${url}#g" $pac_conf > $pac_base
fi
""",
        encoding="utf-8",
    )
    chroot_run = tmp_path / "chroot-run"
    chroot_run.write_text(
        """#!/bin/bash
copy_hostconf () {
    if [[ -n ${build_mirror} ]]; then
        if false; then
            :
        else
            echo "Server = ${build_mirror}" > "$1/etc/pacman.d/mirrorlist"
        fi
    fi
}
""",
        encoding="utf-8",
    )
    return mkchroot, chroot_run


def _run_patch(tmp_path, branch):
    script = _patch_script(tmp_path)
    mkchroot, chroot_run = _manjaro_tools_scripts(tmp_path)
    mirrorlist = tmp_path / "gitrepo-build-mirrors"
    body = script.read_text(encoding="utf-8")
    body = body.replace("/usr/bin/mkchroot", str(mkchroot))
    body = body.replace("/usr/bin/chroot-run", str(chroot_run))
    body = body.replace("/etc/pacman.d/gitrepo-build-mirrors", str(mirrorlist))
    script.write_text(body, encoding="utf-8")
    result = subprocess.run(
        ["bash", str(script)],
        env={"PATH": "/usr/bin:/bin", "MANJARO_BRANCH": branch},
        capture_output=True,
        text=True,
        check=False,
    )
    return result, mirrorlist, mkchroot, chroot_run


def test_the_mirror_is_pinned_before_build_iso_runs(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("build_mirror=") < script.index("bash ./build-iso.sh")
    assert "/root/.config/manjaro-tools/manjaro-tools.conf" in script
    assert 'patch-build-mirrors.sh || die "patch-build-mirrors.sh failed"' in script


def test_the_default_is_not_the_stale_upstream_mirror(tmp_path):
    # manjaro-tools falls back to mirror.easyname.at, which served Plasma 6.6.5
    # while Manjaro stable was on 6.7.3. Anything but that.
    assert "easyname" not in BUILD_MIRROR
    assert BUILD_MIRROR.startswith(("http://", "https://"))
    assert BUILD_MIRROR in _builder(tmp_path)._build_setup_script()


def test_default_mirrors_have_the_requested_priority():
    assert BUILD_MIRRORS == (
        "http://mirrors.manjaro.org/repo",
        "http://mirrors2.manjaro.org",
        "http://mirrors.cicku.me/manjaro",
    )


@pytest.mark.parametrize("branch", ["stable", "testing", "unstable"])
def test_the_selected_branch_is_added_to_every_build_mirror(tmp_path, branch):
    result, mirrorlist, _mkchroot, _chroot_run = _run_patch(tmp_path, branch)

    assert result.returncode == 0, result.stderr
    assert mirrorlist.read_text(encoding="utf-8").splitlines() == [
        f"Server = http://mirrors.manjaro.org/repo/{branch}/$repo/$arch",
        f"Server = http://mirrors2.manjaro.org/{branch}/$repo/$arch",
        f"Server = http://mirrors.cicku.me/manjaro/{branch}/$repo/$arch",
    ]


def test_manjaro_tools_uses_the_ordered_file_in_both_download_paths(tmp_path):
    result, mirrorlist, mkchroot, chroot_run = _run_patch(tmp_path, "stable")

    assert result.returncode == 0, result.stderr
    mkchroot_text = mkchroot.read_text(encoding="utf-8")
    chroot_run_text = chroot_run.read_text(encoding="utf-8")
    assert f"Include = {mirrorlist}" in mkchroot_text
    assert "#Server = ${url}#" not in mkchroot_text
    assert f'cp {mirrorlist} "$1/etc/pacman.d/mirrorlist"' in chroot_run_text
    assert 'echo "Server = ${build_mirror}"' not in chroot_run_text


def test_an_unknown_branch_does_not_patch_manjaro_tools(tmp_path):
    result, mirrorlist, mkchroot, chroot_run = _run_patch(tmp_path, "experimental")

    assert result.returncode != 0
    assert "unknown Manjaro branch" in result.stderr
    assert not mirrorlist.exists()
    assert "Server = ${url}" in mkchroot.read_text(encoding="utf-8")
    assert 'echo "Server = ${build_mirror}"' in chroot_run.read_text(encoding="utf-8")


def test_writing_the_config_produces_exactly_one_assignment(tmp_path):
    home = tmp_path / "root" / ".config" / "manjaro-tools"
    commands = _builder(tmp_path)._build_mirror_commands().replace("/root/.config/manjaro-tools", str(home))
    commands = commands.split("cat > /root/gitrepo-build/patch-build-mirrors.sh", 1)[0]
    script = tmp_path / "pin.sh"
    script.write_text("set -eo pipefail\n" + commands, encoding="utf-8")

    assert subprocess.run(["bash", str(script)], check=False).returncode == 0
    assert (home / "manjaro-tools.conf").read_text(encoding="utf-8") == f"build_mirror={BUILD_MIRROR}\n"


def test_a_configured_mirror_overrides_the_default(tmp_path):
    builder = _builder(tmp_path, build_mirror="https://linorg.usp.br/manjaro")

    assert "https://linorg.usp.br/manjaro" in builder._build_mirror_commands()
    assert BUILD_MIRROR not in builder._build_mirror_commands()


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
    # manjaro-tools.conf is sourced by the build, so shell syntax must never
    # reach it.
    with pytest.raises(ValueError, match="unsafe build mirror"):
        _builder(tmp_path, build_mirror=mirror)._build_mirror_commands()


@pytest.mark.parametrize("mirror", ["", None])
def test_an_empty_mirror_falls_back_to_the_default(tmp_path, mirror):
    assert _builder(tmp_path, build_mirror=mirror).build_mirror == BUILD_MIRROR
