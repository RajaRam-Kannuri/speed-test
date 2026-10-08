import json

import pytest

from app.agents.validation import compile_check, steps_from_dicts, validate_steps
from app.security.crypto import decrypt, encrypt
from app.security.passwords import hash_password, verify_password
from app.security.redaction import REDACTED, redact, redact_obj
from app.security.ssrf import TargetNotAllowed, check_url
from app.services.codegen import generate_spec


def test_password_hashing():
    h = hash_password("correct horse 1")
    assert verify_password("correct horse 1", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("correct horse 1")  # salted


def test_secret_encryption_roundtrip():
    token = encrypt("s3cr3t-value")
    assert "s3cr3t" not in token
    assert decrypt(token) == "s3cr3t-value"


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://192.168.1.1/admin",
    "http://localhost:8080/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[::1]/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "ftp://example.com/",
    "http://user:pass@example.com/",
    "http://100.64.0.1/",
])
def test_ssrf_blocks_restricted_targets(url):
    with pytest.raises(TargetNotAllowed):
        check_url(url)


def test_ssrf_allows_public_and_allowlisted_hosts():
    assert check_url("http://93.184.216.34/", resolve=False) == "93.184.216.34"
    assert check_url("http://127.0.0.1:8101/") == "127.0.0.1"  # allow-listed for tests via LLX_ALLOWED_PRIVATE_HOSTS


def test_redaction_removes_secrets_and_tokens():
    text = "login with Passw0rd! failed; Authorization: Bearer abcdef123456; api_key=XYZ987654"
    out = redact(text, ["Passw0rd!"])
    assert "Passw0rd!" not in out and "abcdef123456" not in out and "XYZ987654" not in out
    assert out.count(REDACTED) >= 3
    assert redact_obj({"a": ["Passw0rd!"]}, ["Passw0rd!"]) == {"a": [REDACTED]}


def test_codegen_treats_values_as_data_not_code():
    payload = '"); require("child_process").execSync("touch /tmp/pwned"); ("'
    steps = steps_from_dicts([
        {"action": "navigate", "value": "https://example.com/"},
        {"action": "fill", "target": {"strategy": "label", "value": payload}, "value": payload},
        {"action": "assert_text", "value": "`${process.env.HOME}`"},
    ])
    code = generate_spec("abc", 'title "quoted" `back`', steps, "../runtime")
    # Every user string appears only inside a JSON string literal.
    assert json.dumps(payload) in code
    assert "require(\"child_process\")" not in code.replace(json.dumps(payload), "")
    ok, output = compile_check("injection", steps)
    assert ok, output


def test_validation_rejects_unreliable_tests():
    report = validate_steps(steps_from_dicts([
        {"action": "navigate", "value": "/"},
        {"action": "click", "target": {"strategy": "css", "value": ""}},
        {"action": "fill", "target": {"strategy": "label", "value": "Email"}, "value": "{{username}}"},
        {"action": "teleport"},
    ]), kind="ui", available_vars=[], base_url="https://example.com")
    codes = {m["code"] for m in report.messages}
    assert {"target_value", "var_missing", "unknown_action", "no_assertion"} <= codes
    assert report.status == "invalid"


def test_validation_blocks_internal_urls_and_ui_steps_in_api_tests():
    report = validate_steps(steps_from_dicts([
        {"action": "api_request", "options": {"method": "GET", "url": "http://169.254.169.254/", "expect": {"status": [200]}}},
        {"action": "click", "target": {"strategy": "text", "value": "x"}},
    ]), kind="api")
    codes = {m["code"] for m in report.messages}
    assert "url_blocked" in codes and "ui_in_api_test" in codes


def test_validation_accepts_a_good_test():
    report = validate_steps(steps_from_dicts([
        {"action": "navigate", "value": "/login"},
        {"action": "fill", "target": {"strategy": "label", "value": "Email"}, "value": "{{username}}"},
        {"action": "set_variable", "value": "n-{{timestamp}}", "options": {"name": "n"}},
        {"action": "assert_text", "value": "{{n}}"},
    ]), kind="ui", available_vars=["username"], base_url="https://example.com")
    assert report.ok, report.messages
