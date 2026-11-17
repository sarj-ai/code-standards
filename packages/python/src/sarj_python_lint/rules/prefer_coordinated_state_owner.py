from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
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
from sarj_python_lint.rules._native_namespace_capability import native_namespace_capability_escapes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MAX_CLASS_NODES = 4096
_MAX_FIELDS = 16
_MAX_GROUPS = 256
_MAX_MANGLED_NAME_LENGTH = 255
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


@dataclass(frozen=True)
class _Initialization:
    target: ast.expr
    annotation: ast.expr
    value: ast.expr


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
            "Warning only. Names and field counts never establish a finding. Each reported group requires consecutive same-key assignments and consecutive same-key removals in different function scopes. Every observed per-key mutation of every member inside the class must participate. Writers and readers outside that receiver scope are not inferred. Maximal groups are preferred, and disjoint groups can report separately without repeating fields.",
            "Distinct private receiver fields must be initialized directly to empty dict literals or unshadowed dict() calls in a synchronous __init__, with builtin dict annotations and the same unshadowed str, int or bytes key type. Annotations may be inline or unique annotation-only class declarations. Keys resolve to the same unchanged parameter with that explicit type. Receivers resolve by binding, including captures in nested callbacks. Shadowed parameters are distinct; ambiguous rebinding abstains. Private names use lexical class mangling, including explicitly mangled aliases; mangled names over 255 characters abstain.",
            "Subscript writes may insert or overwrite; key existence is not inferred. Only direct subscript assignment/deletion and direct pop(key[, None]) statements are mutations. Subscript reads and get/items/keys/values/copy calls are inventoried. Aliases/escapes, escaped bound methods, class/state reflection including implicit super()/__class__ access, replacement, augmented mutation, other methods, unpaired writes, unknown bases/decorators, stored class attributes, nested classes, generic scopes and ambiguous namespaces abstain. A proven builtin object base and import-proven typing.final class/method decorators are allowed. Classes over 4096 nodes, 16 candidate fields or 256 distinct mutation groups, and test/generated/malformed files, are excluded.",
            "The rule does not prove atomic updates, equal key sets, reachable paths, cross-module ownership or runtime value types. Calls can raise and async callbacks can interleave. Explicit await/yield or implicit async-comprehension suspension inside an operation, or any intervening statement, prevents a group. Helper-mediated coordination and independently removed entries remain unsupported. Mirrored indexes or protocol-mandated stores can legitimately match; use a reasoned exact-code suppression after review.",
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
        if (
            provenance.wildcard
            or provenance.dynamic_namespace
            or not provenance.builtin_namespace_untouched
            or native_namespace_capability_escapes(context)
        ):
            return []
        findings: list[Diagnostic] = []
        for owner in context.tree.body:
            if isinstance(owner, ast.ClassDef) and _plain_class(owner, provenance):
                findings.extend(
                    finding
                    for finding in _class_findings(owner, context, provenance)
                    if not context.suppressions.is_suppressed(finding.line, self.code)
                )
        return findings


def _plain_class(owner: ast.ClassDef, provenance: ResourceProvenance) -> bool:
    return (
        (
            not owner.bases
            or (
                len(owner.bases) == 1
                and isinstance(owner.bases[0], ast.Name)
                and owner.bases[0].id == "object"
                and provenance.context.imports.builtin_is_unshadowed("object")
            )
        )
        and not owner.keywords
        and not owner.type_params
        and all(
            provenance.imported(decorator, "typing.final") or provenance.imported(decorator, "typing_extensions.final")
            for decorator in owner.decorator_list
        )
        and all(
            isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef | ast.Pass | ast.Expr)
            or (isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name) and member.value is None)
            for member in owner.body
        )
        and not any(
            isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            and (
                any(
                    not (
                        provenance.imported(decorator, "typing.final")
                        or provenance.imported(decorator, "typing_extensions.final")
                    )
                    for decorator in member.decorator_list
                )
                or member.type_params
                or member.name in {"__getattr__", "__getattribute__", "__setattr__", "__delattr__"}
            )
            for member in owner.body
        )
    )


