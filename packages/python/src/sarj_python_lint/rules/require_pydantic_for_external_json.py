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
    is_suppressed,
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
_ADAPTER_VALIDATORS = frozenset({"validate_python"})
_RECORD_METHODS = frozenset({"get"})
_LOCAL_READ_METHODS = frozenset({"read_bytes", "read_text"})
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src", "examples"})
_SCHEMA_VALIDATOR_MODULES = frozenset({"jsonschema"})
_SUBPROCESS_MODULES = frozenset({"subprocess"})
_PYDANTIC_MODULES = frozenset({"pydantic"})
_MARSHMALLOW_MODULES = frozenset({"marshmallow", "marshmallow.schema"})


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
    marshmallow_schema_names: frozenset[str]
    marshmallow_schema_instances: frozenset[str]
    jsonschema_validator_names: frozenset[str]
    pydantic_adapter_names: frozenset[str]
    pydantic_model_names: frozenset[str]


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
        summary="Proven external JSON record fields are consumed before runtime schema validation.",
        rationale=(
            "Annotations, casts, and partial key checks do not validate a wire protocol; a maintained runtime "
            "schema makes required fields, types, and protocol versions explicit at the boundary."
        ),
        remediation=(
            "Validate raw JSON with `Model.model_validate_json(...)` or `TypeAdapter(Model).validate_json(...)`; "
            "for an already-decoded response, use `model_validate`, `validate_python`, or another maintained "
            "runtime schema validator before reading fields."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule follows import-proven JSON decoders, HTTP responses and clients, environment or subprocess results, and simple module-local helpers through single-assignment names.",
            "It diagnoses literal-key subscription and get calls; iteration and other dynamic JSON use remain out of scope.",
            "Unannotated parameters and unknown expressions are not assumed to be external; interprocedural and framework-specific boundaries can remain unreported.",
            "Functions with complex local binders are skipped rather than guessing which value a name denotes.",
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
                        "import httpx\n\ndef fetch() -> object:\n    report = httpx.get('https://api.example/report').json()\n    return report.get('version')\n",
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
                        "import httpx\nfrom pydantic import BaseModel\n\nclass Report(BaseModel):\n    version: int\n\ndef fetch() -> Report:\n    raw = httpx.get('https://api.example/report').json()\n    report = Report.model_validate(raw)\n    return report\n",
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
        source_lines = source.splitlines()
        summaries = _module_summaries(tree, imports, source_lines)
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
                    "Proven external JSON field is read before runtime schema validation — validate raw input "
                    "with `model_validate_json`/`validate_json`, or validate this decoded object with "
                    "`model_validate`/`validate_python` first."
                ),
                severity=Severity.WARNING,
            )
            for sink, _origin in first_by_origin.values()
            if not is_suppressed(source_lines, sink.lineno, self.code)
        ]


def _functions(tree: ast.Module) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _module_summaries(tree: ast.Module, imports: ImportIndex, source_lines: list[str]) -> _ModuleSummaries:
    binding_counts = _suite_binding_counts(tree.body)
    schema_names = _marshmallow_schema_names(tree, imports, binding_counts)
    module_validator_names = _jsonschema_validator_names_from_statements(
        tree.body, imports, binding_counts=binding_counts
    )
    rebound_names = _module_rebound_names(tree)
    functions = tuple(
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name not in rebound_names
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
        validated_names = _validated_names(function, imports, module_validator_names)
        for node in _own_scope(function):
            receiver = _summary_record_receiver(node)
            if (
                isinstance(receiver, ast.Name)
                and receiver.id in parameters
                and isinstance(node, ast.expr)
                and not _was_validated_before(receiver, node, validated_names)
                and not is_suppressed(source_lines, node.lineno, "SARJ411")
            ):
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
        schema_names,
        _marshmallow_schema_instances(tree, imports, schema_names, binding_counts),
        module_validator_names,
        _pydantic_adapter_names(tree, imports, binding_counts),
        _pydantic_model_names(tree, imports, binding_counts),
    )


