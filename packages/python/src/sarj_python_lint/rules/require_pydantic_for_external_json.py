from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_JSON_MODULES = frozenset({"json", "orjson", "rapidjson", "ujson"})
_HTTP_MODULES = frozenset({"httpx", "requests"})
_HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "request"})
_HTTP_CLIENT_TYPES = frozenset({"AsyncClient", "Client", "Session"})
_OBJECT_VALIDATORS = frozenset({"model_validate", "parse_obj"})
_ADAPTER_VALIDATORS = frozenset({"validate_python"})
_RECORD_METHODS = frozenset({"get", "items", "keys", "values"})
_LOCAL_READ_METHODS = frozenset({"read_bytes", "read_text"})
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src", "examples"})


class _OwnedName(NamedTuple):
    owner: int
    name: str


class _ExternalRecordFinding(NamedTuple):
    sink: ast.expr
    origin: ast.Call


@dataclass(frozen=True, slots=True)
class _ModuleSummaries:
    decoder_parameters: dict[str, int]
    record_parameters: dict[str, frozenset[int]]
    local_parameters: dict[str, frozenset[int]]
    response_functions: frozenset[str]
    response_methods: frozenset[tuple[int, str]]
    function_owners: dict[int, int]
    http_client_attributes: frozenset[_OwnedName]


class _RecordAccess(NamedTuple):
    sink: ast.expr
    receiver: ast.expr


class _NamedBinding(NamedTuple):
    name: str
    value: ast.expr


class _ResponseCallables(NamedTuple):
    functions: frozenset[str]
    methods: frozenset[tuple[int, str]]
    function_owners: dict[int, int]


