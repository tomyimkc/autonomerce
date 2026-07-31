from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from security.controls import (  # noqa: E402
    SecurityError,
    is_public_https_url,
    redact,
    require_public_https_url,
    validate_idempotency_key,
)


def test_public_https_url_rejects_ssrf_targets_and_credentials():
    for value in (
        "http://example.com",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/x",
        "https://user:pass@example.com/x",
        "https://example.com:8443/x",
    ):
        assert not is_public_https_url(value), value
    assert is_public_https_url("https://seller.example/.well-known/agent-card.json")


def test_require_public_https_fails_closed():
    try:
        require_public_https_url("file:///etc/passwd")
    except SecurityError:
        pass
    else:
        raise AssertionError("unsafe URL must fail")


def test_redaction_covers_nested_keys_and_inline_tokens():
    value = {
        "api_key": "abc",
        "detail": ["Bearer abc.def", "otp=123456", {"sessionToken": "x"}],
    }
    clean = redact(value)
    assert clean["api_key"] == "[REDACTED]"
    assert clean["detail"][0] == "Bearer [REDACTED]"
    assert clean["detail"][1] == "otp=[REDACTED]"
    assert clean["detail"][2]["sessionToken"] == "[REDACTED]"


def test_idempotency_key_requires_bounded_safe_shape():
    assert validate_idempotency_key("payment:proposal_123456") == "payment:proposal_123456"
    for value in ("short", "../escape", "x" * 129):
        try:
            validate_idempotency_key(value)
        except SecurityError:
            continue
        raise AssertionError(f"unsafe idempotency key accepted: {value}")
