from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, final, override

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
from sarj_python_lint.rules._ast_index import statement_blocks
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MAX_CLASS_NODES = 4096
_MAX_FIELDS = 16
_PAIR_ARITY = 2
_READ_METHODS = frozenset({"get", "items", "keys", "values", "copy"})
_KEY_TYPES = frozenset({"str", "int", "bytes"})
_BAD = """import asyncio
class Playback:
    def __init__(self) -> None:
        self._observers: dict[str, asyncio.Task[None]] = {}
        self._playbacks: dict[str, asyncio.Task[bool]] = {}
    def start(self, key: str, observer: asyncio.Task[None], playback: asyncio.Task[bool]) -> None:
        self._observers[key] = observer
        self._playbacks[key] = playback
    def finish(self, key: str) -> None:
        self._observers.pop(key, None)
        self._playbacks.pop(key, None)
"""
_GOOD = """import asyncio
from dataclasses import dataclass
@dataclass(frozen=True)
class ActivePlayback:
    observer: asyncio.Task[None]
    playback: asyncio.Task[bool]
class Playback:
    def __init__(self) -> None:
        self._active: dict[str, ActivePlayback] = {}
    def start(self, key: str, observer: asyncio.Task[None], playback: asyncio.Task[bool]) -> None:
        self._active[key] = ActivePlayback(observer, playback)
    def finish(self, key: str) -> None:
        self._active.pop(key, None)
"""


@dataclass(frozen=True)
class _Operation:
    field: str
    key: ast.arg
    kind: Literal["write", "remove"]
    statement: ast.stmt
    container: ast.expr


@dataclass(frozen=True)
class _Uses:
    invalid: set[str]
    readers: dict[str, list[ast.expr]]


@final
class PreferCoordinatedStateOwner(Rule):
    id = "prefer-coordinated-state-owner"
    code = "SARJ565"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Review dictionaries with repeated same-key writes and removals for one typed owner.",
        rationale=(
            "Repeated same-key writes and removals in separate dictionaries distribute a possible entry-lifetime "
            "invariant across writers. One typed owner can hold the coordinated values. This is structural evidence "
            "for review, not proof of a defect or a shared domain lifetime."
        ),
        remediation=(
            "Review the reported fields, writers and readers. If entries have one lifetime, use one dictionary "
            "of typed owner records retaining each value's annotation. Preserve task identities, start/stop order, "
            "exception observation, cancellation and joining. Keep independent outcome reporting, historical "
            "observations, partial results and independently removed entries separate."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warning only. Names and field counts never establish a finding. One finding per plain module-level class requires adjacent same-key assignments and adjacent same-key removals in different function scopes. Every observed per-key mutation of both fields must participate in these pairs.",
            "Distinct private receiver fields must be initialized directly to empty dict literals in an undecorated synchronous __init__, with builtin dict annotations and the same unshadowed str, int or bytes key type. Keys resolve to the same unchanged parameter with that explicit type. Receivers resolve by binding, including captures in nested callbacks. Shadowed parameters are distinct.",
            "Subscript writes may insert or overwrite; key existence is not inferred. Only direct subscript assignment/deletion and direct pop(key[, None]) statements are mutations. Subscript reads and get/items/keys/values/copy calls are inventoried. Aliases/escapes, replacement, augmented mutation, other methods, unpaired writes, inherited/decorated classes, class attributes, generic scopes and ambiguous namespaces abstain. Import-proven typing.final is allowed. Classes over 4096 nodes or 16 candidate fields, and test/generated/malformed files, are excluded.",
            "The rule does not prove atomic updates, equal key sets, reachable paths, cross-module ownership or runtime value types. Calls can raise and async callbacks can interleave. An await or any intervening statement prevents a pair. Helper-mediated coordination and independently removed entries remain unsupported. Mirrored indexes or protocol-mandated stores can legitimately match; use a reasoned exact-code suppression after review.",
            "No automatic owner migration is safe: construction timing, identity, serializers, callback capture, exceptions and cancellation require scoped review. Existing model-union and task-cancellation rules retain their own contracts. This advisory never authorizes deleting state or cleanup.",
        ),
        examples=(
            RuleExample(
                example_id="coordinated-playback-bookkeeping",
                title="Observer and playback entries repeat paired bookkeeping",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("playback.py", _BAD),),
                focus_path=PurePosixPath("playback.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="one-typed-playback-owner",
                title="One typed entry retains both task identities",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("playback.py", _GOOD),),
                focus_path=PurePosixPath("playback.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or is_test_path(context.path)
            or "dict" not in context.symbol_source
        ):
            return []
        provenance = context.static_resource_provenance
        if provenance.wildcard or provenance.dynamic_namespace or not provenance.builtin_namespace_untouched:
            return []
        findings: list[Diagnostic] = []
        for owner in context.tree.body:
            if isinstance(owner, ast.ClassDef) and _plain_class(owner, provenance):
                finding = _class_finding(owner, context, provenance)
                if finding is not None and not context.suppressions.is_suppressed(finding.line, self.code):
                    findings.append(finding)
        return findings


def _plain_class(owner: ast.ClassDef, provenance: ResourceProvenance) -> bool:
    return (
        not owner.bases
        and not owner.keywords
        and not owner.type_params
        and all(
            provenance.imported(decorator, "typing.final") or provenance.imported(decorator, "typing_extensions.final")
            for decorator in owner.decorator_list
        )
        and all(
            isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef | ast.Pass | ast.Expr) for member in owner.body
        )
        and not any(
            isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            and (
                member.decorator_list
                or member.type_params
                or member.name in {"__getattr__", "__getattribute__", "__setattr__", "__delattr__"}
            )
            for member in owner.body
        )
    )


