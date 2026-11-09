from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_ACCOUNT_URL = re.compile(
    r"\A(?i:https://api\.cloudflare\.com)/client/v4/accounts/([a-fA-F0-9]{32})(?:[/?#]|\Z)",
)
_HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put"})
_HTTP_MODULES = frozenset({"httpx", "requests", "urllib"})
_MAX_DEPTH = 16
_MAX_PARTS = 128
_MAX_BYTES = 8192
_UNKNOWN = "\x00"
_BAD = "import httpx\nACCOUNT = '0123456789abcdef0123456789abcdef'\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts')\n"
_GOOD = "from typing import Annotated\nimport httpx\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    cloudflare_account_id: Annotated[str, Field(pattern=r'^[a-fA-F0-9]{32}$')]\nsettings = Settings()\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/workers/scripts')\n"


class _Part(NamedTuple):
    text: str
    origin: ast.expr


@final
class PreferConfiguredCloudScope(Rule):
    id = "prefer-configured-cloud-scope"
    code = "SARJ566"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Read Cloudflare account targets from validated deployment configuration.",
        rationale=(
            "A literal account in a management API request binds the caller to one deployment. "
            "Reusing the script in another environment can target the original account even when its credentials change."
        ),
        remediation=(
            "Read the account ID through validated settings or a required environment variable at startup and inject it "
            "into the request builder. Preserve independent security allowlists and fail when required configuration "
            "is absent; do not replace a required setting with a production account fallback."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Initial scope is an explicit 32-digit hexadecimal Cloudflare account in an HTTPS v4 account-management "
                "URL passed to import-proven requests/httpx module functions or urllib.request.urlopen. "
                "Imported aliases, literal concatenation, f-strings and stable direct same-file assignments are followed."
            ),
            (
                "Reports each originating account literal once. Unknown account values, arbitrary service endpoints, "
                "worker names, UUIDs, unused strings and validation allowlists are not inferred. Settings and environment "
                "expressions are left to their existing validation controls."
            ),
            (
                "Client instances, injected request functions, format calls, environment fallbacks and cross-file values "
                "are not traced. Conditional/reassigned bindings, generated sources, tests and test support are excluded. "
                "Literal expansion stops at 16 nested expressions, 128 fragments or 8 KiB of text. "
                "A deliberately fixed operational target can retain an exact-code exception; there is no automatic rewrite."
            ),
        ),
        examples=(
            RuleExample(
                example_id="literal-account-request",
                title="The outgoing API request is bound to a literal account",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/publish.py", _BAD),),
                focus_path=PurePosixPath("app/publish.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="configured-account-request",
                title="Read the deployment account at the boundary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/publish.py", _GOOD),),
                focus_path=PurePosixPath("app/publish.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or context.tree is None
            or is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        if not _has_http_import(context):
            return []
        provenance = context.static_resource_provenance
        origins: set[ast.expr] = set()
        for call in context.nodes(ast.Call):
            url = _request_url(call, provenance)
            if url is None:
                continue
            parts = _parts(url, provenance)
            origin = _account_origin(parts)
            if origin is not None and not context.suppressions.is_suppressed(origin.lineno, self.code):
                origins.add(origin)
        return [
            Diagnostic(
                context.path,
                origin.lineno,
                origin.col_offset + 1,
                self.code,
                "This literal Cloudflare account flows to a management API request; read and validate the account "
                "from required deployment configuration, then inject it into the request builder. Preserve "
                "independent security allowlists.",
                severity=Severity.WARNING,
            )
            for origin in sorted(origins, key=lambda node: (node.lineno, node.col_offset))
        ]


def _has_http_import(context: PythonFileContext) -> bool:
    return any(
        (isinstance(node, ast.Import) and any(alias.name.partition(".")[0] in _HTTP_MODULES for alias in node.names))
        or (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module is not None
            and node.module.partition(".")[0] in _HTTP_MODULES
        )
        for node in context.nodes(ast.Import, ast.ImportFrom)
    )


def _request_url(call: ast.Call, provenance: ResourceProvenance) -> ast.expr | None:
    qualified = provenance.runtime_import_name(call.func)
    if qualified is None:
        return None
    module, _, method = qualified.rpartition(".")
    if qualified == "urllib.request.urlopen" or (module in {"requests", "httpx"} and method in _HTTP_METHODS):
        position = 0
    elif module in {"requests", "httpx"} and method == "request":
        position = 1
    else:
        return None
    keyword_url = next((keyword.value for keyword in call.keywords if keyword.arg == "url"), None)
    if keyword_url is not None:
        return keyword_url
    return call.args[position] if len(call.args) > position else None


def _parts(
    expression: ast.expr,
    provenance: ResourceProvenance,
    seen: frozenset[ast.AST] = frozenset(),
) -> tuple[_Part, ...]:
    if expression in seen or len(seen) >= _MAX_DEPTH:
        return (_Part(_UNKNOWN, expression),)
    seen |= {expression}
    match expression:
        case ast.Constant(value=str(text)):
            return (_Part(text if _within_text_budget(text) else _UNKNOWN, expression),)
        case ast.Name(id=name):
            binding = provenance.runtime_binding(name, expression)
            if not isinstance(binding, ast.Name) or binding in seen:
                return (_Part(_UNKNOWN, expression),)
            assignment = provenance.parents.get(binding)
            if assignment is None or provenance.parents.get(assignment) is not provenance.scope(binding):
                return (_Part(_UNKNOWN, expression),)
            value = _assignment_value(assignment)
            if value is None or (
                provenance.scope(binding) is provenance.scope(expression)
                and (binding.lineno, binding.col_offset) >= (expression.lineno, expression.col_offset)
            ):
                return (_Part(_UNKNOWN, expression),)
            return _parts(value, provenance, seen | {binding})
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            return _combine((_parts(left, provenance, seen), _parts(right, provenance, seen)), expression)
        case ast.JoinedStr(values=values):
            return _combine((_fstring_parts(value, provenance, seen) for value in values), expression)
        case _:
            return (_Part(_UNKNOWN, expression),)


def _within_text_budget(text: str) -> bool:
    return len(text) <= _MAX_BYTES and len(text.encode("utf-8", errors="surrogatepass")) <= _MAX_BYTES


def _combine(groups: Iterable[tuple[_Part, ...]], expression: ast.expr) -> tuple[_Part, ...]:
    parts: list[_Part] = []
    byte_count = 0
    for group in groups:
        for part in group:
            byte_count += len(part.text.encode("utf-8", errors="surrogatepass"))
            if len(parts) >= _MAX_PARTS or byte_count > _MAX_BYTES:
                return (_Part(_UNKNOWN, expression),)
            parts.append(part)
    return tuple(parts)


def _assignment_value(assignment: ast.AST | None) -> ast.expr | None:
    match assignment:
        case ast.Assign(targets=[ast.Name()], value=value):
            return value
        case ast.AnnAssign(target=ast.Name(), value=value):
            return value
        case _:
            return None


def _fstring_parts(value: ast.expr, provenance: ResourceProvenance, seen: frozenset[ast.AST]) -> tuple[_Part, ...]:
    if isinstance(value, ast.FormattedValue):
        if value.conversion in {-1, ord("s")} and value.format_spec is None:
            return _parts(value.value, provenance, seen)
        return (_Part(_UNKNOWN, value),)
    return _parts(value, provenance, seen)


def _account_origin(parts: tuple[_Part, ...]) -> ast.expr | None:
    match = _ACCOUNT_URL.match("".join(part.text for part in parts))
    if match is None:
        return None
    start = match.start(1)
    offset = 0
    for part in parts:
        if offset <= start < offset + len(part.text):
            return part.origin
        offset += len(part.text)
    return None
