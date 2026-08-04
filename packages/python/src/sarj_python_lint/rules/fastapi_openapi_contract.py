"""SARJ094 — FastAPI operations must publish an explicit, accurate OpenAPI contract.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_fastapi_openapi_contract.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._fastapi import (
    SCHEMA_MARKERS,
    FastapiIndex,
    Route,
    flat_name,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PATH_PARAMETER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]+)?\}")
_STATUS_RE = re.compile(r"HTTP_(\d{3})_")
_RAW_MAPPINGS = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_CONTAINERS = frozenset({"list", "List", "set", "Set", "tuple", "Tuple", "Sequence"})
_BODY_MARKERS = frozenset({"Body", "Form", "File"})
_NO_CONTENT_STATUSES = frozenset({204, 304})


@dataclass(frozen=True, slots=True)
class _Finding:
    node: ast.expr | ast.stmt | ast.arg
    message: str


class FastapiOpenapiContract(Rule):
    id: str = "fastapi-openapi-contract"
    code: str = "SARJ094"
    description: str = "FastAPI operations must publish explicit request, response, and OpenAPI contracts."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        index = FastapiIndex(tree)
        scopes = _function_scopes(tree)
        findings: list[_Finding] = []
        declared: list[tuple[int, Route]] = []
        for function in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef):
            routes = tuple(route for route in index.routes(function) if not _is_hidden(route))
            if not routes:
                continue
            declared.extend((scopes[id(function)], route) for route in routes)
            findings.extend(_check_parameters(function, routes, index))
            findings.extend(_check_return(function, routes, index))
            findings.extend(_check_raw_request(function, routes, index))
            findings.extend(_check_direct_responses(function, routes, index))
            for route in routes:
                findings.extend(_check_metadata(function, route))
                findings.extend(_check_projection(route))
        findings.extend(_check_route_conflicts(declared))
        return [
            Diagnostic(
                path=path,
                line=finding.node.lineno,
                col=finding.node.col_offset + 1,
                code=self.code,
                message=finding.message,
            )
            for finding in sorted(
                findings, key=lambda finding: (finding.node.lineno, finding.node.col_offset, finding.message)
            )
        ]


def _is_hidden(route: Route) -> bool:
    value = route.keywords.get("include_in_schema")
    return isinstance(value, ast.Constant) and value.value is False


def _check_metadata(function: ast.FunctionDef | ast.AsyncFunctionDef, route: Route) -> list[_Finding]:
    if route.has_unpack:
        return []
    keywords = route.keywords
    missing: list[str] = []
    if not _nonblank(keywords.get("summary")):
        missing.append("summary")
    docstring = ast.get_docstring(function, clean=False)
    if not (_nonblank(keywords.get("description")) or bool(docstring and docstring.strip())):
        missing.append("description or handler docstring")
    if "status_code" not in keywords or _literal_none(keywords["status_code"]):
        missing.append("status_code")
    if not missing:
        return []
    return [_Finding(route.decorator, f"[metadata] operation requires explicit {', '.join(missing)}.")]


def _nonblank(node: ast.expr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(node.value.strip())
    return True


def _literal_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _function_parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.arg, ast.expr | None]]:
    positional = [*function.args.posonlyargs, *function.args.args]
    padded_defaults = [None] * (len(positional) - len(function.args.defaults)) + list(function.args.defaults)
    parameters = list(zip(positional, padded_defaults, strict=True))
    parameters.extend(zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True))
    if function.args.vararg is not None:
        parameters.append((function.args.vararg, None))
    if function.args.kwarg is not None:
        parameters.append((function.args.kwarg, None))
    return parameters


def _check_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    routes: tuple[Route, ...],
    index: FastapiIndex,
) -> list[_Finding]:
    findings: list[_Finding] = []
    for parameter, default in _function_parameters(function):
        if parameter.arg in {"self", "cls"} or parameter.annotation is None:
            continue
        if isinstance(default, ast.Call) and index.marker(default) is not None:
            continue
        if index.is_injection(parameter.annotation):
            continue
        parts = index.annotated_parts(parameter.annotation)
        if parts is None:
            findings.append(_Finding(parameter, f"[parameter] `{parameter.arg}` requires explicit Annotated metadata."))
            continue
        value_type, metadata = parts
        markers = [resolved for item in metadata if (resolved := index.marker(item)) is not None]
        if len(markers) != 1:
            findings.append(
                _Finding(parameter, f"[parameter] `{parameter.arg}` requires exactly one FastAPI parameter marker.")
            )
            continue
        marker_name, marker_call = markers[0]
        if marker_name in SCHEMA_MARKERS and not _nonblank(_keyword(marker_call, "description")):
            findings.append(
                _Finding(parameter, f"[parameter] `{parameter.arg}` marker requires a non-empty description.")
            )
        if marker_name in SCHEMA_MARKERS and _schema_erasing(value_type, index):
            findings.append(
                _Finding(
                    parameter, f"[parameter] `{parameter.arg}` uses a schema-erasing request type; define a model."
                )
            )
        if marker_name == "Path":
            if default is not None or _contains_none(value_type, index):
                findings.append(
                    _Finding(parameter, f"[parameter] Path `{parameter.arg}` must be required and non-nullable.")
                )
            literal_paths = [route.path for route in routes if route.path is not None]
            if literal_paths and any(parameter.arg not in _path_parameters(path) for path in literal_paths):
                findings.append(
                    _Finding(parameter, f"[parameter] Path `{parameter.arg}` is not present in route path.")
                )
        if marker_name in _BODY_MARKERS and any(route.method in {"get", "head"} for route in routes):
            findings.append(
                _Finding(
                    parameter, f"[parameter] {routes[0].method.upper()} operations must not declare a request body."
                )
            )
    return findings


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _contains_none(node: ast.expr, index: FastapiIndex) -> bool:
    resolved = index.resolve_annotation(node)
    if isinstance(resolved, ast.Constant):
        return resolved.value is None
    if isinstance(resolved, ast.Name):
        return resolved.id in {"None", "NoneType"}
    if isinstance(resolved, ast.BinOp) and isinstance(resolved.op, ast.BitOr):
        return _contains_none(resolved.left, index) or _contains_none(resolved.right, index)
    if isinstance(resolved, ast.Subscript) and flat_name(resolved.value) in {"Optional", "Union"}:
        return any(_contains_none(item, index) for item in _slice_items(resolved.slice))
    return False


def _is_none_annotation(node: ast.expr, index: FastapiIndex) -> bool:
    resolved = index.resolve_annotation(node)
    return (isinstance(resolved, ast.Constant) and resolved.value is None) or (
        isinstance(resolved, ast.Name) and resolved.id in {"None", "NoneType"}
    )


def _schema_erasing(node: ast.expr, index: FastapiIndex) -> bool:
    resolved = index.resolve_annotation(node)
    if resolved is None:
        return False
    parts = index.annotated_parts(resolved)
    if parts is not None:
        return _schema_erasing(parts[0], index)
    if isinstance(resolved, ast.BinOp) and isinstance(resolved.op, ast.BitOr):
        return _schema_erasing(resolved.left, index) or _schema_erasing(resolved.right, index)
    name = flat_name(resolved.value) if isinstance(resolved, ast.Subscript) else flat_name(resolved)
    if name in {"Any", "object"}:
        return True
    if name in _RAW_MAPPINGS:
        return True
    if name in _CONTAINERS:
        if not isinstance(resolved, ast.Subscript):
            return True
        return any(_schema_erasing(item, index) for item in _slice_items(resolved.slice))
    if isinstance(resolved, ast.Subscript) and name in {"Optional", "Union"}:
        return any(_schema_erasing(item, index) for item in _slice_items(resolved.slice))
    return False


def _slice_items(node: ast.expr) -> tuple[ast.expr, ...]:
    return tuple(node.elts) if isinstance(node, ast.Tuple) else (node,)


def _check_return(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    routes: tuple[Route, ...],
    index: FastapiIndex,
) -> list[_Finding]:
    annotation = index.resolve_annotation(function.returns)
    if annotation is None:
        return []
    findings: list[_Finding] = []
    if _schema_erasing(annotation, index):
        findings.append(
            _Finding(function, "[return] response annotation erases its OpenAPI schema; define an output model.")
        )
    is_response = index.is_response(annotation)
    is_none = _is_none_annotation(annotation, index)
    for route in routes:
        keywords = route.keywords
        response_model = keywords.get("response_model")
        response_model_none = response_model is not None and _literal_none(response_model)
        if is_response and ("response_class" not in keywords or not response_model_none):
            findings.append(
                _Finding(
                    function,
                    "[return] direct Response return requires response_class= and response_model=None for accurate OpenAPI.",
                )
            )
        elif not is_response and not is_none and response_model_none:
            findings.append(_Finding(function, "[return] response_model=None suppresses the declared response schema."))
        status = _status_code(keywords.get("status_code"))
        if status in _NO_CONTENT_STATUSES and (not response_model_none or not (is_none or is_response)):
            findings.append(
                _Finding(function, f"[return] status {status} requires -> None/Response and response_model=None.")
            )
    return findings


def _check_projection(route: Route) -> list[_Finding]:
    projected = sorted(name for name in ("response_model_include", "response_model_exclude") if name in route.keywords)
    if not projected:
        return []
    return [
        _Finding(
            route.decorator,
            f"[return] {', '.join(projected)} leaves OpenAPI inaccurate; define a dedicated output model.",
        )
    ]


def _check_raw_request(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    routes: tuple[Route, ...],
    index: FastapiIndex,
) -> list[_Finding]:
    request_names: set[str] = set()
    for parameter, _default in _function_parameters(function):
        resolved = index.resolve_annotation(parameter.annotation)
        if resolved is not None and index.is_injection(resolved) and index.canonical(resolved) == "Request":
            request_names.add(parameter.arg)
    if not request_names or any("openapi_extra" in route.keywords for route in routes):
        return []
    stack: list[ast.AST] = list(function.body)
    while stack:
        current = stack.pop()
        if current is not function and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr in {"body", "json", "form"}
            and isinstance(current.func.value, ast.Name)
            and current.func.value.id in request_names
        ):
            return [
                _Finding(
                    current,
                    "[parameter] direct Request body access requires openapi_extra.requestBody or a typed Body parameter.",
                )
            ]
        stack.extend(children(current))
    return []


def _check_direct_responses(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    routes: tuple[Route, ...],
    index: FastapiIndex,
) -> list[_Finding]:
    statuses: set[int] = set()
    stack: list[ast.AST] = list(function.body)
    while stack:
        current = stack.pop()
        if current is not function and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        call = current.exc if isinstance(current, ast.Raise) else None
        if isinstance(call, ast.Call) and index.is_http_exception(call.func):
            status = _status_code(_keyword(call, "status_code") or (call.args[0] if call.args else None))
            if status is not None:
                statuses.add(status)
        returned = current.value if isinstance(current, ast.Return) else None
        if isinstance(returned, ast.Call) and index.is_response(returned.func):
            status = _status_code(_keyword(returned, "status_code"))
            if status is not None:
                statuses.add(status)
        stack.extend(children(current))
    if not statuses:
        return []
    findings: list[_Finding] = []
    for route in routes:
        responses = route.keywords.get("responses")
        if responses is not None and not isinstance(responses, ast.Dict):
            continue
        documented: set[int] = _response_codes(responses) if isinstance(responses, ast.Dict) else set()
        primary = _status_code(route.keywords.get("status_code"))
        missing = sorted(statuses - documented - ({primary} if primary is not None else set()))
        if missing:
            findings.append(
                _Finding(
                    route.decorator,
                    f"[responses] document directly raised status codes: {', '.join(map(str, missing))}.",
                )
            )
    return findings


def _status_code(node: ast.expr | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute):
        match = _STATUS_RE.search(node.attr)
        if match is not None:
            return int(match.group(1))
    return None


def _response_codes(node: ast.Dict) -> set[int]:
    if any(key is None for key in node.keys):
        return set(range(100, 600))
    return {code for key in node.keys if key is not None and (code := _status_code(key)) is not None}


def _path_parameters(path: str) -> set[str]:
    return set(_PATH_PARAMETER_RE.findall(path))


def _function_scopes(tree: ast.Module) -> dict[int, int]:
    scopes: dict[int, int] = {}
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        current, owner = stack.pop()
        for child in children(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes[id(child)] = owner
                stack.append((child, child.lineno))
            else:
                stack.append((child, owner))
    return scopes


def _check_route_conflicts(routes: list[tuple[int, Route]]) -> list[_Finding]:
    findings: list[_Finding] = []
    seen: dict[tuple[int, str, str, str], Route] = {}
    dynamic: list[tuple[int, Route]] = []
    for scope, route in sorted(routes, key=lambda item: item[1].decorator.lineno):
        if route.path is None:
            continue
        key = scope, route.receiver, route.method, route.path
        if key in seen:
            findings.append(
                _Finding(route.decorator, f"[routing] duplicate {route.method.upper()} {route.path} route.")
            )
        else:
            seen[key] = route
        for earlier_scope, earlier in dynamic:
            if (
                earlier_scope == scope
                and earlier.receiver == route.receiver
                and earlier.method == route.method
                and _path_matches(earlier.path or "", route.path)
            ):
                findings.append(
                    _Finding(
                        route.decorator, f"[routing] static route {route.path} is shadowed by earlier {earlier.path}."
                    )
                )
                break
        if _path_parameters(route.path):
            dynamic.append((scope, route))
    return findings


def _path_matches(dynamic_path: str, static_path: str) -> bool:
    pattern = re.escape(dynamic_path)
    pattern = re.sub(r"\\\{[A-Za-z_][A-Za-z0-9_]*(?::[^}]+)?\\\}", "[^/]+", pattern)
    return re.fullmatch(pattern, static_path) is not None