def _class_findings(
    owner: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance
) -> list[Diagnostic]:
    nodes = _analyzable_nodes(owner)
    if not nodes:
        return []
    receivers = _receivers(owner)
    fields = _constructor_fields(owner, receivers, context, provenance)
    if not _PAIR_ARITY <= len(fields) <= _MAX_FIELDS:
        return []
    if _receiver_escapes(nodes, receivers, context, provenance, owner=owner, fields=fields):
        return []
    operations = _operations(nodes, fields, receivers, context, provenance)
    uses = _uses(nodes, fields, receivers, operations, context, provenance=provenance)
    groups = _groups(nodes, operations)
    if groups is None:
        return []
    findings: list[Diagnostic] = []
    unavailable = set(uses.invalid)
    for names, evidence in sorted(groups.items(), key=lambda item: (-len(item[0]), item[0])):
        if not unavailable.isdisjoint(names):
            continue
        paired = {item.statement for pair in evidence for item in pair}
        if any(operation.field in names and statement not in paired for statement, operation in operations.items()):
            continue
        finding = _evidence_finding(owner, names, evidence, uses.readers, context)
        if finding is not None:
            findings.append(finding)
            unavailable.update(names)
    return findings


def _analyzable_nodes(owner: ast.ClassDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    for node in ast.walk(owner):
        if (
            len(nodes) >= _MAX_CLASS_NODES
            or isinstance(node, ast.type_param)
            or (isinstance(node, ast.ClassDef) and node is not owner)
        ):
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
    fields: dict[str, tuple[ast.stmt, str]],
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
    nodes: list[ast.AST],
    receivers: set[ast.arg],
    context: PythonFileContext,
    provenance: ResourceProvenance,
    *,
    owner: ast.ClassDef,
    fields: dict[str, tuple[ast.stmt, str]],
) -> bool:
    methods = {
        _attribute_identity(member.name, owner)
        for member in owner.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
    } - fields.keys()
    for node in nodes:
        if _implicit_receiver_access(node, receivers, provenance):
            return True
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if _ambiguous_receiver(node, receivers, provenance):
            return True
        if provenance.binding(node.id, node) not in receivers:
            continue
        parent = context.parents.get(node)
        if not isinstance(parent, ast.Attribute) or parent.value is not node:
            return True
        if _escaped_bound_method(parent, methods, context, owner):
            return True
    return False


def _implicit_receiver_access(node: ast.AST, receivers: set[ast.arg], provenance: ResourceProvenance) -> bool:
    match node:
        case ast.Attribute():
            return _reflective_attribute(node, provenance)
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return any(receiver.arg in names for receiver in receivers)
        case ast.Name(id=name, ctx=ast.Load()):
            return name in {"__class__", "super"}
        case _:
            return False


def _reflective_attribute(node: ast.Attribute, provenance: ResourceProvenance) -> bool:
    if node.attr in {"__class__", "__getstate__", "__reduce__", "__reduce_ex__", "__self__", "__closure__"}:
        return True
    if not node.attr.startswith("__") or node.attr.endswith("__"):
        return False
    owner = _lexical_class(node, provenance)
    return owner is not None and len(_attribute_identity(node.attr, owner)) > _MAX_MANGLED_NAME_LENGTH


def _ambiguous_receiver(node: ast.Name, receivers: set[ast.arg], provenance: ResourceProvenance) -> bool:
    scope = provenance.scope(node)
    while scope is not None:
        bindings = provenance.bindings.get(scope, {}).get(node.id, ())
        if bindings:
            return len(bindings) != 1 and any(binding in receivers for binding in bindings)
        scope = provenance.scope(scope)
    return False


def _escaped_bound_method(
    node: ast.Attribute, methods: set[str], context: PythonFileContext, owner: ast.ClassDef
) -> bool:
    if _attribute_identity(node.attr, owner) not in methods:
        return False
    use = context.parents.get(node)
    return not isinstance(use, ast.Call) or use.func is not node


def _constructor_fields(
    owner: ast.ClassDef, receivers: set[ast.arg], context: PythonFileContext, provenance: ResourceProvenance
) -> dict[str, tuple[ast.stmt, str]]:
    initializers = [
        member for member in owner.body if isinstance(member, ast.FunctionDef) and member.name == "__init__"
    ]
    return _fields(initializers[0], owner, receivers, context, provenance) if len(initializers) == 1 else {}


def _groups(
    nodes: list[ast.AST], operations: dict[ast.stmt, _Operation]
) -> dict[tuple[str, ...], list[tuple[_Operation, ...]]] | None:
    groups: dict[tuple[str, ...], list[tuple[_Operation, ...]]] = defaultdict(list)
    for method in (node for node in nodes if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)):
        for block in statement_blocks(method.body):
            for names, evidence in _mutation_windows(block, operations):
                groups[names].append(evidence)
                if len(groups) > _MAX_GROUPS:
                    return None
    return groups


def _mutation_windows(
    block: list[ast.stmt], operations: dict[ast.stmt, _Operation]
) -> Iterator[tuple[tuple[str, ...], tuple[_Operation, ...]]]:
    for index, statement in enumerate(block):
        first = operations.get(statement)
        if first is None:
            continue
        run = [first]
        names = {first.field}
        for following in block[index + 1 : index + _MAX_FIELDS]:
            item = operations.get(following)
            if item is None or item.field in names or item.key is not first.key or item.kind != first.kind:
                break
            run.append(item)
            names.add(item.field)
            yield tuple(sorted(names)), tuple(run)


