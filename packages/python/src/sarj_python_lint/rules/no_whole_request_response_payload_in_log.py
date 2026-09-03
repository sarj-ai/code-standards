from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr


if TYPE_CHECKING:
    from pathlib import Path


_PAYLOAD_TERMINALS = frozenset({"body", "bodies", "content", "data", "json", "payload", "payloads", "text"})
_REQUEST_RESPONSE = frozenset({"request", "requests", "response", "responses"})
_SAFE_METADATA = frozenset(
    {"count", "id", "ids", "length", "metadata", "redact", "redacted", "sanitized", "status", "summary"}
)
_SERIALIZERS = frozenset({"dict", "json", "model_dump"})
_SANITIZERS = frozenset({"redact", "sanitize", "summarize"})


def _reference_tokens(value: ast.expr) -> tuple[str, ...]:
    match value:
        case ast.Name(id=name):
            return tuple(identifier_tokens(name))
        case ast.Attribute(value=receiver, attr=attribute):
            return (*_reference_tokens(receiver), *identifier_tokens(attribute))
        case ast.Subscript(value=receiver):
            return _reference_tokens(receiver)
        case ast.Await(value=awaited):
            return _reference_tokens(awaited)
        case ast.Call(func=ast.Attribute(value=receiver, attr=method), args=[], keywords=keywords) if (
            method in _SERIALIZERS and all(keyword.arg == "mode" for keyword in keywords)
        ):
            return (*_reference_tokens(receiver), *identifier_tokens(method))
        case _:
            return ()


def _is_payload_reference(value: ast.expr, *, label: str | None = None) -> bool:
    if _is_safe_transform(value) or _is_secret_reference(value):
        return False
    tokens = (*identifier_tokens(label or ""), *_reference_tokens(value))
    if not tokens:
        return False
    if "not" not in tokens and any(token in _SAFE_METADATA for token in tokens):
        return False
    return bool(_REQUEST_RESPONSE.intersection(tokens) and _PAYLOAD_TERMINALS.intersection(tokens))


def _is_safe_transform(value: ast.expr) -> bool:
    if not isinstance(value, ast.Call):
        return False
    function = value.func
    function_name = (
        function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
    )
    if function_name in _SANITIZERS:
        return True
    return (
        isinstance(function, ast.Attribute)
        and function.attr in _SERIALIZERS
        and any(keyword.arg in {"include", "exclude"} for keyword in value.keywords)
    )


def _is_secret_reference(value: ast.expr) -> bool:
    return any(is_secret_name(token) for token in _reference_tokens(value))


def _interpolated_payloads(value: ast.expr) -> tuple[ast.expr, ...]:
    match value:
        case ast.JoinedStr(values=parts):
            candidates = tuple(part.value for part in parts if isinstance(part, ast.FormattedValue))
        case ast.BinOp(op=ast.Mod(), right=right):
            candidates = tuple(right.elts) if isinstance(right, (ast.Tuple, ast.List)) else (right,)
        case ast.BinOp(op=ast.Add(), left=left, right=right):
            direct_left = (left,) if _is_payload_reference(left) else ()
            direct_right = (right,) if _is_payload_reference(right) else ()
            return (*_interpolated_payloads(left), *_interpolated_payloads(right), *direct_left, *direct_right)
        case ast.Call(func=ast.Attribute(value=ast.Constant(value=str()), attr="format"), args=args, keywords=keywords):
            candidates = (*args, *(keyword.value for keyword in keywords))
        case _:
            return ()
    return tuple(candidate for candidate in candidates if _is_payload_reference(candidate))


@final
class NoWholeRequestResponsePayloadInLog(Rule):
    id: str = "no-whole-request-response-payload-in-log"
    code: str = "SARJ436"
    documentation = RuleDocumentation(
        summary="Whole request or response payloads passed to logging calls require review.",
        rationale=(
            "Request and response bodies often contain personal, financial, or echoed authentication data, while "
            "log sinks commonly have broader readership and longer retention."
        ),
        remediation=(
            "Log explicit non-sensitive metadata such as request IDs, response status, counts, or a deliberately "
            "sanitized summary. Suppress with a rationale when the payload type is proven public and bounded."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Detection is a lexical warning for direct request/response body, content, data, JSON, and payload references, including no-argument whole-object serializers and structured field names on recognized logger receivers.",
            "Generic request or response objects, unrelated body/payload values, explicitly sanitized summaries, aliases, dynamic containers, and interprocedural flows are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="response-payload-logged",
                title="Whole response payload passed to a logger",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "response_body = response.json()\nlogger.error('provider failed', response_body=response_body)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="response-metadata-logged",
                title="Only explicit response metadata is logged",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "logger.error('provider failed', request_id=request.id, response_status=response.status_code)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            if not _is_logging_call(node):
                continue
            values = [
                *(payload for argument in node.args for payload in _interpolated_payloads(argument)),
                *(argument for argument in node.args if _is_payload_reference(argument)),
                *(value for keyword in node.keywords for value in _keyword_payloads(keyword)),
            ]
            diagnostics.extend(_diagnostic(path, value) for value in values)
        return diagnostics


def _is_logging_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS and is_logger_expr(node.func.value)


def _keyword_payloads(keyword: ast.keyword) -> tuple[ast.expr, ...]:
    if keyword.arg is None:
        return ()
    if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
        values: list[ast.expr] = []
        for key, value in zip(keyword.value.keys, keyword.value.values, strict=True):
            label = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
            if _is_payload_reference(value, label=label):
                values.append(value)
        return tuple(values)
    return (keyword.value,) if _is_payload_reference(keyword.value, label=keyword.arg) else ()


def _diagnostic(path: Path, value: ast.expr) -> Diagnostic:
    return Diagnostic(
        path=path,
        line=value.lineno,
        col=value.col_offset + 1,
        code="SARJ436",
        message=(
            "Whole request or response payload may expose sensitive data to log readers — log explicit metadata "
            "or a sanitized summary instead."
        ),
        severity=Severity.WARNING,
    )
