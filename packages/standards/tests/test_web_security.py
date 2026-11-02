from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from pydantic import ValidationError
import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.security import web


if TYPE_CHECKING:
    from pathlib import Path


_NONCE = "'nonce-dGVzdC1ub25jZS1mb3ItZml4dHVyZXM='"
_CSP = f"default-src 'none'; script-src {_NONCE} 'strict-dynamic'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"


def _target() -> web.Target:
    return web.Target(name="homepage", url="https://example.com/", kind="html")


def _response() -> web.Response:
    return web.Response(
        status=200,
        headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("Strict-Transport-Security", "max-age=31536000"),
            ("Content-Security-Policy", _CSP),
            ("Permissions-Policy", "camera=(), geolocation=(), microphone=()"),
        ],
    )


def _replace(response: web.Response, name: str, value: str) -> web.Response:
    return web.Response(
        status=response.status,
        headers=[(key, current) for key, current in response.headers if key.lower() != name.lower()] + [(name, value)],
    )


def test_complete_html_policy_accepts_a_valid_response() -> None:
    assert web.evaluate(_target(), _response()) == []


def test_short_hsts_rollout_requires_an_explicit_policy_override() -> None:
    response = _replace(_response(), "Strict-Transport-Security", "max-age=300")
    assert [finding.check for finding in web.evaluate(_target(), response)] == ["hsts"]
    target = _target().model_copy(update={"hsts_min_age": 300})
    assert web.evaluate(target, response) == []


@pytest.mark.parametrize(
    ("header", "value", "check"),
    [
        ("X-Content-Type-Options", "", "content-type-options"),
        ("Referrer-Policy", "unsafe-url", "referrer-policy"),
        ("Strict-Transport-Security", "max-age=0", "hsts"),
        ("Content-Type", "application/json", "html-content-type"),
        ("Content-Security-Policy", "default-src *", "csp"),
        ("Content-Security-Policy", _CSP.replace("frame-ancestors 'none'", "frame-ancestors *"), "framing"),
        ("Permissions-Policy", "camera=(), geolocation=(), microphone=(*)", "browser-permissions"),
    ],
    ids=[
        "mime-sniffing",
        "referrer-leak",
        "disabled-hsts",
        "wrong-mime",
        "unrestricted-scripts",
        "arbitrary-framing",
        "arbitrary-microphone",
    ],
)
def test_html_policy_rejects_demonstrated_weaknesses(header: str, value: str, check: str) -> None:
    findings = web.evaluate(_target(), _replace(_response(), header, value))
    assert check in {finding.check for finding in findings}


@pytest.mark.parametrize(
    "scripts", ["'unsafe-inline'", "'unsafe-eval'", "https:", "data:", "*", "'nonce-'", "'nonce-short'"]
)
def test_script_policy_rejects_unsafe_or_invalid_sources(scripts: str) -> None:
    value = f"script-src {scripts}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    assert any(
        finding.check == "csp"
        for finding in web.evaluate(_target(), _replace(_response(), "Content-Security-Policy", value))
    )


def test_script_element_override_cannot_weaken_the_nonce_policy() -> None:
    response = _replace(_response(), "Content-Security-Policy", _CSP + "; script-src-elem 'unsafe-inline'")
    assert any(finding.check == "csp" for finding in web.evaluate(_target(), response))


