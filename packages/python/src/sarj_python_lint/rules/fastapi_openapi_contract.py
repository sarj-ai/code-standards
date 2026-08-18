from __future__ import annotations

import ast
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
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
_STATUS_RE = re.compile(r"HTTP_(\d{3})_[A-Z0-9_]+")
_RAW_MAPPINGS = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_CONTAINERS = frozenset({"list", "List", "set", "Set", "tuple", "Tuple", "Sequence"})
_BODY_MARKERS = frozenset({"Body", "Form", "File"})
_NO_CONTENT_STATUSES = frozenset({204, 304})
_STATUS_CODE_DIGITS = 3
_DOCUMENTATION_EXAMPLE_DIR_NAMES = frozenset({"docs_src"})
_CONVERTER_PATTERNS = MappingProxyType(
    {
        "str": r"[^/]+",
        "path": r".+",
        "int": r"[0-9]+",
        "float": r"[0-9]+(?:\.[0-9]+)?",
        "uuid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    }
)


@dataclass(frozen=True, slots=True)
class _Finding:
    node: ast.expr | ast.stmt | ast.arg
    message: str


class FastapiOpenapiContract(Rule):
    id: str = "fastapi-openapi-contract"
    code: str = "SARJ094"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="FastAPI operations must publish accurate request, response, and status contracts.",
        rationale="Typed routes and explicit response behavior keep generated OpenAPI accurate without duplicating self-documenting names in prose.",
        remediation="Declare status codes, typed parameters, response schemas, and alternate responses raised directly by the handler.",
        category=RuleCategory.CORRECTNESS,
        limitations=(
            "Hidden routes, WebSocket handlers, tests, generated files, documentation-source examples, and unrelated decorators are excluded.",
            "Dynamic response mappings are accepted when their contents cannot be resolved statically.",
            "Imported dependency aliases are followed only through unique, nonsymlinked relative or same-package modules inside the detected checkout; traversal is bounded and ambiguity remains diagnostic.",
        ),
        examples=(
            RuleExample(
                example_id="missing-operation-metadata",
                title="Visible operation without an explicit success status",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n@router.get('/users')\nasync def users() -> list[UserResponse]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="documented-operation",
                title="Operation with an explicit OpenAPI contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n@router.get('/users', status_code=200)\nasync def read_users() -> list[UserResponse]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_generated(path, source)
            or any(part.lower() in _DOCUMENTATION_EXAMPLE_DIR_NAMES for part in path.parts)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        index = FastapiIndex(tree, path=path)
        scopes = _function_scopes(tree)
        findings: list[_Finding] = []
        declared: list[tuple[int, Route]] = []
        for function in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef):
            all_routes = index.routes(function)
            declared.extend((scopes[id(function)], route) for route in all_routes)
            routes = tuple(route for route in all_routes if not route.is_hidden)
            if not routes:
                continue
            findings.extend(_check_parameters(function, routes, index))
            findings.extend(_check_return(function, routes, index))
            findings.extend(_check_raw_request(function, routes, index))
            findings.extend(_check_direct_responses(function, routes, index))
            for route in _operations(routes):
                findings.extend(_check_metadata(route))
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


def _operations(routes: tuple[Route, ...]) -> tuple[Route, ...]:
    return tuple({id(route.decorator): route for route in routes}.values())


def _check_metadata(route: Route) -> list[_Finding]:
    if route.has_unpack:
        return []
    keywords = route.keywords
    if "status_code" in keywords and not _literal_none(keywords["status_code"]):
        return []
    return [_Finding(route.decorator, "[metadata] operation requires explicit status_code.")]


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
    contract_markers: dict[str, tuple[str | None, ast.arg]] = {}
    has_dynamic_alias = False
    for parameter, default in _function_parameters(function):
        if parameter.arg in {"self", "cls"} or parameter.annotation is None:
            continue
        if index.is_injection(parameter.annotation) or index.is_imported_dependency_alias(parameter.annotation):
            continue
        parts = index.annotated_parts(parameter.annotation)
        if parts is None:
            findings.append(_Finding(parameter, f"[parameter] `{parameter.arg}` requires explicit Annotated metadata."))
            contract_markers[parameter.arg] = (None, parameter)
            continue
        value_type, metadata = parts
        markers = [resolved for item in metadata if (resolved := index.marker(item)) is not None]
        if len(markers) != 1:
            findings.append(
                _Finding(parameter, f"[parameter] `{parameter.arg}` requires exactly one FastAPI parameter marker.")
            )
            contract_markers[parameter.arg] = (None, parameter)
            continue
        marker_name, marker_call = markers[0]
        alias = _keyword(marker_call, "alias")
        if alias is None:
            contract_markers[parameter.arg] = (marker_name, parameter)
        elif isinstance(alias, ast.Constant) and isinstance(alias.value, str):
            contract_markers[alias.value] = (marker_name, parameter)
        else:
            has_dynamic_alias = True
        if _has_embedded_default(marker_name, marker_call):
            findings.append(
                _Finding(parameter, f"[parameter] `{parameter.arg}` default belongs after `=`, not inside Annotated.")
            )
        if isinstance(default, ast.Call) and index.marker(default) is not None:
            findings.append(
                _Finding(parameter, f"[parameter] `{parameter.arg}` must not duplicate FastAPI marker metadata.")
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
            contract_name = alias.value if isinstance(alias, ast.Constant) and isinstance(alias.value, str) else None
            if alias is None:
                contract_name = parameter.arg
            if (
                contract_name is not None
                and literal_paths
                and any(contract_name not in _path_parameters(path) for path in literal_paths)
            ):
                findings.append(
                    _Finding(parameter, f"[parameter] Path `{contract_name}` is not present in route path.")
                )
        if marker_name in _BODY_MARKERS and any(route.method in {"get", "head"} for route in routes):
            bodyless_method = next(route.method for route in routes if route.method in {"get", "head"})
            findings.append(
                _Finding(
                    parameter, f"[parameter] {bodyless_method.upper()} operations must not declare a request body."
                )
            )
    if not has_dynamic_alias:
        for route in routes:
            if route.path is None:
                continue
            for path_name in sorted(_path_parameters(route.path)):
                marker = contract_markers.get(path_name)
                if marker is not None and marker[0] is None:
                    continue
                if marker is None or marker[0] != "Path":
                    node = marker[1] if marker is not None else function
                    findings.append(_Finding(node, f"[parameter] route path `{path_name}` requires a Path marker."))
    return findings


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _has_embedded_default(marker_name: str, marker_call: ast.Call) -> bool:
    marker_default = _keyword(marker_call, "default")
    positional_default = marker_call.args[0] if marker_call.args else None
    return marker_name in SCHEMA_MARKERS and (
        (marker_default is not None and not _ellipsis(marker_default))
        or (positional_default is not None and not _ellipsis(positional_default))
    )


def _ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _contains_none(node: ast.expr, index: FastapiIndex) -> bool:
    resolved = index.resolve_annotation(node)
    match resolved:
        case ast.Constant(value=None) | ast.Name(id="None" | "NoneType"):
            return True
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _contains_none(left, index) or _contains_none(right, index)
        case ast.Subscript(value=value, slice=annotation) if flat_name(value) in {"Optional", "Union"}:
            return any(_contains_none(item, index) for item in _slice_items(annotation))
        case _:
            return False


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
    problems: set[str] = set()
    if _schema_erasing(annotation, index):
        problems.add("response annotation erases its OpenAPI schema; define an output model")
    is_response = index.is_response(annotation)
    is_none = _is_none_annotation(annotation, index)
    for route in _operations(routes):
        if route.has_unpack:
            continue
        keywords = route.keywords
        response_model = keywords.get("response_model")
        response_model_none = response_model is not None and _literal_none(response_model)
        status = _status_code(keywords.get("status_code"), index)
        if is_response and status not in _NO_CONTENT_STATUSES and "response_class" not in keywords:
            problems.add("direct Response return requires response_class= for accurate OpenAPI")
        response_class = keywords.get("response_class")
        response_name = index.response_name(annotation)
        class_name = index.response_name(response_class)
        if response_name not in {"", "Response"} and class_name and response_name != class_name:
            problems.add(f"return type {response_name} conflicts with response_class={class_name}")
        if (
            is_response
            and status not in _NO_CONTENT_STATUSES
            and not _concrete_response_model(response_model, index)
            and not _documents_response_content(keywords.get("responses"), status, index)
        ):
            problems.add("direct Response return requires a concrete response_model or responses content schema")
        elif not is_response and not is_none and response_model_none:
            problems.add("response_model=None suppresses the declared response schema")
        if response_model is not None and not response_model_none and _schema_erasing(response_model, index):
            problems.add("response_model erases its OpenAPI schema; define an output model")
        if status in _NO_CONTENT_STATUSES:
            if response_model is not None and not response_model_none:
                problems.add(f"status {status} must not declare a response model")
            if not (is_none or is_response):
                problems.add(f"status {status} requires -> None/Response")
    if not problems:
        return []
    return [_Finding(function, f"[return] {'; '.join(sorted(problems))}.")]


def _is_none_annotation(node: ast.expr, index: FastapiIndex) -> bool:
    resolved = index.resolve_annotation(node)
    return (isinstance(resolved, ast.Constant) and resolved.value is None) or (
        isinstance(resolved, ast.Name) and resolved.id in {"None", "NoneType"}
    )


def _concrete_response_model(node: ast.expr | None, index: FastapiIndex) -> bool:
    return node is not None and not _literal_none(node) and not _schema_erasing(node, index)


def _documents_response_content(node: ast.expr | None, status: int | None, index: FastapiIndex) -> bool:
    if node is None:
        return False
    if not isinstance(node, ast.Dict):
        return True
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            return True
        if status is not None and status not in _response_codes(ast.Dict(keys=[key], values=[value]), index):
            continue
        if not isinstance(value, ast.Dict):
            return True
        for entry_key in value.keys:
            if isinstance(entry_key, ast.Constant) and entry_key.value == "content":
                return True
    return False


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
            status = _status_code(_keyword(call, "status_code") or (call.args[0] if call.args else None), index)
            if status is not None:
                statuses.add(status)
        returned = current.value if isinstance(current, ast.Return) else None
        if isinstance(returned, ast.Call) and index.is_response(returned.func):
            status = _status_code(_keyword(returned, "status_code"), index)
            if status is not None:
                statuses.add(status)
        stack.extend(children(current))
    if not statuses:
        return []
    findings: list[_Finding] = []
    for route in _operations(routes):
        responses = route.keywords.get("responses")
        if responses is not None and not isinstance(responses, ast.Dict):
            continue
        documented: set[int] = _response_codes(responses, index) if isinstance(responses, ast.Dict) else set()
        primary = _status_code(route.keywords.get("status_code"), index)
        missing = sorted(statuses - documented - ({primary} if primary is not None else set()))
        if missing:
            findings.append(
                _Finding(
                    route.decorator,
                    f"[responses] document directly raised status codes: {', '.join(map(str, missing))}.",
                )
            )
    return findings


def _status_code(node: ast.expr | None, index: FastapiIndex) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name) and (match := _STATUS_RE.fullmatch(index.canonical(node))):
        return int(match.group(1))
    if isinstance(node, ast.Attribute):
        if (match := _STATUS_RE.fullmatch(node.attr)) and index.canonical(node.value) == "status":
            return int(match.group(1))
        if index.canonical(node.value) == "HTTPStatus":
            member = HTTPStatus.__members__.get(node.attr)
            return member.value if member is not None else None
    return None


def _response_codes(node: ast.Dict, index: FastapiIndex) -> set[int]:
    if any(key is None for key in node.keys):
        return set(range(100, 600))
    codes: set[int] = set()
    for key in node.keys:
        if key is None:
            return set(range(100, 600))
        code = _status_code(key, index)
        if code is not None:
            codes.add(code)
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            normalized = key.value.upper()
            if normalized == "DEFAULT":
                return set(range(100, 600))
            if normalized.isdigit() and len(normalized) == _STATUS_CODE_DIGITS:
                codes.add(int(normalized))
                continue
            if re.fullmatch(r"[1-5]XX", normalized):
                start = int(normalized[0]) * 100
                codes.update(range(start, start + 100))
                continue
        return set(range(100, 600))
    return codes


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
    dynamic: dict[tuple[int, str, str], list[tuple[Route, re.Pattern[str]]]] = {}
    for scope, route in sorted(routes, key=lambda item: item[1].decorator.lineno):
        if route.path is None or route.method == "*":
            continue
        key = scope, route.receiver, route.method, route.path
        if key in seen:
            findings.append(
                _Finding(route.decorator, f"[routing] duplicate {route.method.upper()} {route.path} route.")
            )
        else:
            seen[key] = route
        bucket = dynamic.setdefault((scope, route.receiver, route.method), [])
        if not _path_parameters(route.path):
            for earlier, pattern in bucket:
                if pattern.fullmatch(route.path) is not None:
                    findings.append(
                        _Finding(
                            route.decorator,
                            f"[routing] static route {route.path} is shadowed by earlier {earlier.path}.",
                        )
                    )
                    break
        else:
            pattern = _path_pattern(route.path)
            if pattern is not None:
                bucket.append((route, pattern))
    return findings


def _path_pattern(path: str) -> re.Pattern[str] | None:
    parts: list[str] = []
    position = 0
    for match in re.finditer(r"\{[A-Za-z_][A-Za-z0-9_]*(?::([^}]+))?\}", path):
        parts.append(re.escape(path[position : match.start()]))
        converter = match.group(1) or "str"
        pattern = _CONVERTER_PATTERNS.get(converter)
        if pattern is None:
            return None
        parts.append(pattern)
        position = match.end()
    parts.append(re.escape(path[position:]))
    return re.compile("".join(parts))
