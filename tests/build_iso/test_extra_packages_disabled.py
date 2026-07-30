import subprocess
from pathlib import Path

from gitrepo.build_iso.core.iso_builder import ISOBuilder

# Reproduces the buildiso invocations build-iso.sh ships. -f makes manjaro-tools
# set extra=true, which installs every `>extra` line of the profile.
UNPATCHED_BUILD_ISO = """build_iso() {
  msg_info "BUILD COMMAND: buildiso -f -p $EDITION -b $MANJARO_BRANCH -k ${KERNEL_NAME}"
  if [[ "${LOCAL_BUILD:-false}" == "true" ]]; then
    LC_ALL=C buildiso -d zstd -f -p "$EDITION" -b "$MANJARO_BRANCH" -k "linux${KERNEL_NAME}"
    BUILD_EXIT_CODE=$?
  else
    LC_ALL=C sudo -u "$USERNAME" bash -c "buildiso -d zstd -f -p $EDITION -b $MANJARO_BRANCH -k linux${KERNEL_NAME};exit \\$?"
    BUILD_EXIT_CODE=$?
  fi
}
"""


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def test_setup_script_drops_the_flag_before_build_iso_runs(tmp_path):
    script = _builder(tmp_path)._build_setup_script()

    assert script.index("buildiso -d zstd -f ") < script.index("bash ./build-iso.sh")
    assert "! grep -q 'buildiso \\(-d zstd \\)\\?-f '" in script


def test_every_buildiso_invocation_loses_the_flag(tmp_path):
    target = tmp_path / "build-iso.sh"
    target.write_text(UNPATCHED_BUILD_ISO, encoding="utf-8")
    patch = tmp_path / "patch.sh"
    patch.write_text(
        "set -eo pipefail\n"
        + _builder(tmp_path)
        ._disable_extra_packages_commands()
        .replace("/root/gitrepo-build/build-iso/build-iso.sh", str(target)),
        encoding="utf-8",
    )

    assert subprocess.run(["bash", str(patch)], check=False).returncode == 0

    patched = target.read_text(encoding="utf-8")
    assert "-f " not in patched
    assert patched.count("buildiso -d zstd -p ") == 2
    assert 'msg_info "BUILD COMMAND: buildiso -p $EDITION' in patched
    assert subprocess.run(["bash", "-n", str(target)], check=False).returncode == 0


def test_patch_fails_loudly_when_a_flag_survives(tmp_path):
    target = tmp_path / "build-iso.sh"
    # A form the seds do not match, so the guard grep must reject it.
    target.write_text('buildiso -f -b "$MANJARO_BRANCH"\n', encoding="utf-8")
    patch = tmp_path / "patch.sh"
    patch.write_text(
        "set -eo pipefail\n"
        + _builder(tmp_path)
        ._disable_extra_packages_commands()
        .replace("/root/gitrepo-build/build-iso/build-iso.sh", str(target)),
        encoding="utf-8",
    )

    assert subprocess.run(["bash", str(patch)], check=False).returncode != 0
