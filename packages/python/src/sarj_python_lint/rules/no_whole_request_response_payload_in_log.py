from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
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
_MUTATING_METHODS = frozenset(
    {"append", "clear", "extend", "insert", "pop", "popitem", "remove", "reverse", "setdefault", "sort", "update"}
)


_Position = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Binding:
    value: ast.expr
    position: _Position


@dataclass(frozen=True, slots=True)
class _SuiteFacts:
    bindings: dict[str, _Binding]
    statement_positions: dict[int, int]


@dataclass(frozen=True, slots=True)
class _AnalysisFacts:
    suites: dict[int, _SuiteFacts]
    statement_suites: dict[int, int]
    parents: dict[int, ast.AST]


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


def _logging_payloads(node: ast.Call, facts: _SuiteFacts | None, *, statement_index: int) -> list[ast.expr]:
    sink_position = statement_index, node.col_offset
    values: list[ast.expr] = []
    for argument in node.args:
        values.extend(_resolved_payloads(argument, facts, sink_position=sink_position))
    for keyword in node.keywords:
        values.extend(_resolved_keyword_payloads(keyword, facts, sink_position=sink_position))
    return list({(value.lineno, value.col_offset): value for value in values}.values())


@final
class NoWholeRequestResponsePayloadInLog(Rule):
    id: str = "no-whole-request-response-payload-in-log"
    code: str = "SARJ436"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
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
            "Detection follows direct request/response body, content, data, JSON, payload, and text references through stable same-block aliases, interpolation, and immutable literal logging mappings.",
            "Generic request or response objects, unrelated body/payload values, explicitly sanitized summaries, mutated or branch-dependent aliases, dynamic containers, and interprocedural flows are excluded.",
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
        facts = _analysis_facts(tree)
        diagnostics: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            if not _is_logging_call(node):
                continue
            statement = _containing_statement(node, facts.parents)
            suite_id = facts.statement_suites.get(id(statement)) if statement is not None else None
            suite = facts.suites.get(suite_id) if suite_id is not None else None
            statement_index = suite.statement_positions.get(id(statement), -1) if suite is not None else -1
            values = _logging_payloads(node, suite, statement_index=statement_index)
            diagnostics.extend(_diagnostic(path, value) for value in values)
        return diagnostics


def _is_logging_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS and is_logger_expr(node.func.value)


def _resolved_keyword_payloads(
    keyword: ast.keyword,
    facts: _SuiteFacts | None,
    *,
    sink_position: _Position,
) -> tuple[ast.expr, ...]:
    if keyword.arg is None or keyword.arg == "extra":
        return _resolved_payloads(keyword.value, facts, sink_position=sink_position, mapping_only=True)
    return _resolved_payloads(keyword.value, facts, sink_position=sink_position, label=keyword.arg)


def _resolved_payloads(
    value: ast.expr,
    facts: _SuiteFacts | None,
    *,
    sink_position: _Position,
    label: str | None = None,
    mapping_only: bool = False,
    resolving: frozenset[str] = frozenset(),
) -> tuple[ast.expr, ...]:
    if _is_safe_transform(value) or _is_secret_reference(value):
        return ()
    alias = _resolved_alias(value, facts, sink_position=sink_position, resolving=resolving)
    if alias is not None:
        alias_name, alias_value = alias
        return _resolved_payloads(
            alias_value,
            facts,
            sink_position=sink_position,
            label=label,
            mapping_only=mapping_only,
            resolving=resolving | {alias_name},
        )
    if not mapping_only and _is_payload_reference(value, label=label):
        return (value,)
    if isinstance(value, ast.Dict):
        return _mapping_payloads(value, facts, sink_position=sink_position, resolving=resolving)
    if mapping_only:
        return ()
    return tuple(
        payload
        for candidate in _interpolation_values(value)
        for payload in _resolved_payloads(candidate, facts, sink_position=sink_position, resolving=resolving)
    )


def _resolved_alias(
    value: ast.expr,
    facts: _SuiteFacts | None,
    *,
    sink_position: _Position,
    resolving: frozenset[str],
) -> tuple[str, ast.expr] | None:
    if not isinstance(value, ast.Name) or facts is None or value.id in resolving:
        return None
    binding = facts.bindings.get(value.id)
    if binding is None or binding.position >= sink_position:
        return None
    return value.id, binding.value