def _response_callables(tree: ast.Module, imports: ImportIndex) -> _ResponseCallables:
    rebound_names = _module_rebound_names(tree)
    module_declarations: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_declarations.setdefault(statement.name, []).append(statement)
    response_functions = frozenset(
        name
        for name, functions in module_declarations.items()
        if name not in rebound_names and all(_returns_http_response(function, imports) for function in functions)
    )

    response_methods: set[tuple[int, str]] = set()
    function_owners: dict[int, int] = {}
    for class_node in nodes(tree, ast.ClassDef):
        owner = id(class_node)
        rebound_method_names = _suite_rebound_names(class_node.body)
        declarations: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        for statement in class_node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_owners[id(statement)] = owner
                declarations.setdefault(statement.name, []).append(statement)
        response_methods.update(
            (owner, name)
            for name, functions in declarations.items()
            if name not in rebound_method_names
            and all(_returns_http_response(function, imports) for function in functions)
        )
    return _ResponseCallables(response_functions, frozenset(response_methods), function_owners)


def _module_rebound_names(tree: ast.Module) -> frozenset[str]:
    return _suite_rebound_names(tree.body)


def _suite_rebound_names(statements: list[ast.stmt]) -> frozenset[str]:
    names: set[str] = set()
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(statement, ast.ClassDef):
            names.add(statement.name)
        elif isinstance(statement, ast.Import | ast.ImportFrom):
            names.update(alias.asname or alias.name.partition(".")[0] for alias in statement.names)
        else:
            names.update(
                node.id
                for node in ast.walk(statement)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            )
    return frozenset(names)


def _marshmallow_schema_names(tree: ast.Module, imports: ImportIndex, binding_counts: Counter[str]) -> frozenset[str]:
    classes = tuple(node for node in tree.body if isinstance(node, ast.ClassDef))
    names = {
        node.name
        for node in classes
        if binding_counts[node.name] == 1
        if not node.decorator_list
        if not _class_overrides(node, frozenset({"load"}))
        if any(imports.resolves(base, sources=_MARSHMALLOW_MODULES, symbol="Schema") for base in node.bases)
    }
    for _round in range(len(classes)):
        inherited = {
            node.name
            for node in classes
            if binding_counts[node.name] == 1
            if not node.decorator_list
            if not _class_overrides(node, frozenset({"load"}))
            if any(isinstance(base, ast.Name) and base.id in names for base in node.bases)
        }
        if inherited <= names:
            break
        names.update(inherited)
    return _expand_unique_aliases(names, _suite_unique_bindings(tree.body), binding_counts)


def _pydantic_adapter_names(tree: ast.Module, imports: ImportIndex, binding_counts: Counter[str]) -> frozenset[str]:
    names = {
        name
        for name, value in _suite_unique_bindings(tree.body).items()
        if binding_counts[name] == 1
        and isinstance(value, ast.Call)
        and imports.resolves(value.func, sources=_PYDANTIC_MODULES, symbol="TypeAdapter")
    }
    return _expand_unique_aliases(names, _suite_unique_bindings(tree.body), binding_counts)


def _marshmallow_schema_instances(
    tree: ast.Module,
    imports: ImportIndex,
    schema_names: frozenset[str],
    binding_counts: Counter[str],
) -> frozenset[str]:
    return frozenset(
        name
        for name, value in _suite_unique_bindings(tree.body).items()
        if binding_counts[name] == 1
        if isinstance(value, ast.Call)
        and _is_marshmallow_schema_constructor(value, imports, schema_names, shadowed_names=frozenset())
    )


def _suite_unique_bindings(statements: list[ast.stmt]) -> dict[str, ast.expr]:
    candidates: dict[str, list[ast.expr]] = {}
    for statement in statements:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    candidates.setdefault(target.id, []).append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
            candidates.setdefault(statement.target.id, []).append(statement.value)
    return {name: values[0] for name, values in candidates.items() if len(values) == 1}


def _expand_unique_aliases(
    roots: set[str], bindings: dict[str, ast.expr], binding_counts: Counter[str]
) -> frozenset[str]:
    names = set(roots)
    for _round in range(len(bindings)):
        aliases = {
            name
            for name, value in bindings.items()
            if binding_counts[name] == 1 and isinstance(value, ast.Name) and value.id in names
        }
        if aliases <= names:
            break
        names.update(aliases)
    return frozenset(names)


def _jsonschema_validator_names_from_statements(
    statements: list[ast.stmt],
    imports: ImportIndex,
    inherited: frozenset[str] = frozenset(),
    *,
    binding_counts: Counter[str] | None = None,
) -> frozenset[str]:
    binding_counts = binding_counts or _suite_binding_counts(statements)
    bindings = _suite_unique_bindings(statements)
    names = {
        name
        for name, value in bindings.items()
        if binding_counts[name] == 1 and _is_jsonschema_validator_constructor(value, imports)
    }
    available = {name for name in inherited if binding_counts[name] == 0} | names
    for _round in range(len(bindings)):
        aliases = {
            name
            for name, value in bindings.items()
            if binding_counts[name] == 1 and isinstance(value, ast.Name) and value.id in available
        }
        if aliases <= available:
            break
        available.update(aliases)
    return frozenset(available)


