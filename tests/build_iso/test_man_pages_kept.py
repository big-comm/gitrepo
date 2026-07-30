import subprocess
from pathlib import Path

from gitrepo.build_iso.core.iso_builder import ISOBuilder

# Reproduces the cleanup build-iso.sh appends to util-iso-image.sh. BigLinux
# ships man pages, so only that one removal must go.
UNPATCHED_CLEANUPS = """mkiso_build_iso_cleanups() {
  local cpath="$1"

  # ===========================================
  # Remove documentation
  # ===========================================
  rm -rf "$cpath/usr/share/doc"/* 2> /dev/null

  # Remove man pages
  rm -rf "$cpath/usr/share/man"/* 2> /dev/null

  local wallpapers_path="$cpath/usr/share/wallpapers"
}
"""


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def _patch(builder: ISOBuilder, target: Path) -> str:
    return "set -eo pipefail\n" + builder._keep_man_pages_commands().replace(
        "/root/gitrepo-build/build-iso/build-iso.sh", str(target)
    )


def test_setup_script_keeps_man_before_build_iso_runs(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("man pages are kept on purpose") < script.index("bash ./build-iso.sh")


def test_the_man_removal_is_dropped_and_the_rest_survives(tmp_path):
    target = tmp_path / "build-iso.sh"
    target.write_text(UNPATCHED_CLEANUPS, encoding="utf-8")
    patch = tmp_path / "patch.sh"
    patch.write_text(_patch(_builder(tmp_path), target), encoding="utf-8")

    assert subprocess.run(["bash", str(patch)], check=False).returncode == 0

    patched = target.read_text(encoding="utf-8")
    assert "usr/share/man" not in patched
    assert "man pages are kept on purpose" in patched
    # Everything else in the cleanup stays untouched.
    assert 'rm -rf "$cpath/usr/share/doc"/* 2> /dev/null' in patched
    assert 'local wallpapers_path="$cpath/usr/share/wallpapers"' in patched
    assert subprocess.run(["bash", "-n", str(target)], check=False).returncode == 0


def test_patch_fails_loudly_when_a_man_removal_survives(tmp_path):
    target = tmp_path / "build-iso.sh"
    # Different quoting than the sed expects, so the guard grep must reject it.
    target.write_text('  rm -rf "$cpath/usr/share/man"/* 2>/dev/null\n', encoding="utf-8")
    patch = tmp_path / "patch.sh"
    patch.write_text(_patch(_builder(tmp_path), target), encoding="utf-8")

    assert subprocess.run(["bash", str(patch)], check=False).returncode != 0