def test_voice_policy_allows_explicit_same_origin_microphone() -> None:
    target = _target().model_copy(update={"permissions": {"camera": [], "geolocation": [], "microphone": ["self"]}})
    response = _replace(_response(), "Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
    assert web.evaluate(target, response) == []


@pytest.mark.parametrize(
    "permissions",
    [
        'camera=(), geolocation=(), microphone=("https://voice.example.com)',
        'camera=(), geolocation=(), microphone=(), speaker-selection=("',
        'camera=(), geolocation=(), microphone=();report-to="',
        "camera=(), geolocation=(), microphone=(1)",
        "camera=(), geolocation=(),\u2003microphone=()",
    ],
    ids=[
        "unclosed-approved-origin",
        "unclosed-extra-member",
        "unclosed-reporting-parameter",
        "numeric-origin",
        "non-ascii-whitespace",
    ],
)
def test_malformed_permissions_cannot_prove_browser_restrictions(permissions: str) -> None:
    target = _target().model_copy(
        update={"permissions": {"camera": [], "geolocation": [], "microphone": ["self", "https://voice.example.com"]}}
    )
    response = _replace(_response(), "Permissions-Policy", permissions)
    assert [finding.check for finding in web.evaluate(target, response)] == ["browser-permissions"]


@pytest.mark.parametrize(
    "permissions",
    [
        'camera=(), geolocation=(), microphone=(self "https://voice.example.com");report-to=default, fullscreen=*',
        "camera=(), geolocation=(), microphone=self",
        'camera=(), geolocation=(), microphone=(), future-feature=("comma,value")',
    ],
    ids=["approved-voice-origins-and-reporting", "standalone-self", "unrelated-structured-string"],
)
def test_valid_structured_permissions_preserve_declared_voice_access(permissions: str) -> None:
    target = _target().model_copy(
        update={"permissions": {"camera": [], "geolocation": [], "microphone": ["self", "https://voice.example.com"]}}
    )
    assert web.evaluate(target, _replace(_response(), "Permissions-Policy", permissions)) == []


def test_report_only_script_policy_still_enforces_framing() -> None:
    target = _target().model_copy(update={"csp_mode": "report-only"})
    response = _replace(_response(), "Content-Security-Policy", "frame-ancestors 'none'")
    response.headers.append(("Content-Security-Policy-Report-Only", _CSP))
    assert web.evaluate(target, response) == []


def test_report_only_migration_accepts_an_already_enforced_strict_policy() -> None:
    target = _target().model_copy(update={"csp_mode": "report-only"})
    assert web.evaluate(target, _response()) == []


def test_private_content_returning_200_fails_even_with_security_headers() -> None:
    target = web.Target(name="private-doc", url="https://example.com/private", kind="private")
    assert [finding.check for finding in web.evaluate(target, _response())] == ["anonymous-access"]


@pytest.mark.parametrize(
    ("location", "passes"),
    [
        ("https://team.cloudflareaccess.com/cdn-cgi/access/login/example.com", True),
        ("https://team.cloudflareaccess.com.attacker.invalid/login", False),
        ("https://attacker.invalid/?next=https://team.cloudflareaccess.com", False),
        ("http://team.cloudflareaccess.com/login", False),
        ("https://user:secret@team.cloudflareaccess.com/login", False),
        ("/login", False),
    ],
    ids=["access-login", "suffix-spoof", "query-spoof", "cleartext", "userinfo", "undeclared-relative-login"],
)
def test_private_access_requires_an_exact_approved_https_login_host(location: str, passes: bool) -> None:
    target = web.Target(
        name="private-doc", url="https://example.com/", kind="private", login_hosts=["team.cloudflareaccess.com"]
    )
    findings = web.evaluate(target, web.Response(status=302, headers=[("Location", location)]))
    assert (findings == []) is passes


def test_generic_cloudflare_403_does_not_prove_authentication() -> None:
    target = web.Target(name="private-doc", url="https://example.com/", kind="private")
    assert web.evaluate(target, web.Response(status=403, headers=[]))


def test_http_authentication_denial_requires_its_challenge() -> None:
    target = web.Target(name="private-api", url="https://example.com/api", kind="private")
    assert web.evaluate(target, web.Response(status=401, headers=[]))
    assert web.evaluate(target, web.Response(status=401, headers=[("WWW-Authenticate", "Bearer")])) == []


@pytest.mark.parametrize("challenge", ["", "   "], ids=["empty", "whitespace"])
def test_private_endpoint_rejects_an_empty_http_authentication_challenge(challenge: str) -> None:
    target = web.Target(name="private-api", url="https://example.com/api", kind="private")
    response = web.Response(status=401, headers=[("WWW-Authenticate", challenge)])
    assert [finding.check for finding in web.evaluate(target, response)] == ["anonymous-access"]


def test_declared_application_denial_is_supported() -> None:
    target = web.Target(
        name="private-api",
        url="https://example.com/api",
        kind="private",
        denial_headers={"X-Application-Authentication": "required"},
    )
    response = web.Response(status=403, headers=[("X-Application-Authentication", "required")])
    assert web.evaluate(target, response) == []


def test_api_cache_policy_is_independent_of_html_csp() -> None:
    target = web.Target(name="api", url="https://example.com/api", kind="api")
    response = _replace(_response(), "Content-Type", "application/json")
    assert [finding.check for finding in web.evaluate(target, response)] == ["private-cache"]
    assert web.evaluate(target, _replace(response, "Cache-Control", "private, no-store")) == []


@pytest.mark.parametrize("attributes", ["Secure; SameSite=Lax", "HttpOnly; SameSite=Lax", "Secure; HttpOnly"])
def test_session_cookie_flags_are_checked_without_recording_values(attributes: str) -> None:
    target = _target().model_copy(update={"session_cookies": ["session"]})
    response = _replace(_response(), "Set-Cookie", "session=private-cookie-value; " + attributes)
    findings = web.evaluate(target, response)
    assert [finding.check for finding in findings] == ["session-cookie"]
    assert "private-cookie-value" not in json.dumps([finding.model_dump() for finding in findings])


def test_cross_site_session_cookies_keep_secure_and_httponly() -> None:
    target = _target().model_copy(update={"session_cookies": ["session"]})
    response = _replace(_response(), "Set-Cookie", "session=opaque; Secure; HttpOnly; SameSite=None")
    assert web.evaluate(target, response) == []


def test_cookie_issuance_can_be_required_without_requiring_it_on_every_page() -> None:
    target = _target().model_copy(update={"session_cookies": ["session"], "require_session_cookie": True})
    assert [finding.check for finding in web.evaluate(target, _response())] == ["session-cookie-missing"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:password@example.com",
        "https://example.com:8080",
        "https://example.com/#fragment",
        "https://example.com/\nheader",
    ],
)
def test_policy_rejects_unsafe_target_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        web.Target(name="target", url=url, kind="html")