def _is_jsonschema_validator_constructor(value: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(value, ast.Call):
        return False
    symbol = imports.resolved_symbol(value.func, sources=_SCHEMA_VALIDATOR_MODULES)
    return (
        symbol is not None
        and symbol.endswith("Validator")
        and imports.resolves(value.func, sources=_SCHEMA_VALIDATOR_MODULES, symbol=symbol)
    )


def _pydantic_model_names(tree: ast.Module, imports: ImportIndex, binding_counts: Counter[str]) -> frozenset[str]:
    classes = tuple(node for node in tree.body if isinstance(node, ast.ClassDef))
    names = {
        node.name
        for node in classes
        if binding_counts[node.name] == 1
        if not node.decorator_list
        if not _class_overrides(node, frozenset({"model_validate", "parse_obj"}))
        if any(
            imports.resolves(base, sources=_PYDANTIC_MODULES, symbol=model)
            for base in node.bases
            for model in ("BaseModel", "RootModel")
        )
    }
    for _round in range(len(classes)):
        inherited = {
            node.name
            for node in classes
            if binding_counts[node.name] == 1
            if not node.decorator_list
            if not _class_overrides(node, frozenset({"model_validate", "parse_obj"}))
            if any(isinstance(base, ast.Name) and base.id in names for base in node.bases)
        }
        if inherited <= names:
            break
        names.update(inherited)
    return _expand_unique_aliases(names, _suite_unique_bindings(tree.body), binding_counts)


def _class_overrides(node: ast.ClassDef, method_names: frozenset[str]) -> bool:
    binding_counts = _suite_binding_counts(node.body)
    return any(binding_counts[name] for name in method_names)


def _suite_binding_counts(statements: list[ast.stmt]) -> Counter[str]:
    counts: Counter[str] = Counter()
    stack: list[ast.AST] = list(reversed(statements))
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                counts[node.name] += 1
                stack.extend(reversed([*node.decorator_list, node.args, *node.type_params]))
                if node.returns is not None:
                    stack.append(node.returns)
                continue
            case ast.ClassDef():
                counts[node.name] += 1
                stack.extend(
                    reversed(
                        [
                            *node.decorator_list,
                            *node.bases,
                            *(keyword.value for keyword in node.keywords),
                            *node.type_params,
                        ]
                    )
                )
                continue
            case ast.Lambda():
                stack.append(node.args)
                continue
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                continue
            case ast.Import() | ast.ImportFrom():
                counts.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
            ):
                counts[name] += 1
            case _:
                pass
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return counts


def _type_parameter_names(parameters: list[ast.type_param]) -> tuple[str, ...]:
    names: list[str] = []
    for parameter in parameters:
        match parameter:
            case ast.TypeVar(name=name) | ast.ParamSpec(name=name) | ast.TypeVarTuple(name=name):
                names.append(name)
            case _:
                pass
    return tuple(names)


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
    if _has_complex_binders(scope):
        return []
    parameters: frozenset[str] = frozenset()
    outbound_requests = _outbound_request_parameters(function, imports)
    bindings = _unique_bindings(scope)
    local_bound_names = _function_local_bound_names(function, scope)
    response_names = _http_response_names(scope, imports, summaries, function, shadowed_names=local_bound_names)
    resolver = _OriginResolver(
        imports,
        summaries,
        parameters,
        outbound_requests,
        response_names,
        bindings,
        local_bound_names,
    )
    validated_names = _validated_names(function, imports, summaries.jsonschema_validator_names)
    findings: list[_ExternalRecordFinding] = []
    for node in scope:
        access = _record_access(node)
        if access is not None and not _was_validated_before(access.receiver, access.sink, validated_names):
            findings.extend(_ExternalRecordFinding(access.sink, origin) for origin in resolver.origins(access.receiver))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in local_bound_names:
            for position in summaries.record_parameters.get(node.func.id, frozenset()):
                if position < len(node.args):
                    findings.extend(
                        _ExternalRecordFinding(node, origin) for origin in resolver.origins(node.args[position])
                    )
    return findings


