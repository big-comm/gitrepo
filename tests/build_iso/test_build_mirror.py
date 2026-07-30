import subprocess

import pytest

from gitrepo.build_iso.core.config import BUILD_MIRROR
from gitrepo.build_iso.core.iso_builder import ISOBuilder


def _builder(tmp_path, **extra):
    config = {"container_engine": "docker", "output_dir": str(tmp_path)}
    config.update(extra)
    return ISOBuilder(config)


def test_the_mirror_is_pinned_before_build_iso_runs(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("build_mirror=") < script.index("bash ./build-iso.sh")
    assert "/root/.config/manjaro-tools/manjaro-tools.conf" in script


def test_the_default_is_not_the_stale_upstream_mirror(tmp_path):
    # manjaro-tools falls back to mirror.easyname.at, which served Plasma 6.6.5
    # while Manjaro stable was on 6.7.3. Anything but that.
    assert "easyname" not in BUILD_MIRROR
    assert BUILD_MIRROR.startswith("https://")
    assert BUILD_MIRROR in _builder(tmp_path)._build_setup_script()


def test_writing_the_config_produces_exactly_one_assignment(tmp_path):
    home = tmp_path / "root" / ".config" / "manjaro-tools"
    commands = _builder(tmp_path)._build_mirror_commands().replace("/root/.config/manjaro-tools", str(home))
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