def test_private_probe_cannot_use_credentials() -> None:
    with pytest.raises(ValidationError, match="anonymous"):
        web.Target(
            name="target", url="https://example.com", kind="private", request_headers_env={"Authorization": "TEST_AUTH"}
        )


def test_credential_probes_need_an_operator_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_STANDARDS_WEB_CREDENTIAL_HOSTS", raising=False)
    target = _target().model_copy(update={"request_headers_env": {"Authorization": "TEST_AUTH"}})
    with pytest.raises(ValueError, match="allowlist"):
        web.probe(target)


def test_missing_credential_is_not_reported_as_a_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_STANDARDS_WEB_CREDENTIAL_HOSTS", "example.com")
    monkeypatch.delenv("TEST_AUTH", raising=False)
    target = _target().model_copy(update={"request_headers_env": {"Authorization": "TEST_AUTH"}})
    with pytest.raises(ValueError, match="missing"):
        web.probe(target)


def test_transport_failure_returns_execution_error_and_withholds_credentials(
    tmp_path: Path,
) -> None:
    def failed_probe(_target: web.Target) -> web.Response:
        command = ["probe"]
        raise subprocess.TimeoutExpired(command, 15, output="private-cookie-value")

    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"schema_version": 1, "targets": [{"name": "home", "url": "https://example.com", "kind": "html"}]})
    )
    report = web.check_policy(path, fetch=failed_probe)
    assert report.exit_code == 2
    assert "private-cookie-value" not in report.model_dump_json()


def test_cli_violations_fail_and_invalid_policy_values_are_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def violations(_path: Path) -> web.Report:
        return web.Report(
            findings=[web.Finding(target="private", check="anonymous-access", message="Anonymous response was public.")]
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Real CLI dispatch resolves this public policy boundary internally; intercepting it avoids live network I/O while verifying the actual command and exit-code path.
        web,
        "check_policy",
        violations,
    )
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "targets": [{"name": "private", "url": "https://example.com", "kind": "private"}]}
        )
    )
    assert cli.main(["--root", str(tmp_path), "web-security", str(path)]) == 1
    assert "anonymous-access" in capsys.readouterr().out
    monkeypatch.undo()
    path.write_text('{"schema_version":true,"private":"never-echo-this-value"}')
    assert cli.main(["--root", str(tmp_path), "web-security", str(path)]) == 2
    assert "never-echo-this-value" not in capsys.readouterr().out


def test_html_policy_cannot_omit_all_browser_controls() -> None:
    with pytest.raises(ValidationError, match="permissions"):
        web.Target(name="home", url="https://example.com", kind="html", permissions={})


def test_framing_policy_rejects_a_global_wildcard() -> None:
    with pytest.raises(ValidationError, match="framing"):
        web.Target(name="home", url="https://example.com", kind="html", frame_ancestors=["*"])


def test_a_script_host_allowlist_does_not_replace_nonce_authorization() -> None:
    policy = _CSP.replace(" 'strict-dynamic'", " https://scripts.example.com")
    assert any(
        finding.check == "csp"
        for finding in web.evaluate(_target(), _replace(_response(), "Content-Security-Policy", policy))
    )


def test_duplicate_permission_directives_do_not_pass_as_a_deny_policy() -> None:
    value = "camera=(), geolocation=(), microphone=(), microphone=(*)"
    assert any(
        finding.check == "browser-permissions"
        for finding in web.evaluate(_target(), _replace(_response(), "Permissions-Policy", value))
    )


def test_no_store_does_not_hide_a_sensitive_edge_cache_hit() -> None:
    target = web.Target(name="api", url="https://example.com/api", kind="api")
    response = _replace(_response(), "Cache-Control", "no-store")
    response = _replace(response, "CF-Cache-Status", "HIT")
    assert [finding.check for finding in web.evaluate(target, response)] == ["private-edge-cache"]


def test_referrer_policy_uses_the_last_recognized_fallback() -> None:
    response = _replace(_response(), "Referrer-Policy", "unsafe-url, no-referrer, future-unknown-token")
    assert web.evaluate(_target(), response) == []
