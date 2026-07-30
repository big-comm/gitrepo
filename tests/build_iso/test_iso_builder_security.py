import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import gitrepo.build_iso.core.iso_builder as iso_builder_module
import gitrepo.build_iso.local_builder as local_builder_module
from gitrepo.build_iso.core.container_manager import ContainerManager
from gitrepo.build_iso.core.iso_builder import BUILD_ISO_REPO, ISOBuilder


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder(
        {
            "container_engine": "docker",
            "output_dir": str(tmp_path),
        }
    )


def test_execute_never_configures_passwordless_sudo(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    monkeypatch.setattr(builder, "_check_engine", lambda: True)
    monkeypatch.setattr(builder, "_check_storage_driver", lambda: True)
    monkeypatch.setattr(builder, "_pull_image", lambda: True)
    monkeypatch.setattr(builder, "_run_container", lambda: True)
    monkeypatch.setattr(builder, "_publish_container_artifacts", lambda: str(tmp_path / "result.iso"))
    monkeypatch.setattr(builder, "_cleanup_containers", lambda: None)

    launched = []

    def record_run(argv, **kwargs):
        launched.append(argv)
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", record_run)
    monkeypatch.setattr(
        iso_builder_module.subprocess,
        "Popen",
        lambda argv, **kwargs: launched.append(argv) or Mock(poll=lambda: 0, returncode=0),
    )

    result = builder.execute()

    assert result["success"] is True
    assert all("pkexec" not in argv for argv in launched)
    assert all("/etc/sudoers.d" not in " ".join(argv) for argv in launched)


def test_btrfs_driver_is_reported_without_mutating_host(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    commands = []

    def docker_info(argv, **kwargs):
        commands.append(argv)
        return Mock(returncode=0, stdout="btrfs\n")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", docker_info)

    assert builder._check_storage_driver() is True
    assert commands == [["docker", "info", "--format", "{{.Driver}}"]]


def test_iso_builder_has_no_global_docker_storage_deletion():
    source = Path(iso_builder_module.__file__).read_text(encoding="utf-8")

    assert "/var/lib/docker" not in source
    assert "NOPASSWD" not in source


def test_cancel_uses_the_unprivileged_container_engine(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"
    commands = []

    def record_run(argv, **kwargs):
        commands.append(argv)
        return Mock(returncode=0)

    monkeypatch.setattr(iso_builder_module.subprocess, "run", record_run)
    monkeypatch.setattr(iso_builder_module.threading, "Thread", _ImmediateThread)

    builder.cancel()

    assert commands == [
        ["docker", "stop", "-t", "2", "build-iso-test"],
        ["docker", "rm", "-f", "-v", "build-iso-test"],
    ]


def test_container_owns_workspace_and_runs_as_root(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    launched = []
    process = Mock(stdout=BytesIO(), returncode=0)
    process.wait = Mock()
    monkeypatch.setattr(
        iso_builder_module.subprocess,
        "Popen",
        lambda argv, **kwargs: launched.append(argv) or process,
    )

    assert builder._run_container() is True

    argv = launched[0]
    assert "--rm" not in argv
    assert "--privileged" not in argv
    assert argv[argv.index("--label") + 1] == "org.biglinux.gitrepo.role=iso-builder"
    assert argv[argv.index("--cap-add") + 1] == "SYS_ADMIN"
    assert argv[argv.index("--user") + 1] == "0:0"
    assert not any(f"{tmp_path}/work:/work" in argument for argument in argv)
    assert not any(f"{tmp_path}/cache" in argument for argument in argv)
    assert "type=volume,destination=/var/lib/manjaro-tools/buildiso" in argv
    assert "type=volume,destination=/var/cache/manjaro-tools/iso" in argv
    setup_script = argv[-1]
    assert f"BUILD_ISO_REPO={BUILD_ISO_REPO}" in argv
    assert 'git clone --depth 1 "$BUILD_ISO_REPO"' in setup_script
    assert "/root/gitrepo-build/build-iso" in setup_script
    assert "/root/gitrepo-build/output" in setup_script


def test_container_artifacts_are_published_from_private_staging(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"

    def copy_from_container(argv, **kwargs):
        if argv[0] == "md5sum":
            return Mock(returncode=0, stdout=f"{'0' * 32}  {argv[1]}\n")
        staging = Path(argv[-1])
        (staging / "biglinux.iso").write_bytes(b"iso")
        (staging / "biglinux.iso.pkgs").write_text("packages\n", encoding="utf-8")
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", copy_from_container)

    published = builder._publish_container_artifacts()

    assert published == str(tmp_path / "biglinux.iso")
    assert (tmp_path / "biglinux.iso").read_bytes() == b"iso"
    assert (tmp_path / "biglinux.iso.pkgs").read_text(encoding="utf-8") == "packages\n"
    assert (tmp_path / "biglinux.iso.md5").read_text(encoding="utf-8").endswith("  biglinux.iso\n")
    assert not list(tmp_path.glob(".gitrepo-iso-*"))


def test_container_artifact_publication_rejects_symlink(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"

    def copy_hostile_output(argv, **kwargs):
        staging = Path(argv[-1])
        (staging / "outside.iso").symlink_to(tmp_path / "outside")
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", copy_hostile_output)

    assert builder._publish_container_artifacts() == ""
    assert not (tmp_path / "outside.iso").exists()


def test_container_artifact_publication_suffixes_duplicate_family(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"
    existing = tmp_path / "biglinux.iso"
    existing.write_bytes(b"existing")
    (tmp_path / "biglinux-1.iso").write_bytes(b"existing-1")

    def copy_duplicate_output(argv, **kwargs):
        staging = Path(argv[-1])
        (staging / "biglinux.iso").write_bytes(b"replacement")
        (staging / "biglinux.iso.pkgs").write_text("packages\n", encoding="utf-8")
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", copy_duplicate_output)

    assert builder._publish_container_artifacts() == str(tmp_path / "biglinux-2.iso")
    assert existing.read_bytes() == b"existing"
    assert (tmp_path / "biglinux-1.iso").read_bytes() == b"existing-1"
    assert (tmp_path / "biglinux-2.iso").read_bytes() == b"replacement"
    assert (tmp_path / "biglinux-2.iso.pkgs").read_text(encoding="utf-8") == "packages\n"
    # The checksum is computed from the published bytes, not from an external
    # binary that may be missing after a build that already took an hour.
    expected = hashlib.md5(b"replacement").hexdigest()
    assert (tmp_path / "biglinux-2.iso.md5").read_text(encoding="utf-8") == f"{expected}  biglinux-2.iso\n"


def test_available_artifact_name_reserves_the_whole_artifact_family(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    iso_file = staging / "biglinux.iso"
    package_file = staging / "biglinux.iso.pkgs"
    (tmp_path / "biglinux.iso.pkgs").write_text("existing packages\n", encoding="utf-8")
    (tmp_path / "biglinux-1.iso.md5").write_text("existing checksum\n", encoding="utf-8")

    assert ISOBuilder._available_artifact_name(tmp_path, iso_file, [iso_file, package_file]) == "biglinux-2.iso"


def test_success_cleanup_removes_only_the_current_container(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "gitrepo-build-iso-test"
    commands = []

    def record_run(argv, **kwargs):
        commands.append(argv)
        return Mock(returncode=0)

    monkeypatch.setattr(iso_builder_module.subprocess, "run", record_run)

    builder._cleanup_containers()

    assert commands == [["docker", "rm", "-f", "-v", "gitrepo-build-iso-test"]]


class _ImmediateThread:
    def __init__(self, target, daemon):
        self._target = target

    def start(self):
        self._target()


def test_cli_builder_has_no_host_privilege_escalation_or_storage_deletion():
    source = Path(local_builder_module.__file__).read_text(encoding="utf-8")

    assert "/var/lib/docker" not in source
    assert '["sudo", "-v"]' not in source
    assert '"chmod", "-R", "777"' not in source


def test_container_cleanup_lists_only_valid_ids(monkeypatch):
    manager = ContainerManager("docker")
    manager.engine = "docker"
    result = Mock(returncode=0, stdout="0123456789ab\n../../host\nabcdefabcdefabcdefabcdef\n")
    commands = []
    monkeypatch.setattr(
        "gitrepo.build_iso.core.container_manager.subprocess.run",
        lambda argv, **kwargs: commands.append(argv) or result,
    )

    assert manager.list_stopped_containers("example/image:latest") == [
        "0123456789ab",
        "abcdefabcdefabcdefabcdef",
    ]
    assert commands[0][-2:] == ["--filter", "label=org.biglinux.gitrepo.role=iso-builder"]


def test_container_cleanup_rejects_unvalidated_id(monkeypatch):
    manager = ContainerManager("docker")
    manager.engine = "docker"
    run = Mock()
    monkeypatch.setattr("gitrepo.build_iso.core.container_manager.subprocess.run", run)

    assert manager.remove_stopped_containers(["--force", "../../host"]) is False
    run.assert_not_called()


def test_explicit_container_engine_never_falls_back(monkeypatch):
    manager = ContainerManager("docker")
    monkeypatch.setattr(manager, "_engine_available", lambda engine: engine == "podman")

    assert manager.detect_engine() is None


def test_container_status_uses_one_image_probe(monkeypatch):
    manager = ContainerManager("docker")
    commands = []

    def run(argv, **_kwargs):
        commands.append(argv)
        if argv == ["docker", "--version"]:
            return Mock(returncode=0, stdout="Docker version 27.0\n", stderr="")
        if argv[:2] == ["docker", "info"]:
            return Mock(returncode=0, stdout="overlay2\n")
        return Mock(returncode=0, stdout="2147483648 2026-07-16T10:00:00Z\n", stderr="")

    monkeypatch.setattr(manager, "_engine_available", lambda engine: engine == "docker")
    monkeypatch.setattr("gitrepo.build_iso.core.container_manager.subprocess.run", run)

    status = manager.capture_status("example/image:latest")

    assert status.is_engine_ready is True
    assert status.is_image_available is True
    assert status.image_size_gb == 2.0
    assert len([command for command in commands if command[1:3] == ["image", "inspect"]]) == 1


def test_container_status_stops_when_engine_is_unavailable(monkeypatch):
    manager = ContainerManager("docker")
    run = Mock()
    monkeypatch.setattr(manager, "_engine_available", lambda _engine: False)
    monkeypatch.setattr("gitrepo.build_iso.core.container_manager.subprocess.run", run)

    status = manager.capture_status("example/image:latest")

    assert status.engine is None
    assert status.is_engine_ready is False
    assert status.is_image_available is False
    run.assert_not_called()


def test_cancelled_build_has_distinct_status(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder.cancel()

    result = builder.execute()

    assert result["success"] is False
    assert result["status"] == "cancelled"
    assert result["error"]


def test_container_cleanup_removes_exact_confirmed_ids(monkeypatch):
    manager = ContainerManager("docker")
    manager.engine = "docker"
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("gitrepo.build_iso.core.container_manager.subprocess.run", run)

    assert manager.remove_stopped_containers(["0123456789ab"]) is True
    # -v as well: each build owns two anonymous volumes holding the work tree,
    # and removing the container without them strands tens of gigabytes.
    assert run.call_args.args[0] == ["docker", "rm", "-v", "0123456789ab"]


def test_publication_never_overwrites_a_file_created_after_the_name_check(monkeypatch, tmp_path):
    """A competing writer between naming and publication keeps its bytes."""
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"

    def copy_output(argv, **kwargs):
        staging = Path(argv[-1])
        (staging / "biglinux.iso").write_bytes(b"ours")
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", copy_output)

    original_name = ISOBuilder._available_artifact_name

    def race(output, iso_file, entries):
        chosen = original_name(output, iso_file, entries)
        # Another build publishes under the same name right after we picked it.
        (output / chosen).write_bytes(b"someone else")
        return chosen

    monkeypatch.setattr(ISOBuilder, "_available_artifact_name", staticmethod(race))

    assert builder._publish_container_artifacts() == ""
    assert (tmp_path / "biglinux.iso").read_bytes() == b"someone else"


def test_a_failed_publication_removes_only_what_it_created(monkeypatch, tmp_path):
    builder = _builder(tmp_path)
    builder._container_name = "build-iso-test"
    bystander = tmp_path / "biglinux.iso.pkgs"
    bystander.write_text("not mine\n", encoding="utf-8")

    def copy_output(argv, **kwargs):
        staging = Path(argv[-1])
        (staging / "biglinux.iso").write_bytes(b"ours")
        (staging / "biglinux.iso.pkgs").write_text("packages\n", encoding="utf-8")
        return Mock(returncode=0, stdout="")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", copy_output)

    published = builder._publish_container_artifacts()

    # The family avoided the taken name instead of clobbering the bystander.
    assert published == str(tmp_path / "biglinux-1.iso")
    assert bystander.read_text(encoding="utf-8") == "not mine\n"
