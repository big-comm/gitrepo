from __future__ import annotations

from pathlib import Path

from gitrepo.common.rich_logger import RichLogger


def test_logger_redacts_secrets_from_terminal_and_file(tmp_path: Path, capsys) -> None:
    logger = RichLogger("gitrepo", "test", str(tmp_path), use_colors=False)
    logger.setup_log_file(lambda: "repository")

    logger.log("white", "Authorization: Bearer ghp_0123456789abcdef token=plain-secret")

    terminal = capsys.readouterr().out
    persisted = (tmp_path / "repository" / "gitrepo.log").read_text(encoding="utf-8")
    for output in (terminal, persisted):
        assert "0123456789abcdef" not in output
        assert "plain-secret" not in output
        assert "REDACTED" in output
