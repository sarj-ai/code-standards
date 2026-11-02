from __future__ import annotations

import base64
import binascii
from contextlib import closing
from http import HTTPStatus
from http.client import HTTPException, HTTPSConnection
from http.cookies import CookieError, SimpleCookie
import json
import os
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- Fixed argv invokes an isolated, deadline-bounded HTTPS probe; target data travels over stdin.
import sys
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, Self
from urllib.parse import urlsplit

from http_sfv.dictionary import Dictionary
from http_sfv.item import InnerList, Item
from http_sfv.types import Token
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    RootModel,
    ValidationError,
    field_validator,
    model_validator,
)

from sarj_standards.libs.json_boundary import parse_unique_json


_DEADLINE_SECONDS: Final = 15
_CONTROL_CHAR_LIMIT: Final = 32
_MIN_NONCE_BYTES: Final = 16
_MAX_POLICY_BYTES: Final = 1_048_576
_MAX_HEADER_BYTES: Final = 131_072
_HEADER_ENV_NAMES: Final = frozenset({"authorization", "cookie", "cf-access-client-id", "cf-access-client-secret"})
_REFERRER_POLICIES: Final = frozenset(
    {"no-referrer", "same-origin", "strict-origin", "strict-origin-when-cross-origin"}
)
_VALID_REFERRER_POLICIES: Final = _REFERRER_POLICIES | {
    "no-referrer-when-downgrade",
    "origin",
    "origin-when-cross-origin",
    "unsafe-url",
}
_DEFAULT_PERMISSIONS: Final = ("camera", "geolocation", "microphone")

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


class _StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)


class Target(_StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")
    url: str
    kind: Literal["html", "api", "private"]
    login_hosts: list[str] = Field(default_factory=list)
    denial_headers: dict[str, str] = Field(default_factory=dict)
    request_headers_env: dict[str, str] = Field(default_factory=dict)
    session_cookies: list[str] = Field(default_factory=list)
    require_session_cookie: bool = False
    csp_mode: Literal["enforce", "report-only"] = "enforce"
    frame_ancestors: list[str] = Field(default_factory=lambda: ["'none'"])
    permissions: dict[str, list[str]] = Field(default_factory=lambda: {name: [] for name in _DEFAULT_PERMISSIONS})
    hsts_min_age: Annotated[int, Field(ge=300, le=63_072_000)] = 31_536_000

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            msg = "targets require an HTTPS URL without userinfo or fragments"
            raise ValueError(msg)
        if parsed.port not in {None, 443} or any(ord(char) < _CONTROL_CHAR_LIMIT for char in value):
            msg = "targets require the standard HTTPS port and no control characters"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        if self.kind == "private" and self.request_headers_env:
            msg = "private probes must remain anonymous; add a separate authenticated html/api probe"
            raise ValueError(msg)
        for header, variable in self.request_headers_env.items():
            if header.lower() not in _HEADER_ENV_NAMES or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", variable):
                msg = "credential headers must reference named environment variables"
                raise ValueError(msg)
        for host in self.login_hosts:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host):
                msg = "login_hosts must contain exact hostnames"
                raise ValueError(msg)
        if self.require_session_cookie and not self.session_cookies:
            msg = "require_session_cookie needs declared session cookie names"
            raise ValueError(msg)
        if self.kind == "html" and not set(_DEFAULT_PERMISSIONS) <= self.permissions.keys():
            msg = "HTML policies must declare camera, geolocation and microphone permissions"
            raise ValueError(msg)
        if "*" in self.frame_ancestors:
            msg = "framing requires explicit approved origins, not a global wildcard"
            raise ValueError(msg)
        return self