def _class_finding(
    owner: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance
) -> Diagnostic | None:
    nodes = _analyzable_nodes(owner)
    if not nodes:
        return None
    receivers = _receivers(owner)
    fields = _constructor_fields(owner, receivers, context, provenance)
    if not _PAIR_ARITY <= len(fields) <= _MAX_FIELDS:
        return None
    if _receiver_escapes(nodes, receivers, context, provenance):
        return None
    operations = _operations(nodes, fields, receivers, context, provenance)
    uses = _uses(nodes, fields, receivers, operations, context, provenance=provenance)
    for names, evidence in sorted(_pairs(nodes, operations).items()):
        if uses.invalid.intersection(names):
            continue
        paired = {item.statement for pair in evidence for item in pair}
        if any(operation.field in names and statement not in paired for statement, operation in operations.items()):
            continue
        finding = _evidence_finding(owner, names, evidence, uses.readers, context)
        if finding is not None:
            return finding
    return None


def _analyzable_nodes(owner: ast.ClassDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    for node in ast.walk(owner):
        if len(nodes) >= _MAX_CLASS_NODES or isinstance(node, ast.type_param):
            return []
        nodes.append(node)
    return nodes


def _receivers(owner: ast.ClassDef) -> set[ast.arg]:
    methods = [member for member in owner.body if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)]
    return {
        (method.args.posonlyargs + method.args.args)[0]
        for method in methods
        if method.args.posonlyargs or method.args.args
    }


def _operations(
    nodes: list[ast.AST],
    fields: dict[str, tuple[ast.AnnAssign, str]],
    receivers: set[ast.arg],
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> dict[ast.stmt, _Operation]:
    return {
        node: operation
        for node in nodes
        if isinstance(node, ast.stmt)
        and (operation := _operation(node, fields, receivers, context, provenance)) is not None
    }


def _receiver_escapes(
    nodes: list[ast.AST], receivers: set[ast.arg], context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    for node in nodes:
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if provenance.binding(node.id, node) not in receivers:
            continue
        parent = context.parents.get(node)
        if not isinstance(parent, ast.Attribute) or parent.value is not node:
            return True
    return False


def _constructor_fields(
    owner: ast.ClassDef, receivers: set[ast.arg], context: PythonFileContext, provenance: ResourceProvenance
) -> dict[str, tuple[ast.AnnAssign, str]]:
    initializers = [
        member for member in owner.body if isinstance(member, ast.FunctionDef) and member.name == "__init__"
    ]
    return _fields(initializers[0], receivers, context, provenance) if len(initializers) == 1 else {}


def _pairs(
    nodes: list[ast.AST], operations: dict[ast.stmt, _Operation]
) -> dict[tuple[str, str], list[tuple[_Operation, _Operation]]]:
    pairs: dict[tuple[str, str], list[tuple[_Operation, _Operation]]] = defaultdict(list)
    for method in (node for node in nodes if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)):
        for block in statement_blocks(method.body):
            for left, right in pairwise(block):
                a, b = operations.get(left), operations.get(right)
                if a is not None and b is not None and a.field != b.field and a.key is b.key and a.kind == b.kind:
                    names = sorted((a.field, b.field))
                    pairs[names[0], names[1]].append((a, b))
    return pairs


def _evidence_finding(
    owner: ast.ClassDef,
    names: tuple[str, str],
    evidence: list[tuple[_Operation, _Operation]],
    readers: dict[str, list[ast.expr]],
    context: PythonFileContext,
) -> Diagnostic | None:
    assignments = [a for a, _b in evidence if a.kind == "write"]
    removals = [a for a, _b in evidence if a.kind == "remove"]
    if (
        not assignments
        or not removals
        or _scope(assignments[0].statement, context) is _scope(removals[0].statement, context)
    ):
        return None
    writes = ", ".join(_site(item.statement, context) for pair in evidence for item in pair)
    reads = ", ".join(_site(node, context) for name in names for node in readers[name]) or "none locally"
    first = assignments[0].statement
    return Diagnostic(
        context.path,
        first.lineno,
        first.col_offset + 1,
        PreferCoordinatedStateOwner.code,
        f"`{owner.name}.{names[0]}` and `{owner.name}.{names[1]}` have paired same-key assignment/removal "
        f"at {writes}; readers: {reads}. If entry lifetimes must agree, use one typed owner per key; "
        "independent completion or intentional mirrored stores require review.",
        severity=Severity.WARNING,
    )


def _fields(
    initializer: ast.FunctionDef, receivers: set[ast.arg], context: PythonFileContext, provenance: ResourceProvenance
) -> dict[str, tuple[ast.AnnAssign, str]]:
    result: dict[str, tuple[ast.AnnAssign, str]] = {}
    for statement in initializer.body:
        if (
            not isinstance(statement, ast.AnnAssign)
            or not isinstance(statement.value, ast.Dict)
            or statement.value.keys
        ):
            continue
        name = _field(statement.target, receivers, provenance)
        annotation = statement.annotation
        if name is None or not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
            continue
        if annotation.value.id != "dict" or not context.imports.builtin_is_unshadowed("dict"):
            continue
        if not isinstance(annotation.slice, ast.Tuple) or len(annotation.slice.elts) != _PAIR_ARITY:
            continue
        key = annotation.slice.elts[0]
        if isinstance(key, ast.Name) and key.id in _KEY_TYPES and context.imports.builtin_is_unshadowed(key.id):
            result[name] = statement, key.id
    return result


def _field(node: ast.AST, receivers: set[ast.arg], provenance: ResourceProvenance) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.attr.startswith("_")
        and provenance.binding(node.value.id, node.value) in receivers
    ):
        return node.attr
    return None