def _evidence_finding(
    owner: ast.ClassDef,
    names: tuple[str, ...],
    evidence: list[tuple[_Operation, ...]],
    readers: dict[str, list[ast.expr]],
    context: PythonFileContext,
) -> Diagnostic | None:
    assignments = [group[0] for group in evidence if group[0].kind == "write"]
    removals = [group[0] for group in evidence if group[0].kind == "remove"]
    if (
        not assignments
        or not removals
        or len({_scope(item.statement, context) for item in (*assignments, *removals)}) < _PAIR_ARITY
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
        f"{', '.join(f'`{owner.name}.{name}`' for name in names)} have grouped same-key assignment/removal "
        f"at {writes}; readers: {reads}. If entry lifetimes must agree, use one typed owner per key; "
        "independent completion or intentional mirrored stores require review.",
        severity=Severity.WARNING,
    )


def _fields(
    initializer: ast.FunctionDef,
    owner: ast.ClassDef,
    receivers: set[ast.arg],
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> dict[str, tuple[ast.stmt, str]]:
    result: dict[str, tuple[ast.stmt, str]] = {}
    annotations: dict[str, list[ast.expr]] = defaultdict(list)
    for member in owner.body:
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name) and member.value is None:
            annotations[_attribute_identity(member.target.id, owner)].append(member.annotation)
    for statement in initializer.body:
        assignment = _annotated_assignment(statement, annotations, receivers, provenance)
        if assignment is None:
            continue
        if not _empty_dict(assignment.value, context):
            continue
        name = _field(assignment.target, receivers, provenance)
        key = _dictionary_key(assignment.annotation, context)
        if name is not None and key is not None:
            result[name] = statement, key
    return result


def _annotated_assignment(
    statement: ast.stmt,
    annotations: dict[str, list[ast.expr]],
    receivers: set[ast.arg],
    provenance: ResourceProvenance,
) -> _Initialization | None:
    if isinstance(statement, ast.AnnAssign):
        return (
            _Initialization(statement.target, statement.annotation, statement.value)
            if statement.value is not None
            else None
        )
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        return None
    target = statement.targets[0]
    candidates = annotations.get(_field(target, receivers, provenance) or "", [])
    return _Initialization(target, candidates[0], statement.value) if len(candidates) == 1 else None


def _dictionary_key(annotation: ast.expr, context: PythonFileContext) -> str | None:
    if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
        return None
    if annotation.value.id != "dict" or not context.imports.builtin_is_unshadowed("dict"):
        return None
    if not isinstance(annotation.slice, ast.Tuple) or len(annotation.slice.elts) != _PAIR_ARITY:
        return None
    key = annotation.slice.elts[0]
    if isinstance(key, ast.Name) and key.id in _KEY_TYPES and context.imports.builtin_is_unshadowed(key.id):
        return key.id
    return None


def _empty_dict(value: ast.expr | None, context: PythonFileContext) -> bool:
    return (isinstance(value, ast.Dict) and not value.keys) or (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "dict"
        and not value.args
        and not value.keywords
        and context.imports.builtin_is_unshadowed("dict")
    )


def _attribute_identity(name: str, owner: ast.ClassDef) -> str:
    prefix = owner.name.lstrip("_")
    return f"_{prefix}{name}" if prefix and name.startswith("__") and not name.endswith("__") else name


def _lexical_class(node: ast.AST, provenance: ResourceProvenance) -> ast.ClassDef | None:
    scope = provenance.scope(node)
    while scope is not None:
        if isinstance(scope, ast.ClassDef):
            return scope
        scope = provenance.scope(scope)
    return None


def _field(node: ast.AST, receivers: set[ast.arg], provenance: ResourceProvenance) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.attr.startswith("_")
        and provenance.binding(node.value.id, node.value) in receivers
    ):
        owner = _lexical_class(node, provenance)
        return _attribute_identity(node.attr, owner) if owner is not None else None
    return None


def _operation(
    statement: ast.stmt,
    fields: dict[str, tuple[ast.stmt, str]],
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
    if any(
        isinstance(node, ast.Await | ast.Yield | ast.YieldFrom)
        or (isinstance(node, ast.comprehension) and node.is_async)
        for node in ast.walk(statement)
    ):
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
    fields: dict[str, tuple[ast.stmt, str]],
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
        if isinstance(parent, ast.AnnAssign | ast.Assign) and parent is fields[name][0]:
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