class WebPolicy(_StrictModel):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    targets: Annotated[list[Target], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_names(self) -> Self:
        if len({target.name for target in self.targets}) != len(self.targets):
            msg = "target names must be unique"
            raise ValueError(msg)
        return self


class Response(_StrictModel):
    status: int
    headers: list[tuple[str, str]]

    def values(self, name: str) -> list[str]:
        return [value.strip() for key, value in self.headers if key.lower() == name]


class Finding(_StrictModel):
    target: str
    check: str
    message: str


class Report(_StrictModel):
    targets_checked: int = 0
    findings: list[Finding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 2
        return int(bool(self.findings))


class _ProbeRequest(_StrictModel):
    url: str
    headers: dict[str, str]


class _PermissionsDictionary(RootModel[dict[str, InstanceOf[Item] | InstanceOf[InnerList]]]):
    pass


def evaluate(target: Target, response: Response) -> list[Finding]:
    if target.kind == "private":
        failures = list(_authentication_failures(target, response))
    elif response.status != HTTPStatus.OK:
        failures = [("response-status", "Expected a successful application response; redirects are not followed.")]
    else:
        failures = [*_security_header_failures(target, response), *_cookie_failures(target, response)]
        if target.kind == "html":
            failures.extend(_html_failures(target, response))
        if target.kind == "api" or target.request_headers_env:
            failures.extend(_private_cache_failures(response))
    return [Finding(target=target.name, check=check, message=message) for check, message in failures]


def _private_cache_failures(response: Response) -> Iterator[tuple[str, str]]:
    controls = response.values("cache-control")
    if not any("no-store" in [part.strip().lower() for part in value.split(",")] for value in controls):
        yield (
            "private-cache",
            "Sensitive responses must include Cache-Control: no-store; configure edge cache bypass separately.",
        )
    if any(
        value.upper() in {"HIT", "STALE", "UPDATING", "REVALIDATED"} for value in response.values("cf-cache-status")
    ):
        yield (
            "private-edge-cache",
            "Sensitive responses must bypass shared edge caching; a response header alone does not change Cloudflare caching.",
        )


def _authentication_failures(target: Target, response: Response) -> Iterator[tuple[str, str]]:
    denial = response.status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN} and (
        (
            bool(target.denial_headers)
            and all(response.values(name.lower()) == [value] for name, value in target.denial_headers.items())
        )
        or (
            not target.login_hosts
            and response.status == HTTPStatus.UNAUTHORIZED
            and any(response.values("www-authenticate"))
        )
    )
    if not denial and not _approved_login(target, response):
        yield (
            "anonymous-access",
            "Private endpoint must reject anonymous requests or redirect to an explicitly allowed login host.",
        )
    if response.status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN} and response.values("cf-mitigated"):
        yield ("authentication-proof", "A Cloudflare challenge does not prove application authentication.")


def _approved_login(target: Target, response: Response) -> bool:
    locations = response.values("location")
    if (
        response.status not in {301, 302, 303, 307, 308}
        or len(locations) != 1
        or any(ord(char) < _CONTROL_CHAR_LIMIT for char in locations[0])
    ):
        return False
    try:
        login = urlsplit(locations[0])
        return (
            login.scheme == "https"
            and not login.username
            and not login.password
            and login.hostname in {host.lower() for host in target.login_hosts}
            and login.port in {None, 443}
        )
    except ValueError:
        return False


def _security_header_failures(target: Target, response: Response) -> Iterator[tuple[str, str]]:
    if [value.lower() for value in response.values("x-content-type-options")] != ["nosniff"]:
        yield ("content-type-options", "Set one X-Content-Type-Options: nosniff response header.")
    referrers = [
        token
        for value in response.values("referrer-policy")
        for part in value.split(",")
        if (token := part.strip().lower()) in _VALID_REFERRER_POLICIES
    ]
    if not referrers or referrers[-1] not in _REFERRER_POLICIES:
        yield ("referrer-policy", "Use a referrer policy that does not expose paths across origins.")
    hsts = response.values("strict-transport-security")
    match = re.search(r"(?:^|;)\s*max-age\s*=\s*(\d+)\s*(?:;|$)", hsts[0], re.IGNORECASE) if len(hsts) == 1 else None
    if (
        not match
        or len(re.findall(r"(?:^|;)\s*max-age\s*=", hsts[0], re.IGNORECASE)) != 1
        or int(match.group(1)) < target.hsts_min_age
    ):
        yield (
            "hsts",
            "Set HSTS with at least the policy's minimum max-age; subdomain coverage and preload are separate decisions.",
        )


