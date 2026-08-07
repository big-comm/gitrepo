"""A finished ISO records what it was actually built from."""

from pathlib import Path
from unittest.mock import Mock

import gitrepo.build_iso.core.iso_builder as iso_builder_module
from gitrepo.build_iso.core.iso_builder import ISOBuilder


def _builder(tmp_path: Path) -> ISOBuilder:
    return ISOBuilder({"container_engine": "docker", "output_dir": str(tmp_path)})


def test_the_container_reports_the_commits_it_resolved(tmp_path):
    builder = _builder(tmp_path)

    builder._handle_container_record("GITREPO-MANIFEST build-iso " + "a" * 40, False)
    builder._handle_container_record("GITREPO-MANIFEST iso-profiles " + "b" * 40, False)

    assert builder.manifest == {"build-iso": "a" * 40, "iso-profiles": "b" * 40}


def test_a_manifest_line_is_not_mistaken_for_build_output(tmp_path):
    logged = []
    builder = ISOBuilder(
        {"container_engine": "docker", "output_dir": str(tmp_path)},
        {"on_log": lambda color, message: logged.append(message)},
    )

    builder._handle_container_record("GITREPO-MANIFEST build-iso " + "c" * 40, False)

    # It is recorded and summarized, never echoed as an ordinary build line.
    assert builder.manifest["build-iso"] == "c" * 40
    assert all(not message.startswith("GITREPO-MANIFEST") for message in logged)


def test_a_forged_manifest_line_is_ignored(tmp_path):
    builder = _builder(tmp_path)

    for forged in (
        "GITREPO-MANIFEST build-iso not-a-sha",
        "prefix GITREPO-MANIFEST build-iso " + "d" * 40,
        "GITREPO-MANIFEST build iso " + "d" * 40,
    ):
        builder._handle_container_record(forged, False)

    assert builder.manifest == {}


def test_the_build_script_records_every_cloned_commit(tmp_path):
    script = _builder(tmp_path)._build_setup_script()
    assert "GITREPO-MANIFEST iso-profiles $(git -C /root/gitrepo-build/iso-profiles rev-parse HEAD)" in script

    community = _builder(tmp_path)
    community.distroname = "bigcommunity"
    community.iso_profiles_repo = "https://github.com/big-comm/iso-profiles"
    script = community._build_setup_script()
    assert "GITREPO-MANIFEST iso-profiles" in script
    assert "GITREPO-MANIFEST profiles $(git -C /root/gitrepo-build/profiles rev-parse HEAD)" in script


def test_the_image_digest_pins_the_exact_image_that_ran(tmp_path, monkeypatch):
    builder = _builder(tmp_path)
    digest = "talesam/community-build@sha256:" + "e" * 64

    def inspect(argv, **kwargs):
        assert argv[:3] == ["docker", "image", "inspect"]
        return Mock(returncode=0, stdout=f"{digest}\n")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", inspect)

    assert builder.resolve_image_digest() == digest


def test_an_image_without_a_repository_digest_falls_back_to_its_id(tmp_path, monkeypatch):
    builder = _builder(tmp_path)
    image_id = "sha256:" + "f" * 64
    calls = []

    def inspect(argv, **kwargs):
        calls.append(argv[-2])
        if argv[-2] == "{{index .RepoDigests 0}}":
            return Mock(returncode=1, stdout="")
        return Mock(returncode=0, stdout=f"{image_id}\n")

    monkeypatch.setattr(iso_builder_module.subprocess, "run", inspect)

    # A locally built image has no repository digest, but still has an identity.
    assert builder.resolve_image_digest() == image_id
    assert calls == ["{{index .RepoDigests 0}}", "{{.Id}}"]


def test_the_result_carries_the_manifest_even_when_the_build_fails(tmp_path, monkeypatch):
    builder = _builder(tmp_path)
    monkeypatch.setattr(builder, "_prepare_build", lambda: "")
    monkeypatch.setattr(builder, "_build_and_publish_iso", lambda: ("", "container build failed"))
    builder.manifest["build-iso"] = "a" * 40

    result = builder.execute()

    assert result["status"] == "failed"
    assert result["manifest"] == {"build-iso": "a" * 40}
