from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import chain
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._project_index import SymbolRef
from sarj_python_lint.rules._resource_provenance import import_name_for_binding
from sarj_python_lint.rules._suite_flow import previous_statements


if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Literal


type _TableUse = Literal["indexed", "sparse", "qualified-index", "opaque"]


_WRAPPERS = frozenset({"typing.Final", "typing_extensions.Final", "typing.ClassVar", "typing_extensions.ClassVar"})
_LITERAL = frozenset({"typing.Literal", "typing_extensions.Literal"})
_READONLY_CONSTRUCTORS = frozenset({"types.MappingProxyType", "frozendict.frozendict"})
_MAPPINGS = _READONLY_CONSTRUCTORS | {
    "builtins.dict",
    "collections.OrderedDict",
    "collections.abc.Mapping",
    "typing.Dict",
    "typing.Mapping",
    "typing.OrderedDict",
}
_ENUM_BASES = frozenset({"enum.Enum", "enum.IntEnum", "enum.StrEnum"})
_SPARSE_METHODS = frozenset({"get", "items", "keys", "values"})
_MIN_LITERAL_KEYS = 2
_EXAMPLE_TYPES = (
    "from enum import StrEnum\nfrom typing import Final, Literal\n\n"
    "class Acceptance(StrEnum):\n    JOINED = 'joined'\n    MEMBER = 'member'\n    CLOSED = 'closed'\n\n"
)
_EXAMPLE_ENTRIES = " = {Acceptance.JOINED: 'added', Acceptance.MEMBER: 'already a member'}\n"