def _cookie_failures(target: Target, response: Response) -> Iterator[tuple[str, str]]:
    issued: set[str] = set()
    for value in response.values("set-cookie"):
        name = value.partition("=")[0].strip()
        if name not in target.session_cookies:
            continue
        issued.add(name)
        cookie = SimpleCookie()
        try:
            cookie.load(value)
        except CookieError:
            yield ("session-cookie", "A declared session cookie could not be parsed safely.")
            continue
        if name not in cookie:
            yield ("session-cookie", "A declared session cookie could not be parsed safely.")
            continue
        same_site: object = cookie[name]["samesite"]  # pyright: ignore[reportAny] -- The stdlib Morsel mapping exposes attribute values as Any; validate the response value before string operations.
        if (
            not cookie[name]["secure"]
            or not cookie[name]["httponly"]
            or not isinstance(same_site, str)
            or same_site.lower() not in {"strict", "lax", "none"}
        ):
            yield (
                "session-cookie",
                "Declared session cookies must use Secure, HttpOnly and an explicit SameSite attribute.",
            )
    if target.require_session_cookie and not issued:
        yield ("session-cookie-missing", "This probe must issue a declared session cookie.")


def _html_failures(target: Target, response: Response) -> Iterator[tuple[str, str]]:
    if not any(
        value.split(";", 1)[0].lower() in {"text/html", "application/xhtml+xml"}
        for value in response.values("content-type")
    ):
        yield ("html-content-type", "The HTML probe must receive an HTML Content-Type.")
    policies = response.values("content-security-policy")
    if target.csp_mode == "report-only":
        policies += response.values("content-security-policy-report-only")
    if not any(_strict_csp(value) for value in policies):
        yield (
            "csp",
            "Use a nonce/hash-based script policy, object-src 'none', and a restricted base-uri in the selected CSP mode.",
        )
    if not _approved_framing(target, response):
        yield ("framing", "Enforce CSP frame-ancestors using only the policy's approved embedding origins.")
    if not _approved_permissions(target, response):
        yield (
            "browser-permissions",
            "Declare each required browser feature with only its approved origins; preserve microphone access where needed.",
        )


def _approved_framing(target: Target, response: Response) -> bool:
    for value in response.values("content-security-policy"):
        tokens = _directives(value).get("frame-ancestors", [])
        if tokens == ["'none'"] or (bool(tokens) and set(tokens) <= set(target.frame_ancestors)):
            return True
    return False


def _approved_permissions(target: Target, response: Response) -> bool:
    permissions = Dictionary()
    try:
        permissions.parse(",".join(response.values("permissions-policy")).encode("ascii"))
        members = _PermissionsDictionary.model_validate(permissions).root
    except UnicodeEncodeError, ValueError:
        return False
    for feature, allowed in target.permissions.items():
        origins = _permission_origins(members.get(feature))
        if origins is None or not origins <= set(allowed):
            return False
    return True


def _permission_origins(member: object) -> set[str] | None:
    if isinstance(member, Item):
        return {"self"} if isinstance(member.value, Token) and member.value == "self" else None
    if not isinstance(member, InnerList):
        return None
    origins: set[str] = set()
    for item in list[object](member):
        if not isinstance(item, Item):
            return None
        value = item.value
        if not isinstance(value, str) or (isinstance(value, Token) and value != "self"):
            return None
        origins.add(value)
    return origins


def _strict_csp(value: str) -> bool:
    policy = _directives(value)
    scripts = policy.get("script-src", policy.get("default-src", []))
    return (
        _strict_scripts(scripts)
        and _strict_scripts(policy.get("script-src-elem", scripts))
        and policy.get("script-src-attr", ["'none'"]) == ["'none'"]
        and policy.get("object-src", policy.get("default-src")) == ["'none'"]
        and policy.get("base-uri") in (["'none'"], ["'self'"])
    )


def _strict_scripts(scripts: list[str]) -> bool:
    if scripts == ["'none'"]:
        return True
    if not {"'unsafe-inline'", "'unsafe-eval'", "*", "data:", "http:", "https:"}.isdisjoint(scripts):
        return False
    if not any(_script_source(token) for token in scripts):
        return False
    return "'strict-dynamic'" in scripts or all(
        _script_source(source) or source == "'report-sample'" for source in scripts
    )