def _has_complex_binders(scope: tuple[ast.AST, ...]) -> bool:
    return any(
        isinstance(
            node,
            (
                ast.NamedExpr,
                ast.For,
                ast.AsyncFor,
                ast.comprehension,
                ast.With,
                ast.AsyncWith,
                ast.ExceptHandler,
                ast.Match,
                ast.Import,
                ast.ImportFrom,
            ),
        )
        or (isinstance(node, ast.Tuple | ast.List) and isinstance(node.ctx, ast.Store))
        for node in scope
    )


def _function_local_bound_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef, scope: tuple[ast.AST, ...]
) -> frozenset[str]:
    names = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    names.update(_type_parameter_names(function.type_params))
    for node in scope:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.add(node.name)
    return frozenset(names)


_Position = tuple[int, int]
_ValidationHistory = dict[str, tuple[tuple[_Position, bool], ...]]


def _validated_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    module_validator_names: frozenset[str] = frozenset(),
) -> _ValidationHistory:
    validation_calls: list[ast.Call] = []
    for statement in function.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if imports.resolves(call.func, sources=_SCHEMA_VALIDATOR_MODULES, symbol="validate") or (
            isinstance(call.func, ast.Attribute) and call.func.attr == "validate"
        ):
            validation_calls.append(call)
    if not validation_calls:
        return {}
    histories: dict[str, list[tuple[_Position, bool]]] = {}
    tokens: dict[str, object] = {}
    validated_tokens: set[object] = set()
    validator_names = _jsonschema_validator_names(function, imports, module_validator_names)
    for statement in function.body:
        position = _node_position(statement)
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Name)
        ):
            alias = statement.targets[0].id
            token = tokens.setdefault(statement.value.id, object())
            tokens[alias] = token
            histories.setdefault(alias, []).append((position, token in validated_tokens))
            continue
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and isinstance(statement.value, ast.Name)
        ):
            alias = statement.target.id
            token = tokens.setdefault(statement.value.id, object())
            tokens[alias] = token
            histories.setdefault(alias, []).append((position, token in validated_tokens))
            continue
        for name in _statement_bound_names(statement):
            tokens[name] = object()
            histories.setdefault(name, []).append((position, False))
        if (
            not isinstance(statement, ast.Expr)
            or not isinstance(statement.value, ast.Call)
            or statement.value not in validation_calls
        ):
            continue
        call = statement.value
        is_module_validator = imports.resolves(call.func, sources=_SCHEMA_VALIDATOR_MODULES, symbol="validate")
        is_instance_validator = (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "validate"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in validator_names
        )
        if not is_module_validator and not is_instance_validator:
            continue
        candidates = [*call.args[:1], *(keyword.value for keyword in call.keywords if keyword.arg == "instance")]
        for argument in candidates:
            if isinstance(argument, ast.Name):
                token = tokens.setdefault(argument.id, object())
                validated_tokens.add(token)
                for name, current_token in tokens.items():
                    if current_token is token:
                        histories.setdefault(name, []).append((_node_position(call), True))
    return {name: tuple(events) for name, events in histories.items()}


def _statement_bound_names(statement: ast.stmt) -> frozenset[str]:
    match statement:
        case ast.Assign(targets=assignment_targets):
            targets: tuple[ast.expr, ...] = tuple(assignment_targets)
        case ast.AnnAssign(target=target) | ast.AugAssign(target=target):
            targets = (target,)
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            return frozenset({name})
        case _:
            return frozenset()
    return frozenset(target.id for target in targets if isinstance(target, ast.Name))


def _node_position(node: ast.expr | ast.stmt) -> _Position:
    return node.lineno, node.col_offset


def _jsonschema_validator_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    module_validator_names: frozenset[str],
) -> frozenset[str]:
    binding_counts = _suite_binding_counts(function.body)
    parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    parameter_names = {argument.arg for argument in parameters}
    if function.args.vararg is not None:
        parameter_names.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        parameter_names.add(function.args.kwarg.arg)
    parameter_names.update(_type_parameter_names(function.type_params))
    names = set(_jsonschema_validator_names_from_statements(function.body, imports, module_validator_names))
    names.difference_update(parameter_names)
    names.update(
        {
            argument.arg
            for argument in parameters
            if argument.annotation is not None
            and imports.resolves(argument.annotation, sources=frozenset({"jsonschema.protocols"}), symbol="Validator")
            and binding_counts[argument.arg] == 0
        }
    )
    return frozenset(names)


def _was_validated_before(receiver: ast.expr, sink: ast.expr, validated_names: _ValidationHistory) -> bool:
    if not isinstance(receiver, ast.Name):
        return False
    prior_events = tuple(
        validated for position, validated in validated_names.get(receiver.id, ()) if position < _node_position(sink)
    )
    return bool(prior_events and prior_events[-1])


