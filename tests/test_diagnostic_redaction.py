from gitrepo.common.diagnostic_redaction import redact_diagnostic


def test_redacts_authorization_and_github_tokens():
    message = "Authorization: token ghp_0123456789abcdef token=plain-secret"

    redacted = redact_diagnostic(message)

    assert "0123456789abcdef" not in redacted
    assert "plain-secret" not in redacted
    assert redacted.count("[REDACTED]") == 2


def test_preserves_non_secret_diagnostics():
    assert redact_diagnostic("Cloning https://github.com/biglinux/iso-profiles") == (
        "Cloning https://github.com/biglinux/iso-profiles"
    )