def _script_source(value: str) -> bool:
    match = re.fullmatch(r"'(nonce|sha256|sha384|sha512)-([a-zA-Z0-9+/_-]+={0,2})'", value)
    if not match:
        return False
    try:
        decoded = base64.b64decode(match.group(2) + "=" * (-len(match.group(2)) % 4), altchars=b"-_", validate=True)
    except binascii.Error:
        return False
    return (
        len(decoded) >= _MIN_NONCE_BYTES
        if match.group(1) == "nonce"
        else len(decoded) == {"sha256": 32, "sha384": 48, "sha512": 64}[match.group(1)]
    )


def _directives(value: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in value.split(";"):
        words = part.split()
        if words:
            result.setdefault(words[0].lower(), words[1:])
    return result


def probe(target: Target) -> Response:
    headers: dict[str, str] = {}
    if target.request_headers_env:
        configured_hosts = os.environ.get("CODE_STANDARDS_WEB_CREDENTIAL_HOSTS", "")  # ruff: ignore[banned-api] -- The operator's exact host allowlist is read without reflecting any environment values.
        allowed_hosts = {value.strip().lower() for value in configured_hosts.split(",") if value.strip()}
        if urlsplit(target.url).hostname not in allowed_hosts:
            msg = "Credential probes require an operator-provided CODE_STANDARDS_WEB_CREDENTIAL_HOSTS allowlist."
            raise ValueError(msg)
    for name, variable in target.request_headers_env.items():
        value = os.environ.get(variable)  # ruff: ignore[banned-api] -- Policy declares dynamic credential environment names; values remain in the private probe pipe and are never reported.
        if not value or "\r" in value or "\n" in value:
            msg = "A required credential environment variable is missing or invalid."
            raise ValueError(msg)
        headers[name] = value
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- Fixed Python executable/module, no shell; URL and credentials are JSON on stdin.
        [sys.executable, "-I", "-m", __name__],
        input=json.dumps({"url": target.url, "headers": headers}),
        capture_output=True,
        text=True,
        timeout=_DEADLINE_SECONDS,
        check=False,
    )
    if completed.returncode:
        msg = "HTTPS probe failed; response details and credentials are withheld."
        raise ValueError(msg)
    return Response.model_validate_json(completed.stdout)


def check_policy(path: Path, *, fetch: Callable[[Target], Response] = probe) -> Report:
    if path.stat().st_size > _MAX_POLICY_BYTES:
        msg = "Web policy exceeds the 1 MiB limit."
        raise ValueError(msg)
    policy = WebPolicy.model_validate(parse_unique_json(path.read_text(encoding="utf-8")))
    report = Report()
    for target in policy.targets:
        try:
            response = fetch(target)
        except OSError, ValueError, ValidationError, subprocess.TimeoutExpired:
            report.errors.append(
                target.name + ": HTTPS probe could not complete safely; credentials and response values are withheld."
            )
            continue
        report.targets_checked += 1
        report.findings.extend(evaluate(target, response))
    return report


def _probe_worker() -> int:
    try:
        payload = _ProbeRequest.model_validate_json(sys.stdin.read(_MAX_HEADER_BYTES))
        response = _fetch_response(payload)
    except OSError, ValueError, HTTPException:
        return 2
    sys.stdout.write(response.model_dump_json() + "\n")
    return 0


def _fetch_response(payload: _ProbeRequest) -> Response:
    parsed = urlsplit(payload.url)
    hostname = parsed.hostname
    if hostname is None:
        msg = "HTTPS probe requires a hostname."
        raise ValueError(msg)
    with closing(HTTPSConnection(hostname, timeout=10)) as connection:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers={"User-Agent": "code-standards-web-security/1.0", **payload.headers})
        response = connection.getresponse()
        headers = response.getheaders()
        if sum(len(name) + len(value) for name, value in headers) > _MAX_HEADER_BYTES:
            msg = "Response headers exceed the probe limit."
            raise ValueError(msg)
        return Response(status=response.status, headers=headers)


if __name__ == "__main__":
    raise SystemExit(_probe_worker())