@dataclass(slots=True)
class _OriginResolver:
    imports: ImportIndex
    summaries: _ModuleSummaries
    parameters: frozenset[str]
    outbound_request_parameters: frozenset[str]
    response_names: frozenset[str]
    bindings: dict[str, ast.expr]
    local_bound_names: frozenset[str]

    def origins(self, expression: ast.expr, resolving: frozenset[str] = frozenset()) -> frozenset[ast.Call]:
        expression = _unwrap_await(expression)
        if isinstance(expression, ast.Name):
            if expression.id in resolving or (value := self.bindings.get(expression.id)) is None:
                return frozenset()
            return self.origins(value, resolving | {expression.id})
        if isinstance(expression, ast.Call):
            if self._is_validation_call(expression):
                return frozenset()
            if self._is_source(expression):
                return frozenset({expression})
            found_origins: set[ast.Call] = set()
            if (
                isinstance(expression.func, ast.Name)
                and expression.func.id not in self.local_bound_names
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

    def _is_validation_call(self, call: ast.Call) -> bool:
        if _is_validation_call(
            call,
            self.imports,
            marshmallow_schema_names=self.summaries.marshmallow_schema_names,
            pydantic_adapter_names=self.summaries.pydantic_adapter_names,
            pydantic_model_names=self.summaries.pydantic_model_names,
            marshmallow_schema_instances=self.summaries.marshmallow_schema_instances,
            shadowed_names=self.local_bound_names,
        ):
            return True
        if not isinstance(call.func, ast.Attribute):
            return False
        receiver = call.func.value
        if not isinstance(receiver, ast.Name):
            return False
        value = self._resolved_binding(receiver)
        if call.func.attr in _ADAPTER_VALIDATORS:
            return (
                isinstance(value, ast.Call)
                and self.imports.resolves(value.func, sources=_PYDANTIC_MODULES, symbol="TypeAdapter")
            ) or (
                isinstance(value, ast.Name)
                and value.id not in self.local_bound_names
                and value.id in self.summaries.pydantic_adapter_names
            )
        if call.func.attr == "load":
            return (
                isinstance(value, ast.Call)
                and _is_marshmallow_schema_constructor(
                    value,
                    self.imports,
                    self.summaries.marshmallow_schema_names,
                    shadowed_names=self.local_bound_names,
                )
            ) or (
                isinstance(value, ast.Name)
                and value.id not in self.local_bound_names
                and value.id in self.summaries.marshmallow_schema_instances
            )
        if call.func.attr in {"model_validate", "parse_obj"} and isinstance(value, ast.Name):
            return value.id not in self.local_bound_names and value.id in self.summaries.pydantic_model_names
        return False

    def _resolved_binding(self, name: ast.Name) -> ast.expr:
        current: ast.expr = name
        seen: set[str] = set()
        while isinstance(current, ast.Name) and current.id not in seen:
            seen.add(current.id)
            value = self.bindings.get(current.id)
            if value is None:
                break
            current = value
        return current

    def _is_source(self, call: ast.Call) -> bool:
        if _is_json_loads(call, self.imports) and call.args:
            return self._is_external_input(call.args[0])
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "json" or call.args:
            return False
        receiver = _unwrap_await(call.func.value)
        if isinstance(receiver, ast.Name):
            return receiver.id in self.response_names
        return isinstance(receiver, ast.Call) and any(
            self.imports.resolves(receiver.func, sources=_HTTP_MODULES, symbol=method) for method in _HTTP_METHODS
        )

    def _is_external_input(self, expression: ast.expr) -> bool:
        expression = _unwrap_await(expression)
        match expression:
            case ast.Name(id=name):
                return name in self.parameters
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute) if owner in self.outbound_request_parameters:
                return False
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute) if (
                attribute in {"content", "text"} and owner in self.response_names
            ):
                return True
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute) if attribute in {"stderr", "stdout"}:
                value = self.bindings.get(owner)
                value = _unwrap_await(value) if value is not None else None
                return isinstance(value, ast.Call) and _is_subprocess_run(value, self.imports)
            case ast.Attribute(value=ast.Call() as call, attr=attribute) if attribute in {"stderr", "stdout"}:
                return _is_subprocess_run(call, self.imports)
            case ast.Subscript(value=value):
                return self.imports.resolves(value, sources=frozenset({"os"}), symbol="environ")
            case ast.Call() as call:
                if _is_subprocess_output_call(call, self.imports):
                    return True
                return (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "decode"
                    and self._is_external_input(call.func.value)
                )
            case _:
                return False


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
    *,
    shadowed_names: frozenset[str],
) -> frozenset[str]:
    bindings = _unique_bindings(scope)
    assigned_names = {
        target.id
        for node in scope
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else (node.target,))
        if isinstance(target, ast.Name)
    }
    names = {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if argument.annotation is not None
        and argument.arg not in assigned_names
        and imports.resolves(argument.annotation, sources=_HTTP_MODULES, symbol="Response")
    }
    typed_clients = {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if argument.annotation is not None
        and argument.arg not in assigned_names
        and any(
            imports.resolves(argument.annotation, sources=_HTTP_MODULES, symbol=symbol) for symbol in _HTTP_CLIENT_TYPES
        )
    }
    for name, value in bindings.items():
        call = _unwrap_await(value)
        if not isinstance(call, ast.Call) or not _is_http_response_call(
            call,
            imports,
            summaries,
            typed_clients,
            function,
            shadowed_names=shadowed_names,
        ):
            continue
        names.add(name)
    for _round in range(len(scope)):
        aliases = {name for name, value in bindings.items() if isinstance(value, ast.Name) and value.id in names}
        if aliases <= names:
            break
        names.update(aliases)
    return frozenset(names)


