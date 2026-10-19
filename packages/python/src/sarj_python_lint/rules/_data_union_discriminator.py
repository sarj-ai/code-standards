from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from sarj_python_lint.rule_base import Diagnostic, Severity, is_suppressed
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._pydantic_field_contract import MODEL_SOURCES, unique_members
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_DATACLASS_SOURCES = frozenset({"dataclasses"})
_MAX_EXPANSION = 128
_MIN_VARIANTS = 2

type _Tag = str | bytes | int | None


@dataclass(frozen=True, slots=True)
class _Record:
    fields: dict[str, ast.AnnAssign]
    required: bool


@dataclass(frozen=True, slots=True)
class _Domain:
    values: frozenset[_Tag] = frozenset()
    opaque: bool = False
    unresolved: bool = False


@dataclass(frozen=True, slots=True)
class _Expansion:
    node: ast.expr
    aliases: frozenset[str] = frozenset()


@dataclass(slots=True)
class _Budget:
    remaining: int = _MAX_EXPANSION


def data_union_diagnostics(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if not any(symbol in context.symbol_source for symbol in ("dataclass", "BaseModel", "TypedDict")):
        return []
    tree = context.tree
    if tree is None or context.generated or context.has_wildcard_import:
        return []
    if not any(
        value is not None and _union_expression(value, context)
        for node in tree.body
        for value in (_alias_value(node, context),)
    ):
        return []
    analysis = _DataUnions(context, tree)
    if analysis.provenance.dynamic_namespace:
        return []
    return analysis.diagnostics(code)


@final
class _DataUnions:
    def __init__(self, context: PythonFileContext, tree: ast.Module) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)
        bindings = self.provenance.bindings.get(tree, {})
        self.classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and len(bindings.get(node.name, ())) == 1
            and node.name not in self.provenance.mutated
        }
        self.aliases: dict[str, ast.expr] = {}
        self.declarations: dict[str, ast.stmt] = {}
        for node in tree.body:
            value = _alias_value(node, context)
            name = _alias_name(node)
            if value is not None and name is not None and len(bindings.get(name, ())) == 1:
                self.aliases[name] = value
                self.declarations[name] = node
        self.records: dict[str, _Record | None] = {}

    def diagnostics(self, code: str) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for name, value in self.aliases.items():
            node = self.declarations[name]
            if is_suppressed(self.context.source_lines, node.lineno, code) or not self._untagged_union(value):
                continue
            findings.append(
                Diagnostic(
                    path=self.context.path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=code,
                    message=f"Data union `{name}` has no shared disjoint Literal discriminator. "
                    "Add a common field such as `kind` or `scope` with non-overlapping Literal values "
                    "on every variant; preserve constructor and serialized contracts when choosing defaults.",
                    severity=Severity.WARNING,
                )
            )
        return findings

    def _untagged_union(self, value: ast.expr) -> bool:
        if not _union_expression(value, self.context):
            return False
        variants = self._variants(value)
        if variants is None or len(variants) < _MIN_VARIANTS:
            return False
        records: list[_Record] = []
        for variant in sorted(variants):
            record = self._record(variant)
            if record is None:
                return False
            records.append(record)
        return not self._has_discriminator(records, _Budget())

    def _typing_symbol(self, node: ast.expr) -> str | None:
        if not _untouched(node, self.provenance):
            return None
        return self.context.imports.resolved_symbol(node, sources=TYPING_SOURCES)

    def _variants(self, expression: ast.expr) -> set[str] | None:
        leaves = self._leaves(expression)
        if leaves is None:
            return None
        variants: set[str] = set()
        for node in leaves:
            if isinstance(node, ast.Constant) and node.value is None:
                continue
            if not isinstance(node, ast.Name) or node.id not in self.classes:
                return None
            variants.add(node.id)
        return variants

    def _leaves(self, expression: ast.expr) -> list[ast.expr] | None:
        pending = [_Expansion(expression)]
        leaves: list[ast.expr] = []
        for _ in range(_MAX_EXPANSION):
            if not pending:
                return leaves
            item = pending.pop()
            node = _string_expression(item.node)
            if node is None:
                return None
            if isinstance(node, ast.Name) and node.id in self.aliases:
                if node.id in item.aliases:
                    return None
                pending.append(_Expansion(self.aliases[node.id], item.aliases | {node.id}))
            else:
                children = self._union_members(node)
                if children is None:
                    leaves.append(node)
                else:
                    pending.extend(_Expansion(child, item.aliases) for child in children)
        return None

    def _union_members(self, node: ast.expr) -> tuple[ast.expr, ...] | None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return node.left, node.right
        if not isinstance(node, ast.Subscript):
            return None
        symbol = self._typing_symbol(node.value)
        if symbol == "Union" and isinstance(node.slice, ast.Tuple):
            return tuple(node.slice.elts)
        if symbol == "Optional":
            return node.slice, ast.Constant(value=None)
        if symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            return (node.slice.elts[0],)
        return None

    def _record(self, name: str) -> _Record | None:
        if name not in self.records:
            self.records[name] = _record(self.classes[name], self.context, self.provenance)
        return self.records[name]

    def _has_discriminator(self, records: list[_Record], budget: _Budget) -> bool:
        if budget.remaining <= 0:
            return True
        budget.remaining -= 1
        common = set(records[0].fields).intersection(*(record.fields for record in records[1:]))
        common.difference_update({name for name in common if name.startswith("__")})
        uncertain = False
        for name in sorted(common):
            domains = [self._field_domain(record.fields[name], required=record.required) for record in records]
            uncertain |= _uncertain_domains(domains)
            groups = _tag_groups(records, domains)
            if groups and all(len(group) == 1 or self._has_discriminator(group, budget) for group in groups):
                return True
        return uncertain

    def _field_domain(self, field: ast.AnnAssign, *, required: bool) -> _Domain:
        node = field.annotation
        for _ in range(_MAX_EXPANSION):
            parsed = _string_expression(node)
            if parsed is None:
                return _Domain(opaque=True)
            node = parsed
            if not isinstance(node, ast.Subscript):
                break
            symbol = self._typing_symbol(node.value)
            if symbol in {"Required", "NotRequired"}:
                required = symbol == "Required"
                node = node.slice
            elif symbol == "ClassVar":
                if field.value is None:
                    return _Domain()
                node = node.slice
            elif symbol == "ReadOnly":
                node = node.slice
            elif symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
                node = node.slice.elts[0]
            else:
                break
        return self._literal_domain(node) if required else _Domain()

    def _literal_domain(self, expression: ast.expr) -> _Domain:
        leaves = self._leaves(expression)
        if leaves is None:
            return _Domain(opaque=True)
        domains = [self._leaf_domain(node) for node in leaves]
        if any(domain.opaque for domain in domains):
            return _Domain(opaque=True)
        if any(domain.unresolved for domain in domains):
            return _Domain(unresolved=True)
        if any(not domain.values for domain in domains):
            return _Domain()
        return _Domain(frozenset(value for domain in domains for value in domain.values))

    def _leaf_domain(self, node: ast.expr) -> _Domain:
        if isinstance(node, ast.Constant) and node.value is None:
            return _Domain(frozenset({None}))
        if isinstance(node, ast.Name) and (
            node.id in self.classes or self.context.imports.resolved_qualified_name(node) is not None
        ):
            return _Domain(unresolved=True)
        if not isinstance(node, ast.Subscript):
            return _Domain()
        symbol = self._typing_symbol(node.value)
        if symbol == "Literal":
            return _literal_values(node)
        if symbol is not None or (
            isinstance(node.value, ast.Name)
            and node.value.id in {"list", "dict", "tuple", "set", "frozenset", "type"}
            and self.context.imports.builtin_is_unshadowed(node.value.id)
        ):
            return _Domain()
        return _Domain(opaque=True)