@final
class RequireTotalEnumMapping(ProjectRule):
    id = "require-total-enum-mapping"
    code = "SARJ600"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Cover every member of the declared key type in a constant dispatch mapping.",
        rationale="A dispatch mapping with an omitted key can raise KeyError even when the lookup key satisfies its annotation.",
        remediation="Add the missing entries or narrow the key type to a Literal alias of the covered keys.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct module and class assignments with a dict display or a resolved read-only wrapper.",
            "Resolves direct standard enum declarations with static string or integer values, or uniform auto() values, and string Literal domains.",
            "Skips ambiguous declarations, computed or spread keys, mutable or escaping tables, and tables used only for guarded lookups or enumeration.",
        ),
        examples=(
            RuleExample(
                example_id="missing-acceptance",
                title="A dispatch table omits an acceptance status",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "case.py",
                        _EXAMPLE_TYPES
                        + "STATUS: Final[dict[Acceptance, str]]"
                        + _EXAMPLE_ENTRIES
                        + "\ndef status(acceptance: Acceptance) -> str:\n    return STATUS[acceptance]\n",
                    ),
                ),
                focus_path=PurePosixPath("case.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="narrow-acceptance-domain",
                title="A Literal alias documents the covered members",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "case.py",
                        _EXAMPLE_TYPES
                        + "type AutoAcceptance = Literal[Acceptance.JOINED, Acceptance.MEMBER]\n"
                        + "STATUS: Final[dict[AutoAcceptance, str]]"
                        + _EXAMPLE_ENTRIES,
                    ),
                ),
                focus_path=PurePosixPath("case.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        candidates = [node for node in context.nodes(ast.AnnAssign) if _table_assignment(node, context)]
        if not candidates or context.has_wildcard_import or context.dynamic_namespace:
            return []
        facts = AnnotationOrigins(context)
        return [finding for node in candidates if (finding := _finding(node, facts)) is not None]


def _table_assignment(node: ast.AnnAssign, context: PythonFileContext) -> bool:
    match node.value:
        case ast.Dict() | ast.Call(args=[ast.Dict()], keywords=[]):
            pass
        case _:
            return False
    owner = context.parents.get(node)
    while isinstance(owner, ast.ClassDef):
        owner = context.parents.get(owner)
    return owner is context.tree


def _finding(node: ast.AnnAssign, facts: AnnotationOrigins) -> Diagnostic | None:
    target = node.target
    if not isinstance(target, ast.Name) or facts.binding(target.id, target) is not target:
        return None
    key = _mapping_key(node.annotation, facts)
    if key is None:
        return None
    value = node.value
    if not isinstance(value, ast.Dict):
        match value:
            case ast.Call(func=wrapper, args=[ast.Dict() as entries], keywords=[]) if (
                facts.qualified(wrapper, wrapper) in _READONLY_CONSTRUCTORS
            ):
                value = entries
            case _:
                return None
    missing = _missing_keys(key, node.annotation, value, facts)
    if not missing or (indexed := _indexed_table(target, value, facts)) is None:
        return None
    use = " A subscript read in this module requires the key to be present." if indexed else ""
    return Diagnostic(
        path=facts.context.path,
        line=node.annotation.lineno,
        col=node.annotation.col_offset + 1,
        code=RequireTotalEnumMapping.code,
        message=f"Mapping {target.id!r} omits declared keys {', '.join(missing)}. Add entries or narrow the key type.{use}",
        severity=Severity.ERROR,
    )


def _mapping_key(annotation: ast.expr, facts: AnnotationOrigins) -> ast.expr | None:
    node = facts.context.annotation_semantics.parse(annotation)
    while isinstance(node, ast.Subscript) and facts.qualified(node.value, annotation) in _WRAPPERS:
        node = node.slice
    match node:
        case ast.Subscript(value=kind, slice=ast.Tuple(elts=[key, _])) if facts.qualified(
            kind, annotation
        ) in _MAPPINGS or facts.builtin(kind, "dict", annotation):
            return key
        case _:
            return None


def _reference(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> ast.AST | SymbolRef | None:
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in facts.provenance.mutated | facts.provenance.external_bindings:
        return None
    binding = facts.binding(root.id, at)
    if not isinstance(binding, ast.alias):
        return binding if root is node else None
    if qualified := import_name_for_binding(node, binding, facts.context.parents.get(binding)):
        module, _, name = qualified.rpartition(".")
        return SymbolRef(module, name)
    project = facts.context.session.project
    if project is not None and (unit := project.unit(facts.context.path)) is not None:
        return project.resolve(unit, node)
    return None


@dataclass(frozen=True, slots=True)
class _Declaration:
    node: ast.AST
    facts: AnnotationOrigins


def _missing_keys(key: ast.expr, at: ast.expr, entries: ast.Dict, facts: AnnotationOrigins) -> list[str]:
    match key:
        case ast.Subscript():
            return _missing_strings(key, at, entries, facts)
        case ast.Name() | ast.Attribute():
            pass
        case _:
            return []
    reference = _reference(key, at, facts)
    match _declaration(reference, facts):
        case _Declaration(node=ast.ClassDef() as enum, facts=origin):
            if members := _enum_members(enum, origin):
                return _missing_enum_members(entries, members, reference, facts)
        case _Declaration(node=ast.Name() as alias, facts=origin):
            value = origin.alias_value(alias, alias)
            match origin.context.parents.get(alias):
                case ast.Assign(targets=[target], value=literal) if target is alias:
                    value = literal
                case _:
                    pass
            match value:
                case ast.Subscript():
                    return _missing_strings(value, value, entries, origin)
                case _:
                    pass
        case _:
            pass
    return []


def _declaration(reference: ast.AST | SymbolRef | None, facts: AnnotationOrigins) -> _Declaration | None:
    match reference:
        case ast.AST():
            return _Declaration(reference, facts)
        case None:
            return None
        case SymbolRef():
            pass
    project = facts.context.session.project
    if project is None:
        return None
    unit = project.source_unit(reference.module)
    if unit is None or unit.tree is None:
        return None
    context = PythonFileContext(unit.path, unit.source, facts.context.session)
    inventory = context.binding_inventory
    match inventory.bindings.get(unit.tree, {}).get(reference.name, ()):
        case [binding] if (
            not inventory.wildcard
            and reference.name not in inventory.mutated | inventory.external_bindings
            and not context.dynamic_namespace
        ):
            return _Declaration(binding, AnnotationOrigins(context))
        case _:
            return None


def _missing_strings(node: ast.Subscript, at: ast.expr, entries: ast.Dict, facts: AnnotationOrigins) -> list[str]:
    if facts.qualified(node.value, at) not in _LITERAL or not isinstance(node.slice, ast.Tuple):
        return []
    domain: set[str] = set()
    for item in node.slice.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return []
        domain.add(item.value)
    if len(domain) < _MIN_LITERAL_KEYS:
        return []
    covered: set[str] = set()
    for key in entries.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or key.value not in domain:
            return []
        covered.add(key.value)
    return sorted(map(repr, domain - covered))


def _enum_members(enum: ast.ClassDef, facts: AnnotationOrigins) -> dict[str, str | int | ast.Call] | None:
    if len(enum.bases) != 1 or enum.decorator_list or enum.keywords:
        return None
    [base] = enum.bases
    qualified = facts.qualified(base, base)
    if qualified not in _ENUM_BASES:
        return None
    members: dict[str, str | int | ast.Call] = {}
    for statement in enum.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ):
                member = (
                    members.get(value.id) if isinstance(value, ast.Name) else _member_value(value, facts, qualified)
                )
                if member is None or name.startswith("_") or name in members:
                    return None
                members[name] = member
            case ast.Expr(value=ast.Constant(value=str())) | ast.Pass():
                continue
            case ast.FunctionDef(name=name, decorator_list=[]) if not name.startswith("_") and name not in members:
                continue
            case _:
                return None
    return members if len({isinstance(value, ast.Call) for value in members.values()}) <= 1 else None


def _member_value(value: ast.expr, facts: AnnotationOrigins, base: str) -> str | int | ast.Call | None:
    match value:
        case ast.Constant(value=str() as text) if base != "enum.IntEnum":
            return text
        case ast.Constant(value=int() as number) if base != "enum.StrEnum":
            return number
        case ast.Call(func=callee, args=[], keywords=[]) if facts.qualified(callee, callee) == "enum.auto":
            return value
        case _:
            return None


def _missing_enum_members(
    entries: ast.Dict,
    members: dict[str, str | int | ast.Call],
    reference: ast.AST | SymbolRef | None,
    facts: AnnotationOrigins,
) -> list[str]:
    covered: set[str | int | ast.Call] = set()
    for key in entries.keys:
        if (
            not isinstance(key, ast.Attribute)
            or key.attr not in members
            or _reference(key.value, key, facts) != reference
        ):
            return []
        covered.add(members[key.attr])
    missing: list[str] = []
    for name, value in members.items():
        if value not in covered:
            missing.append(name)
            covered.add(value)
    return sorted(missing)


def _indexed_table(target: ast.Name, entries: ast.Dict, facts: AnnotationOrigins) -> bool | None:
    if target.id in facts.provenance.external_bindings:
        return None
    uses = {_table_use(read, entries, facts) for read in _table_reads(target, facts)}
    if "opaque" in uses:
        return None
    if "indexed" in uses:
        return True
    return None if "sparse" in uses or _only_enumerated_by_importers(target, facts) else False


def _table_use(read: ast.Name | ast.Attribute, entries: ast.Dict, facts: AnnotationOrigins) -> _TableUse:
    if not isinstance(read.ctx, ast.Load):
        return "opaque"
    match facts.context.parents.get(read):
        case ast.Subscript(value=receiver, ctx=ast.Load()) as subscript if receiver is read:
            if _guarded_lookup(subscript, entries, facts):
                return "sparse"
            return "indexed" if isinstance(read, ast.Name) else "qualified-index"
        case (
            ast.For(iter=receiver)
            | ast.comprehension(iter=receiver)
            | ast.Compare(comparators=[receiver], ops=[ast.In() | ast.NotIn()])
        ) if receiver is read:
            return "sparse"
        case ast.Attribute() as method if _sparse_method(read, method):
            return "sparse"
        case _:
            return "opaque"


def _sparse_method(read: ast.expr, parent: ast.AST | None) -> bool:
    return isinstance(parent, ast.Attribute) and parent.value is read and parent.attr in _SPARSE_METHODS


def _table_reads(target: ast.Name, facts: AnnotationOrigins) -> Iterator[ast.Name | ast.Attribute]:
    provenance = facts.provenance
    for read in provenance.reads.get(target.id, ()):
        if (provenance.runtime_binding(target.id, read) or provenance.binding(target.id, read)) is target:
            yield read
    if isinstance(provenance.scope(target), ast.ClassDef):
        yield from (node for node in facts.context.nodes(ast.Attribute) if node.attr == target.id)


def _guarded_lookup(node: ast.Subscript, entries: ast.Dict, facts: AnnotationOrigins) -> bool:
    if _covered_key(node.slice, entries, facts):
        return True
    key = node.slice
    if not isinstance(key, ast.Name) or not isinstance(facts.provenance.runtime_binding(key.id, key), ast.arg):
        return False
    return any(
        guard and all(_covered_key(member, entries, facts) for member in guard)
        for guard in _guards_for_key(node, key, facts)
    )


def _guards_for_key(node: ast.Subscript, key: ast.Name, facts: AnnotationOrigins) -> Iterator[list[ast.expr]]:
    context = facts.context
    child: ast.AST = node
    while (parent := context.parents.get(child)) is not None:
        if (
            isinstance(parent, ast.match_case)
            and isinstance(match := context.parents.get(parent), ast.Match)
            and isinstance(match.subject, ast.Name)
            and match.subject.id == key.id
        ):
            yield _pattern_values(parent.pattern)
        if isinstance(child, ast.stmt):
            yield from (_membership_guard(statement, key.id) for statement in previous_statements(child, parent))
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return
        child = parent


def _membership_guard(statement: ast.stmt, key: str) -> list[ast.expr]:
    match statement:
        case ast.If(
            test=ast.Compare(
                left=ast.Name(id=name),
                ops=[ast.NotIn()],
                comparators=[ast.Set(elts=allowed) | ast.Tuple(elts=allowed) | ast.List(elts=allowed)],
            ),
            body=[*_, ast.Raise() | ast.Return()],
        ) if name == key:
            return allowed
        case _:
            return []


def _pattern_values(pattern: ast.pattern) -> list[ast.expr]:
    match pattern:
        case ast.MatchValue(value=value):
            return [value]
        case ast.MatchOr(patterns=patterns):
            values = [item.value for item in patterns if isinstance(item, ast.MatchValue)]
            return values if len(values) == len(patterns) else []
        case _:
            return []


def _covered_key(key: ast.expr, entries: ast.Dict, facts: AnnotationOrigins) -> bool:
    match key:
        case ast.Constant(value=str() as text):
            return any(isinstance(entry, ast.Constant) and entry.value == text for entry in entries.keys)
        case ast.Attribute(value=owner, attr=name):
            reference = _reference(owner, key, facts)
            return any(
                isinstance(entry, ast.Attribute)
                and entry.attr == name
                and _reference(entry.value, entry, facts) == reference
                for entry in entries.keys
            )
        case _:
            return False


def _only_enumerated_by_importers(target: ast.Name, facts: AnnotationOrigins) -> bool:
    context = facts.context
    project = context.session.project
    if project is None or facts.provenance.scope(target) is not context.tree:
        return False
    unit = project.unit(context.path)
    if unit is None or unit.module is None or project.source_unit(unit.module) is not unit:
        return False
    symbol = SymbolRef(unit.module, target.id)
    uses: set[bool] = set()
    for consumer in project.source_units:
        aliases = {name for name, ref in consumer.imports.items() if ref == symbol}
        if not aliases or consumer.tree is None or is_test_path(consumer.path):
            continue
        origin = AnnotationOrigins(PythonFileContext(consumer.path, consumer.source, context.session))
        reads = chain.from_iterable(origin.provenance.reads.get(name, ()) for name in aliases)
        uses.update(
            _sparse_method(read, origin.context.parents.get(read))
            for read in reads
            if _reference(read, read, origin) == symbol
        )
    return uses == {True}