def _mapping_payloads(
    value: ast.Dict,
    facts: _SuiteFacts | None,
    *,
    sink_position: _Position,
    resolving: frozenset[str],
) -> tuple[ast.expr, ...]:
    payloads: list[ast.expr] = []
    for key, item in zip(value.keys, value.values, strict=True):
        item_label = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
        payloads.extend(
            _resolved_payloads(
                item,
                facts,
                sink_position=sink_position,
                label=item_label,
                resolving=resolving,
            )
        )
    return tuple(payloads)


def _interpolation_values(value: ast.expr) -> tuple[ast.expr, ...]:
    match value:
        case ast.JoinedStr(values=parts):
            return tuple(part.value for part in parts if isinstance(part, ast.FormattedValue))
        case ast.BinOp(op=ast.Mod(), right=right):
            return tuple(right.elts) if isinstance(right, (ast.Tuple, ast.List)) else (right,)
        case ast.BinOp(op=ast.Add(), left=left, right=right):
            return left, right
        case ast.Call(func=ast.Attribute(value=ast.Constant(value=str()), attr="format"), args=args, keywords=words):
            return *args, *(keyword.value for keyword in words)
        case _:
            return ()


def _is_payload_reference(value: ast.expr, *, label: str | None = None) -> bool:
    if _is_safe_transform(value) or _is_secret_reference(value):
        return False
    tokens = (*identifier_tokens(label or ""), *_reference_tokens(value))
    if not tokens or ("not" not in tokens and any(token in _SAFE_METADATA for token in tokens)):
        return False
    return bool(_REQUEST_RESPONSE.intersection(tokens) and _PAYLOAD_TERMINALS.intersection(tokens))


def _analysis_facts(tree: ast.Module) -> _AnalysisFacts:
    suites: dict[int, _SuiteFacts] = {}
    statement_suites: dict[int, int] = {}
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for owner in ast.walk(tree):
        for field_name in owner._fields:
            statements = _statement_list(getattr(owner, field_name, None))
            if statements is None:
                continue
            suite_id = len(suites)
            suites[suite_id] = _facts_for_statements(statements)
            statement_suites.update((id(statement), suite_id) for statement in statements)
    return _AnalysisFacts(suites, statement_suites, parents)


def _statement_list(value: object) -> list[ast.stmt] | None:
    if not isinstance(value, list):
        return None
    ast_items: list[ast.AST] = [item for item in value if isinstance(item, ast.AST)]  # pyright: ignore[reportUnknownVariableType] — narrowed by isinstance
    if not ast_items or not all(isinstance(item, ast.stmt) for item in ast_items):
        return None
    return [item for item in ast_items if isinstance(item, ast.stmt)]


def _facts_for_statements(statements: list[ast.stmt]) -> _SuiteFacts:
    counts: Counter[str] = Counter()
    candidates: dict[str, _Binding] = {}
    mutated: set[str] = set()
    positions = {id(statement): index for index, statement in enumerate(statements)}
    for index, statement in enumerate(statements):
        bound_names = _bound_names(statement)
        counts.update(bound_names)
        binding = _direct_binding(statement)
        if binding is not None:
            candidates[binding[0]] = _Binding(binding[1], (index, 0))
        mutated.update(_mutated_names(statement))
    return _SuiteFacts(
        {name: binding for name, binding in candidates.items() if counts[name] == 1 and name not in mutated},
        positions,
    )


def _direct_binding(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
        return statement.target.id, statement.value
    return None


def _bound_names(statement: ast.stmt) -> tuple[str, ...]:
    names: list[str] = []
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        if node is not statement and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.append(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.append(node.name)
        stack.extend(ast.iter_child_nodes(node))
    return tuple(names)


def _mutated_names(statement: ast.stmt) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(statement):
        if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = _root_name(node)
            if root is not None:
                names.add(root)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATING_METHODS
            and (root := _root_name(node.func.value)) is not None
        ):
            names.add(root)
    return frozenset(names)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _containing_statement(node: ast.AST, parents: dict[int, ast.AST]) -> ast.stmt | None:
    current: ast.AST | None = node
    while current is not None and not isinstance(current, ast.stmt):
        current = parents.get(id(current))
    return current


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
