import subprocess
from pathlib import Path

from gitrepo.build_iso.core.iso_builder import ISOBuilder

# Reproduces the manjaro-tools-iso-git call that aborts make_image_live() when the
# livefs still ships the stable manjaro-live-base without /usr/bin/manjaro-live-setup.
UNPATCHED_CONFIGURE_LIVE_IMAGE = """configure_live_image(){
    write_live_session_conf "$1"
    msg2 "Call manjaro-live-setup ..."
    chroot $1 /usr/bin/manjaro-live-setup
    chroot $1 cat /var/log/manjaro-live-setup.log
    msg "Done configuring [livefs]"
}
"""


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def _patch_script(builder: ISOBuilder, target: Path) -> str:
    script = builder._live_setup_guard_commands()
    body = script.split("<<'GITREPO_LIVE_SETUP_GUARD'\n", 1)[1].split("\nGITREPO_LIVE_SETUP_GUARD\n", 1)[0]
    return body.replace("/usr/lib/manjaro-tools/util-iso-image.sh", str(target))


def test_setup_script_installs_the_guard_before_build_iso_runs(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    guard_index = script.index("patch-live-setup.sh")
    assert guard_index < script.index("bash ./build-iso.sh")
    assert "/^  patch_manjaro_tools$/a" in script
    assert "grep -q '^  sudo bash /root/gitrepo-build/patch-live-setup.sh$'" in script


def test_guard_skips_the_chroot_call_when_the_livefs_lacks_the_binary(tmp_path):
    target = tmp_path / "util-iso-image.sh"
    target.write_text(UNPATCHED_CONFIGURE_LIVE_IMAGE, encoding="utf-8")
    patch = tmp_path / "patch-live-setup.sh"
    patch.write_text(_patch_script(_builder(tmp_path), target), encoding="utf-8")

    assert subprocess.run(["bash", str(patch)], check=False).returncode == 0

    patched = target.read_text(encoding="utf-8")
    assert 'if [[ -x "$1/usr/bin/manjaro-live-setup" ]]; then chroot $1 /usr/bin/manjaro-live-setup;' in patched
    assert 'if [[ -f "$1/var/log/manjaro-live-setup.log" ]]; then' in patched
    assert subprocess.run(["bash", "-n", str(target)], check=False).returncode == 0

    livefs = tmp_path / "livefs"
    (livefs / "usr" / "bin").mkdir(parents=True)
    harness = tmp_path / "harness.sh"
    harness.write_text(
        'set -eo pipefail\nmsg(){ :; }\nmsg2(){ echo "$*"; }\nchroot(){ echo "CHROOT $*"; }\n'
        f"write_live_session_conf(){{ :; }}\nsource {target}\nconfigure_live_image {livefs}\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert "Skipping manjaro-live-setup" in result.stdout
    assert "CHROOT" not in result.stdout