def _operation(
    statement: ast.stmt,
    fields: dict[str, tuple[ast.AnnAssign, str]],
    receivers: set[ast.arg],
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> _Operation | None:
    target: ast.AST | None = None
    kind: Literal["write", "remove"] = "write"
    match statement:
        case ast.Assign(targets=[ast.Subscript() as subscript]):
            target = subscript
        case ast.Delete(targets=[ast.Subscript() as subscript]):
            target, kind = subscript, "remove"
        case ast.Expr(value=ast.Call() as call) | ast.Assign(value=ast.Call() as call):
            if _plain_pop(call):
                target, kind = call, "remove"
        case _:
            pass
    if isinstance(target, ast.Subscript):
        container, key = target.value, target.slice
    elif isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
        container, key = target.func.value, target.args[0]
    else:
        return None
    name = _field(container, receivers, provenance)
    if name is None or name not in fields or not isinstance(key, ast.Name):
        return None
    binding = provenance.binding(key.id, key)
    if not isinstance(binding, ast.arg) or not isinstance(binding.annotation, ast.Name):
        return None
    if binding.annotation.id != fields[name][1] or not context.imports.builtin_is_unshadowed(binding.annotation.id):
        return None
    if any(isinstance(node, ast.Await | ast.Yield | ast.YieldFrom) for node in ast.walk(statement)):
        return None
    return _Operation(name, binding, kind, statement, container)


def _plain_pop(call: ast.Call) -> bool:
    match call:
        case ast.Call(func=ast.Attribute(attr="pop"), args=[_] | [_, ast.Constant(value=None)], keywords=[]):
            return True
        case _:
            return False


def _uses(
    nodes: list[ast.AST],
    fields: dict[str, tuple[ast.AnnAssign, str]],
    receivers: set[ast.arg],
    operations: dict[ast.stmt, _Operation],
    context: PythonFileContext,
    *,
    provenance: ResourceProvenance,
) -> _Uses:
    invalid: set[str] = set()
    readers: dict[str, list[ast.expr]] = defaultdict(list)
    for node in nodes:
        name = _field(node, receivers, provenance)
        if name is None or name not in fields:
            continue
        parent = context.parents.get(node)
        if isinstance(parent, ast.AnnAssign) and parent is fields[name][0] and parent.target is node:
            continue
        statement = _statement(node, context)
        if statement is not None and statement in operations and operations[statement].container is node:
            continue
        read = _reader(node, context)
        if read is None:
            invalid.add(name)
        else:
            readers[name].append(read)
    return _Uses(invalid, readers)


def _statement(node: ast.AST, context: PythonFileContext) -> ast.stmt | None:
    while (parent := context.parents.get(node)) is not None:
        if isinstance(parent, ast.stmt):
            return parent
        node = parent
    return None


def _reader(node: ast.AST, context: PythonFileContext) -> ast.expr | None:
    parent = context.parents.get(node)
    if isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, ast.Load):
        return parent
    if isinstance(parent, ast.Attribute) and parent.attr in _READ_METHODS:
        call = context.parents.get(parent)
        if isinstance(call, ast.Call) and call.func is parent:
            return call
    return None


def _scope(node: ast.AST, context: PythonFileContext) -> _Function | None:
    while (parent := context.parents.get(node)) is not None:
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            return parent
        node = parent
    return None


def _site(node: ast.expr | ast.stmt, context: PythonFileContext) -> str:
    scope = _scope(node, context)
    return f"{scope.name if scope is not None else 'class'}:{node.lineno}"