def _is_http_response_call(
    call: ast.Call,
    imports: ImportIndex,
    summaries: _ModuleSummaries,
    typed_clients: set[str],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    shadowed_names: frozenset[str] = frozenset(),
) -> bool:
    if any(imports.resolves(call.func, sources=_HTTP_MODULES, symbol=method) for method in _HTTP_METHODS):
        return True
    if isinstance(call.func, ast.Name):
        return call.func.id not in shadowed_names and call.func.id in summaries.response_functions
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


def _is_validation_call(
    call: ast.Call,
    imports: ImportIndex,
    *,
    marshmallow_schema_names: frozenset[str] = frozenset(),
    pydantic_adapter_names: frozenset[str] = frozenset(),
    pydantic_model_names: frozenset[str] = frozenset(),
    marshmallow_schema_instances: frozenset[str] = frozenset(),
    shadowed_names: frozenset[str] = frozenset(),
) -> bool:
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "load"
        and isinstance(call.func.value, ast.Call)
        and _is_marshmallow_schema_constructor(
            call.func.value, imports, marshmallow_schema_names, shadowed_names=shadowed_names
        )
    ):
        return True
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "load"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id not in shadowed_names
        and call.func.value.id in marshmallow_schema_instances
    ):
        return True
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in _ADAPTER_VALIDATORS
        and isinstance(call.func.value, ast.Call)
        and imports.resolves(call.func.value.func, sources=_PYDANTIC_MODULES, symbol="TypeAdapter")
    ):
        return True
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in _ADAPTER_VALIDATORS
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id not in shadowed_names
        and call.func.value.id in pydantic_adapter_names
    ):
        return True
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"model_validate", "parse_obj"}
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id not in shadowed_names
        and call.func.value.id in pydantic_model_names
    ):
        return True
    return imports.resolves(call.func, sources=_PYDANTIC_MODULES, symbol="parse_obj_as") or imports.resolves(
        call.func, sources=_SCHEMA_VALIDATOR_MODULES, symbol="validate"
    )


def _is_marshmallow_schema_constructor(
    call: ast.Call,
    imports: ImportIndex,
    schema_names: frozenset[str],
    *,
    shadowed_names: frozenset[str],
) -> bool:
    if imports.resolves(call.func, sources=_MARSHMALLOW_MODULES, symbol="Schema"):
        return True
    return isinstance(call.func, ast.Name) and call.func.id not in shadowed_names and call.func.id in schema_names


def _is_subprocess_run(call: ast.Call, imports: ImportIndex) -> bool:
    return imports.resolves(call.func, sources=_SUBPROCESS_MODULES, symbol="run")


def _is_subprocess_output_call(call: ast.Call, imports: ImportIndex) -> bool:
    return imports.resolves(call.func, sources=_SUBPROCESS_MODULES, symbol="check_output")


def _is_local_json_text(expression: ast.expr) -> bool:
    expression = _unwrap_await(expression)
    if isinstance(expression, ast.Constant) and isinstance(expression.value, (str, bytes)):
        return True
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr in _LOCAL_READ_METHODS
    )


def _literal_string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _expression_tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


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