@final
class RequirePydanticForExternalJson(Rule):
    id = "require-pydantic-for-external-json"
    code = "SARJ411"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Externally sourced JSON is consumed without runtime schema validation.",
        rationale=(
            "Annotations, casts, key-by-key checks, and dictionary access do not validate a wire protocol; "
            "Pydantic makes required fields, types, and protocol versions explicit at the boundary."
        ),
        remediation=(
            "Use `Model.model_validate_json(payload)` or `TypeAdapter(Model).validate_json(payload)`, or "
            "validate an already-decoded value with `model_validate` or `validate_python` before use."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule follows common JSON decoders, typed HTTP response helpers and clients, and simple module-local helpers through single-assignment names.",
            "It diagnoses literal-key record access; dynamic JSON documents without fixed-field access remain out of scope.",
            "Repository-local JSON, json.load file handles, tests, generated files, and documentation examples are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="manual-external-json-access",
                title="External JSON read as a dictionary",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "protocol.py",
                        "import json\n\ndef parse(payload: str) -> object:\n    report = json.loads(payload)\n    return report.get('version')\n",
                    ),
                ),
                focus_path=PurePosixPath("protocol.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="pydantic-external-json-validation",
                title="External JSON validated by a boundary model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "protocol.py",
                        "def parse(payload: str) -> Report:\n    return Report.model_validate_json(payload)\n",
                    ),
                ),
                focus_path=PurePosixPath("protocol.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _excluded(path, source) or ("loads" not in source and ".json(" not in source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        summaries = _module_summaries(tree, imports)
        findings: list[tuple[ast.expr, ast.Call]] = []
        for function in _functions(tree):
            findings.extend(_function_findings(function, imports, summaries))

        first_by_origin: dict[int, tuple[ast.expr, ast.Call]] = {}
        for sink, origin in sorted(findings, key=lambda item: (item[0].lineno, item[0].col_offset)):
            first_by_origin.setdefault(id(origin), (sink, origin))
        return [
            Diagnostic(
                path=path,
                line=sink.lineno,
                col=sink.col_offset + 1,
                code=self.code,
                message=(
                    "External JSON field is read without Pydantic validation — validate the payload with "
                    "`Model.model_validate_json(...)` or `TypeAdapter(Model).validate_json(...)` first."
                ),
                severity=Severity.WARNING,
            )
            for sink, _origin in first_by_origin.values()
        ]


def _functions(tree: ast.Module) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _module_summaries(tree: ast.Module, imports: ImportIndex) -> _ModuleSummaries:
    functions = tuple(
        statement for statement in tree.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    duplicate_names = {name for name, count in Counter(function.name for function in functions).items() if count > 1}
    decoders: dict[str, int] = {}
    records: dict[str, frozenset[int]] = {}
    for function in functions:
        if function.name in duplicate_names:
            continue
        parameters = _parameter_positions(function)
        returned = tuple(node.value for node in _own_scope(function) if isinstance(node, ast.Return) and node.value)
        decoder_positions = {
            position
            for value in returned
            if (position := _decoded_parameter_position(value, parameters, imports)) is not None
        }
        if (
            returned
            and len(decoder_positions) == 1
            and all(_decoded_parameter_position(value, parameters, imports) in decoder_positions for value in returned)
        ):
            decoders[function.name] = decoder_positions.pop()

        consumed: set[int] = set()
        for node in _own_scope(function):
            receiver = _summary_record_receiver(node)
            if isinstance(receiver, ast.Name) and receiver.id in parameters:
                consumed.add(parameters[receiver.id])
        if consumed:
            records[function.name] = frozenset(consumed)
    response_callables = _response_callables(tree, imports)
    return _ModuleSummaries(
        decoders,
        records,
        _locally_sourced_parameters(functions),
        response_callables.functions,
        response_callables.methods,
        response_callables.function_owners,
        _http_client_attribute_names(tree, imports),
    )


def _response_callables(tree: ast.Module, imports: ImportIndex) -> _ResponseCallables:
    module_declarations: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_declarations.setdefault(statement.name, []).append(statement)
    response_functions = frozenset(
        name
        for name, functions in module_declarations.items()
        if all(_returns_http_response(function, imports) for function in functions)
    )

    response_methods: set[tuple[int, str]] = set()
    function_owners: dict[int, int] = {}
    for class_node in nodes(tree, ast.ClassDef):
        owner = id(class_node)
        declarations: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        for statement in class_node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_owners[id(statement)] = owner
                declarations.setdefault(statement.name, []).append(statement)
        response_methods.update(
            (owner, name)
            for name, functions in declarations.items()
            if all(_returns_http_response(function, imports) for function in functions)
        )
    return _ResponseCallables(response_functions, frozenset(response_methods), function_owners)


def _returns_http_response(function: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    return function.returns is not None and imports.resolves(function.returns, sources=_HTTP_MODULES, symbol="Response")


def _http_client_attribute_names(tree: ast.Module, imports: ImportIndex) -> frozenset[_OwnedName]:
    owned_attributes: set[_OwnedName] = set()
    for class_node in nodes(tree, ast.ClassDef):
        assignments: dict[str, list[bool]] = {}
        for function in class_node.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            typed_parameters = {
                argument.arg
                for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
                if argument.annotation is not None
                and any(
                    imports.resolves(argument.annotation, sources=_HTTP_MODULES, symbol=symbol)
                    for symbol in _HTTP_CLIENT_TYPES
                )
            }
            for node in _own_scope(function):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        assignments.setdefault(target.attr, []).append(
                            isinstance(node.value, ast.Name) and node.value.id in typed_parameters
                        )
        owner = id(class_node)
        owned_attributes.update(
            _OwnedName(owner, name) for name, values in assignments.items() if values and all(values)
        )
    return frozenset(owned_attributes)


def _locally_sourced_parameters(
    functions: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...],
) -> dict[str, frozenset[int]]:
    calls: dict[str, list[ast.Call]] = {}
    for owner in functions:
        for node in _own_scope(owner):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.setdefault(node.func.id, []).append(node)
    local: dict[str, frozenset[int]] = {}
    for function in functions:
        callsites = calls.get(function.name, [])
        if not callsites:
            continue
        positions = {
            position
            for position in range(len(_parameter_positions(function)))
            if all(position < len(call.args) and _is_local_json_text(call.args[position]) for call in callsites)
        }
        if positions:
            local[function.name] = frozenset(positions)
    return local


def _decoded_parameter_position(
    value: ast.expr,
    parameters: dict[str, int],
    imports: ImportIndex,
) -> int | None:
    value = _unwrap_await(value)
    if not isinstance(value, ast.Call) or not _is_json_loads(value, imports) or not value.args:
        return None
    argument = value.args[0]
    return parameters.get(argument.id) if isinstance(argument, ast.Name) else None


def _parameter_positions(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    arguments = (*function.args.posonlyargs, *function.args.args)
    return {argument.arg: position for position, argument in enumerate(arguments)}


def _function_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    summaries: _ModuleSummaries,
) -> list[_ExternalRecordFinding]:
    scope = _own_scope(function)
    local_positions = summaries.local_parameters.get(function.name, frozenset())
    parameters = frozenset(
        name for name, position in _parameter_positions(function).items() if position not in local_positions
    )
    outbound_requests = _outbound_request_parameters(function, imports)
    response_names = _http_response_names(scope, imports, summaries, function)
    bindings = _unique_bindings(scope)
    resolver = _OriginResolver(imports, summaries, parameters, outbound_requests, response_names, bindings)
    findings: list[_ExternalRecordFinding] = []
    for node in scope:
        access = _record_access(node)
        if access is not None:
            findings.extend(_ExternalRecordFinding(access.sink, origin) for origin in resolver.origins(access.receiver))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            for position in summaries.record_parameters.get(node.func.id, frozenset()):
                if position < len(node.args):
                    findings.extend(
                        _ExternalRecordFinding(node, origin) for origin in resolver.origins(node.args[position])
                    )
    return findings


@dataclass(slots=True)
class _OriginResolver:
    imports: ImportIndex
    summaries: _ModuleSummaries
    parameters: frozenset[str]
    outbound_request_parameters: frozenset[str]
    response_names: frozenset[str]
    bindings: dict[str, ast.expr]

    def origins(self, expression: ast.expr, resolving: frozenset[str] = frozenset()) -> frozenset[ast.Call]:
        expression = _unwrap_await(expression)
        if isinstance(expression, ast.Name):
            if expression.id in resolving or (value := self.bindings.get(expression.id)) is None:
                return frozenset()
            return self.origins(value, resolving | {expression.id})
        if isinstance(expression, ast.Call):
            if _is_validation_call(expression, self.imports) or _is_model_unpack_validation(expression):
                return frozenset()
            if self._is_source(expression):
                return frozenset({expression})
            found_origins: set[ast.Call] = set()
            if (
                isinstance(expression.func, ast.Name)
                and (position := self.summaries.decoder_parameters.get(expression.func.id)) is not None
                and position < len(expression.args)
                and self._is_external_input(expression.args[position])
            ):
                found_origins.add(expression)
            for argument in expression.args:
                found_origins.update(self.origins(argument, resolving))
            for keyword in expression.keywords:
                found_origins.update(self.origins(keyword.value, resolving))
            return frozenset(found_origins)
        found_origins = set()
        for child in ast.iter_child_nodes(expression):
            if isinstance(child, ast.expr):
                found_origins.update(self.origins(child, resolving))
        return frozenset(found_origins)

    def _is_source(self, call: ast.Call) -> bool:
        if _is_json_loads(call, self.imports) and call.args:
            return self._is_external_input(call.args[0])
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "json"
            and not call.args
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in self.response_names
        )

    def _is_external_input(self, expression: ast.expr) -> bool:
        expression = _unwrap_await(expression)
        match expression:
            case ast.Name(id=name):
                return name in self.parameters
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute) if owner in self.outbound_request_parameters:
                return False
            case ast.Attribute(attr=attribute):
                return attribute in {"content", "stderr", "stdout", "text"}
            case ast.Subscript(value=value):
                return _dotted_name(value) in {"environ", "os.environ"}
            case _:
                return not _is_local_json_text(expression)


def _record_access(node: ast.AST) -> _RecordAccess | None:
    if isinstance(node, ast.Subscript) and _literal_string(node.slice) is not None:
        return _RecordAccess(node, node.value)
    if isinstance(node, ast.Call) and (receiver := _fixed_record_call_receiver(node)) is not None:
        return _RecordAccess(node, receiver)
    return None


def _fixed_record_call_receiver(node: ast.Call) -> ast.expr | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in _RECORD_METHODS:
        return None
    if node.func.attr == "get" and not (node.args and _literal_string(node.args[0]) is not None):
        return None
    return node.func.value


def _summary_record_receiver(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Subscript):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _RECORD_METHODS:
        return node.func.value
    return None


def _unique_bindings(scope: tuple[ast.AST, ...]) -> dict[str, ast.expr]:
    candidates: dict[str, list[ast.expr]] = {}
    for node in scope:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    candidates.setdefault(target.id, []).append(node.value)
        elif (binding := _single_named_binding(node)) is not None:
            candidates.setdefault(binding.name, []).append(binding.value)
    return {name: values[0] for name, values in candidates.items() if len(values) == 1}


def _single_named_binding(node: ast.AST) -> _NamedBinding | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return _NamedBinding(node.target.id, node.value)
    if isinstance(node, ast.NamedExpr):
        return _NamedBinding(node.target.id, node.value)
    return None


def _http_response_names(
    scope: tuple[ast.AST, ...],
    imports: ImportIndex,
    summaries: _ModuleSummaries,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    names: set[str] = set()
    typed_clients = {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if argument.annotation is not None
        and any(
            imports.resolves(argument.annotation, sources=_HTTP_MODULES, symbol=symbol) for symbol in _HTTP_CLIENT_TYPES
        )
    }
    for node in scope:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        call = _unwrap_await(node.value)
        if not isinstance(call, ast.Call) or not _is_http_response_call(
            call,
            imports,
            summaries,
            typed_clients,
            function,
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return frozenset(names)


def _is_http_response_call(
    call: ast.Call,
    imports: ImportIndex,
    summaries: _ModuleSummaries,
    typed_clients: set[str],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if any(imports.resolves(call.func, sources=_HTTP_MODULES, symbol=method) for method in _HTTP_METHODS):
        return True
    if isinstance(call.func, ast.Name):
        return call.func.id in summaries.response_functions
    if not isinstance(call.func, ast.Attribute):
        return False
    owner = summaries.function_owners.get(id(function))
    if (
        owner is not None
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and (owner, call.func.attr) in summaries.response_methods
    ):
        return True
    if call.func.attr not in (_HTTP_METHODS | {"send"}):
        return False
    receiver = call.func.value
    if isinstance(receiver, ast.Name):
        return receiver.id in typed_clients
    return (
        isinstance(receiver, ast.Attribute)
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id == "self"
        and owner is not None
        and (owner, receiver.attr) in summaries.http_client_attributes
    )


def _outbound_request_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex
) -> frozenset[str]:
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    return frozenset(
        argument.arg
        for argument in arguments
        if argument.annotation is not None
        and imports.resolves(argument.annotation, sources=_HTTP_MODULES, symbol="Request")
    )


def _is_json_loads(call: ast.Call, imports: ImportIndex) -> bool:
    return imports.resolves(call.func, sources=_JSON_MODULES, symbol="loads")


def _is_validation_call(call: ast.Call, imports: ImportIndex) -> bool:
    if isinstance(call.func, ast.Attribute) and call.func.attr in (_OBJECT_VALIDATORS | _ADAPTER_VALIDATORS):
        return True
    return imports.resolves(call.func, sources=frozenset({"pydantic"}), symbol="parse_obj_as")


def _is_model_unpack_validation(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id[:1].isupper()
        and any(keyword.arg is None for keyword in call.keywords)
    )


def _is_local_json_text(expression: ast.expr) -> bool:
    expression = _unwrap_await(expression)
    if isinstance(expression, ast.Constant) and isinstance(expression.value, (str, bytes)):
        return True
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr in _LOCAL_READ_METHODS
    )


def _dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return ".".join((current.id, *reversed(parts)))


def _literal_string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _unwrap_await(node: ast.expr) -> ast.expr:
    return node.value if isinstance(node, ast.Await) else node


def _excluded(path: Path, source: str) -> bool:
    return (
        is_test_path(path)
        or is_test_support_path(path)
        or is_generated(path, source)
        or any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)
    )


def _own_scope(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.AST, ...]:
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(reversed(function.body))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return tuple(out)