def _record(node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> _Record | None:
    required = _record_required(node, context, provenance)
    if required is None:
        return None
    fields: dict[str, ast.AnnAssign] = {}
    unique = unique_members(node)
    for member in node.body:
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
            if member.target.id not in unique:
                return None
            fields[member.target.id] = member
        elif isinstance(member, ast.Pass | ast.Expr) and (
            isinstance(member, ast.Pass)
            or (isinstance(member.value, ast.Constant) and isinstance(member.value.value, str))
        ):
            continue
        else:
            return None
    return _Record(fields, required)


def _record_required(node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool | None:
    if node.type_params:
        return None
    if any(not _untouched(base, provenance) for base in node.bases):
        return None
    if node.decorator_list:
        return _direct_dataclass(node, context, provenance)
    if len(node.bases) != 1:
        return None
    if context.imports.resolves(node.bases[0], sources=MODEL_SOURCES, symbol="BaseModel"):
        return True if not node.keywords else None
    if not context.imports.resolves(node.bases[0], sources=TYPING_SOURCES, symbol="TypedDict"):
        return None
    required = True
    for keyword in node.keywords:
        if keyword.arg != "total" or not isinstance(keyword.value, ast.Constant):
            return None
        if not isinstance(keyword.value.value, bool):
            return None
        required = keyword.value.value
    return required


def _direct_dataclass(node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool | None:
    if node.bases or node.keywords or len(node.decorator_list) != 1:
        return None
    decorator = node.decorator_list[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not _untouched(target, provenance) or not context.imports.resolves(
        target, sources=_DATACLASS_SOURCES, symbol="dataclass"
    ):
        return None
    return True


def _literal_values(node: ast.Subscript) -> _Domain:
    values: set[_Tag] = set()
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    for member in members:
        match member:
            case ast.Constant(value=(str() | bytes() | int()) as value):
                values.add(value)
            case ast.Constant(value=None):
                values.add(None)
            case ast.UnaryOp(op=op, operand=ast.Constant(value=int() as number)) if (
                isinstance(op, ast.USub | ast.UAdd) and type(number) is int
            ):
                values.add(-number if isinstance(op, ast.USub) else number)
            case _:
                return _Domain(opaque=True)
    return _Domain(frozenset(values))


def _tag_groups(records: list[_Record], domains: list[_Domain]) -> list[list[_Record]]:
    if any(not domain.values or domain.opaque for domain in domains):
        return []
    groups: dict[_Tag, list[_Record]] = {}
    for record, domain in zip(records, domains, strict=True):
        for value in sorted(domain.values, key=repr):
            groups.setdefault(value, []).append(record)
    if any(len(group) == len(records) for group in groups.values()):
        return []
    return list(groups.values())


def _uncertain_domains(domains: list[_Domain]) -> bool:
    return any(domain.opaque for domain in domains) or (
        any(domain.values for domain in domains) and any(domain.unresolved for domain in domains)
    )


def _alias_name(node: ast.stmt) -> str | None:
    match node:
        case ast.TypeAlias(name=ast.Name(id=name)) | ast.AnnAssign(target=ast.Name(id=name)):
            return name
        case ast.Assign(targets=[ast.Name(id=name)]):
            return name
        case _:
            return None


def _alias_value(node: ast.stmt, context: PythonFileContext) -> ast.expr | None:
    match node:
        case ast.TypeAlias(type_params=[]):
            return node.value
        case ast.AnnAssign(target=ast.Name(), annotation=annotation, value=value):
            return value if context.imports.resolves(annotation, sources=TYPING_SOURCES, symbol="TypeAlias") else None
        case ast.Assign(targets=[ast.Name()], value=value):
            return None if isinstance(value, ast.Constant) and isinstance(value.value, str) else value
        case _:
            return None


def _string_expression(node: ast.expr) -> ast.expr | None:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return node
    try:
        return ast.parse(node.value, mode="eval").body
    except SyntaxError, UnicodeError, RecursionError:
        return None


def _untouched(node: ast.expr, provenance: ResourceProvenance) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id not in provenance.mutated


def _union_expression(node: ast.expr, context: PythonFileContext) -> bool:
    for _ in range(_MAX_EXPANSION):
        parsed = _string_expression(node)
        if parsed is None:
            return False
        node = parsed
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return True
        if not isinstance(node, ast.Subscript):
            return False
        symbol = context.imports.resolved_symbol(node.value, sources=TYPING_SOURCES)
        if symbol == "Union":
            return True
        if symbol == "Optional":
            node = node.slice
        elif symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            node = node.slice.elts[0]
        else:
            return False
    return False
