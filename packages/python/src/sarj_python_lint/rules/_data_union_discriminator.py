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
_DISCRIMINATOR_SOURCES = frozenset({"pydantic", "pydantic.types"})
_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_NON_LITERAL_BUILTINS = frozenset(
    {"str", "bytes", "int", "bool", "float", "complex", "object", "list", "dict", "tuple", "set", "frozenset", "type"}
)

type _Tag = tuple[str, str | bytes | int | None]


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
        self.provenance.mutated = _scoped_module_mutations(self.provenance, tree)
        bindings = self.provenance.bindings.get(tree, {})
        self.classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and len(bindings.get(node.name, ())) == 1
            and node.name not in self.provenance.mutated
            and node.name not in self.provenance.external_bindings
        }
        self.aliases: dict[str, ast.expr] = {}
        self.declarations: dict[str, ast.stmt] = {}
        self.values: dict[str, ast.expr] = {}
        self.metadata_aliases = _metadata_alias_graph(tree, bindings)
        self.metadata_mutation_cache: dict[str, bool | None] = {}
        self.metadata_writes = _metadata_attribute_writes(context, tree, self.provenance)
        for node in tree.body:
            binding = _value_binding(node)
            if binding is not None:
                bound_name, bound_value = binding
                if len(bindings.get(bound_name, ())) == 1:
                    self.values[bound_name] = bound_value
            value = _alias_value(node, context, self.provenance)
            name = _alias_name(node)
            if (
                value is not None
                and name is not None
                and len(bindings.get(name, ())) == 1
                and name not in self.provenance.external_bindings
                and name not in self.provenance.mutated
            ):
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
        if not _union_expression(value, self.context) or self._explicit_discriminator(value):
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

    def _explicit_discriminator(self, node: ast.expr) -> bool:
        pending = [_Expansion(node)]
        covered = False
        for _ in range(_MAX_EXPANSION):
            if not pending:
                return covered
            item = pending.pop()
            parsed = _string_expression(item.node)
            if parsed is None:
                return True
            node = parsed
            if isinstance(node, ast.Name) and node.id in self.aliases:
                if node.id in item.aliases:
                    return True
                pending.append(_Expansion(self.aliases[node.id], item.aliases | {node.id}))
                continue
            if isinstance(node, ast.Constant) and node.value is None:
                continue
            if self._discriminated_annotation(node):
                covered = True
                continue
            children = self._union_members(node)
            if children is None:
                return False
            pending.extend(_Expansion(child, item.aliases) for child in children)
        return True

    def _discriminated_annotation(self, node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Subscript)
            and self._typing_symbol(node.value) == "Annotated"
            and isinstance(node.slice, ast.Tuple)
            and any(self._discriminator_metadata(item) for item in node.slice.elts[1:])
        )

    def _discriminator_metadata(self, node: ast.expr) -> bool:
        seen: frozenset[str] = frozenset()
        for _ in range(_MAX_EXPANSION):
            reference = self._metadata_reference(node, seen)
            if isinstance(reference, bool):
                return reference
            if reference is not None:
                node, seen = reference.node, reference.aliases
                continue
            if not isinstance(node, ast.Call):
                return self._metadata_aliases_discriminate(seen, callable_metadata=False)
            step = self._metadata_step(node)
            if isinstance(step, bool):
                return self._metadata_aliases_discriminate(seen, callable_metadata=step)
            node = step
        return True

    def _metadata_reference(self, node: ast.expr, seen: frozenset[str]) -> _Expansion | bool | None:
        if isinstance(node, ast.Name) and node.id in self.values:
            return True if node.id in seen else _Expansion(self.values[node.id], seen | {node.id})
        projected = self._metadata_projection(node)
        if projected is None or isinstance(projected, bool):
            return projected
        if not projected.aliases.isdisjoint(seen) or any(
            self._metadata_projection_escaped(name) for name in projected.aliases
        ):
            return True
        return _Expansion(projected.node, seen | projected.aliases)

    def _metadata_projection(self, node: ast.expr) -> _Expansion | bool | None:
        if isinstance(node, ast.Subscript):
            return self._metadata_tuple_item(node)
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            return None
        bindings = self.provenance.bindings.get(self.context.tree, {}).get(node.value.id, ())
        if len(bindings) != 1 or not isinstance(bindings[0], ast.ClassDef):
            return None
        value = _namespace_metadata_value(bindings[0], node.attr)
        return _Expansion(value, frozenset({node.value.id})) if value is not None else None

    def _metadata_tuple_item(self, node: ast.Subscript) -> _Expansion | bool | None:
        value = node.value
        names: frozenset[str] = frozenset()
        for _ in range(_MAX_EXPANSION):
            if not isinstance(value, ast.Name) or value.id not in self.values:
                break
            if value.id in names:
                return True
            names |= {value.id}
            value = self.values[value.id]
        else:
            return True
        if not isinstance(value, ast.Tuple):
            return None
        if len(value.elts) > _MAX_EXPANSION:
            return True
        if any(isinstance(item, ast.Starred) for item in value.elts):
            return None
        index = _metadata_tuple_index(node.slice)
        if index is None:
            return True
        if not -len(value.elts) <= index < len(value.elts):
            return None
        return _Expansion(value.elts[index], names)

    def _metadata_projection_escaped(self, name: str) -> bool:
        bindings = self.provenance.bindings.get(self.context.tree, {}).get(name, ())
        reads = self.provenance.reads.get(name, ())
        if len(bindings) != 1 or len(reads) > _MAX_EXPANSION:
            return True
        for read in reads:
            if self.provenance.binding(name, read) is not bindings[0]:
                continue
            projection = self.context.parents.get(read)
            if not isinstance(projection, ast.Attribute | ast.Subscript) or projection.value is not read:
                return True
            if not self._metadata_annotation_member(projection):
                return True
        return False

    def _metadata_annotation_member(self, node: ast.expr) -> bool:
        parent = self.context.parents.get(node)
        if not isinstance(parent, ast.Tuple) or len(parent.elts) > _MAX_EXPANSION:
            return False
        owner = self.context.parents.get(parent)
        return (
            isinstance(owner, ast.Subscript)
            and owner.slice is parent
            and self._typing_symbol(owner.value) == "Annotated"
            and node in parent.elts[1:]
        )

    def _metadata_step(self, node: ast.Call) -> ast.expr | bool:
        if not _untouched(node.func, self.provenance):
            return False
        discriminator = next((keyword.value for keyword in node.keywords if keyword.arg == "discriminator"), None)
        if self._metadata_constructor(node.func, _DISCRIMINATOR_SOURCES, "Discriminator"):
            argument = node.args[0] if node.args else discriminator
            return argument is not None and not self._string_discriminator(argument)
        if self._metadata_constructor(node.func, _FIELD_SOURCES, "Field") and discriminator is not None:
            return discriminator
        return False

    def _metadata_aliases_discriminate(self, names: frozenset[str], *, callable_metadata: bool) -> bool:
        mutations = [self._metadata_mutated(name) for name in names]
        return any(mutation is None for mutation in mutations) or (callable_metadata and not any(mutations))

    def _metadata_mutated(self, name: str) -> bool | None:
        if name in self.metadata_mutation_cache:
            return self.metadata_mutation_cache[name]
        pending = [name]
        seen: set[str] = set()
        mutated = False
        for _ in range(_MAX_EXPANSION):
            if not pending:
                self.metadata_mutation_cache.update(dict.fromkeys(seen, mutated))
                return mutated
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self.provenance.external_bindings or self._metadata_escaped(current):
                return None
            if current in self.provenance.mutated:
                if not self._metadata_string_writes(current):
                    return None
                mutated = True
            pending.extend(self.metadata_aliases.get(current, set()).difference(seen))
        return None

    def _metadata_string_writes(self, name: str) -> bool:
        writes = self.metadata_writes.get(name, ())
        return (
            bool(writes)
            and len(writes) <= _MAX_EXPANSION
            and all(attribute == "discriminator" and self._string_discriminator(value) for attribute, value in writes)
        )

    def _metadata_escaped(self, name: str) -> bool:
        reads = self.provenance.reads.get(name, ())
        if len(reads) > _MAX_EXPANSION:
            return True
        bindings = self.provenance.bindings.get(self.context.tree, {}).get(name, ())
        if len(bindings) != 1:
            return True
        for read in reads:
            if self.provenance.binding(name, read) is not bindings[0]:
                continue
            node: ast.AST | None = read
            for _ in range(_MAX_EXPANSION):
                node = self.context.parents.get(node)
                if isinstance(node, ast.Call):
                    return True
                if node is None or isinstance(node, ast.stmt):
                    break
            else:
                return True
        return False

    def _metadata_constructor(self, node: ast.expr, sources: frozenset[str], symbol: str) -> bool:
        imports = self.context.module_imports
        return imports.resolves(node, sources=sources, symbol=symbol) or (
            isinstance(node, ast.Attribute)
            and node.attr == symbol
            and imports.resolved_qualified_name(node.value) in sources
        )

    def _string_discriminator(self, node: ast.expr) -> bool:
        pending = [_Expansion(node)]
        for _ in range(_MAX_EXPANSION):
            if not pending:
                return True
            item = pending.pop()
            node = item.node
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                continue
            if (
                isinstance(node, ast.Name)
                and node.id in self.values
                and node.id not in item.aliases
                and node.id not in self.provenance.mutated
                and node.id not in self.provenance.external_bindings
            ):
                pending.append(_Expansion(self.values[node.id], item.aliases | {node.id}))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                pending.extend(_Expansion(child, item.aliases) for child in (node.left, node.right))
            else:
                return False
        return False

    def _typing_symbol(self, node: ast.expr) -> str | None:
        if not _untouched(node, self.provenance):
            return None
        return self.context.module_imports.resolved_symbol(node, sources=TYPING_SOURCES)

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
        common.difference_update({name for name in common if name.startswith("__") and not name.endswith("__")})
        uncertain = False
        for name in sorted(common):
            domains = [self._field_domain(record.fields[name], required=record.required) for record in records]
            uncertain |= _uncertain_domains(domains)
            groups = _tag_groups(records, domains)
            if groups and all(len(group) == 1 or self._has_discriminator(group, budget) for group in groups):
                return True
        return uncertain

    def _field_domain(self, field: ast.AnnAssign, *, required: bool) -> _Domain:
        if _direct_initvar_field(field, self.context, self.provenance):
            return _Domain()
        node = field.annotation
        aliases: set[str] = set()
        for _ in range(_MAX_EXPANSION):
            parsed = _string_expression(node)
            if parsed is None:
                return _Domain(opaque=True)
            node = parsed
            if isinstance(node, ast.Name) and node.id in self.aliases:
                if node.id in aliases:
                    return _Domain(opaque=True)
                aliases.add(node.id)
                node = self.aliases[node.id]
                continue
            if not isinstance(node, ast.Subscript):
                break
            symbol = self._typing_symbol(node.value)
            if symbol == "ClassVar" and field.value is None:
                return _Domain()
            wrapped = _wrapped_annotation(node, symbol, required=required)
            if wrapped is None:
                break
            node, required = wrapped
        else:
            return _Domain(opaque=True)
        return self._literal_domain(node) if required else _Domain()

    def _literal_domain(self, expression: ast.expr) -> _Domain:
        leaves = self._leaves(expression)
        if leaves is None:
            return _Domain(opaque=True)
        domains = [self._leaf_domain(node) for node in leaves]
        if any(domain.opaque for domain in domains):
            return _Domain(opaque=True)
        values = frozenset(value for domain in domains for value in domain.values)
        if any(domain.unresolved for domain in domains):
            return _Domain(values, unresolved=True)
        if any(not domain.values for domain in domains):
            return _Domain()
        return _Domain(values)

    def _leaf_domain(self, node: ast.expr) -> _Domain:
        if isinstance(node, ast.Constant) and node.value is None:
            return _Domain(frozenset({_tag(None)}))
        if isinstance(node, ast.Name | ast.Attribute) and (
            (isinstance(node, ast.Name) and node.id in self.classes)
            or (
                _untouched(node, self.provenance)
                and self.context.module_imports.resolved_qualified_name(node) is not None
            )
        ):
            return _Domain(unresolved=True)
        if (
            isinstance(node, ast.Name)
            and node.id in _NON_LITERAL_BUILTINS
            and self.context.module_imports.builtin_is_unshadowed(node.id)
            and _untouched(node, self.provenance)
        ):
            return _Domain()
        if not isinstance(node, ast.Subscript):
            return _Domain(opaque=True)
        symbol = self._typing_symbol(node.value)
        if symbol == "Literal":
            return self._literal_values(node)
        if symbol is not None or (
            isinstance(node.value, ast.Name)
            and node.value.id in {"list", "dict", "tuple", "set", "frozenset", "type"}
            and self.context.module_imports.builtin_is_unshadowed(node.value.id)
            and _untouched(node.value, self.provenance)
        ):
            return _Domain()
        return _Domain(opaque=True)

    def _literal_values(self, node: ast.Subscript) -> _Domain:
        values: set[_Tag] = set()
        pending = [_Expansion(member) for member in _subscript_members(node)]
        for _ in range(_MAX_EXPANSION):
            if not pending:
                return _Domain(frozenset(values))
            piece = self._literal_piece(pending.pop())
            if isinstance(piece, list):
                pending.extend(piece)
                continue
            if piece.opaque:
                return piece
            values.update(piece.values)
        return _Domain(opaque=True)

    def _literal_piece(self, item: _Expansion) -> _Domain | list[_Expansion]:
        member = item.node
        if isinstance(member, ast.Name) and member.id in self.aliases:
            if member.id in item.aliases:
                return _Domain(opaque=True)
            parsed = _string_expression(self.aliases[member.id])
            if parsed is None:
                return _Domain(opaque=True)
            return [_Expansion(parsed, item.aliases | {member.id})]
        if isinstance(member, ast.Subscript):
            children = (
                _subscript_members(member)
                if self._typing_symbol(member.value) == "Literal"
                else self._union_members(member)
            )
            if children is not None:
                return [_Expansion(child, item.aliases) for child in children]
        return _literal_value(member)


def _wrapped_annotation(node: ast.Subscript, symbol: str | None, *, required: bool) -> tuple[ast.expr, bool] | None:
    if symbol in {"Required", "NotRequired"}:
        return node.slice, symbol == "Required"
    if symbol in {"ClassVar", "ReadOnly", "Final"}:
        return node.slice, required
    if symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
        return node.slice.elts[0], required
    return None


def _direct_initvar_field(field: ast.AnnAssign, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if field.value is not None or not isinstance(field.annotation, ast.Subscript):
        return False
    target = field.annotation.value
    if not _untouched(target, provenance) or not context.module_imports.resolves(
        target, sources=_DATACLASS_SOURCES, symbol="InitVar"
    ):
        return False
    owner = context.parents.get(field)
    if not isinstance(owner, ast.ClassDef):
        return False
    for decorator in owner.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _untouched(target, provenance) and context.module_imports.resolves(
            target, sources=_DATACLASS_SOURCES, symbol="dataclass"
        ):
            return True
    return False


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
    field_names = frozenset(fields)
    if any(_class_annotation_shadowed(field.annotation, field_names, context) for field in fields.values()):
        return None
    return _Record(fields, required)


def _class_annotation_shadowed(annotation: ast.expr, names: frozenset[str], context: PythonFileContext) -> bool:
    pending = [(annotation, True)]
    for _ in range(_MAX_EXPANSION):
        if not pending:
            return False
        node, forward = pending.pop()
        parsed = _string_expression(node) if forward else node
        if parsed is None or (isinstance(parsed, ast.Name) and parsed.id in names):
            return True
        pending.extend(_class_annotation_children(parsed, forward=forward, context=context))
    return True


def _class_annotation_children(
    node: ast.expr, *, forward: bool, context: PythonFileContext
) -> list[tuple[ast.expr, bool]]:
    if not isinstance(node, ast.Subscript):
        return [(child, forward) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)]
    members = _subscript_members(node)
    symbol = context.module_imports.resolved_symbol(node.value, sources=TYPING_SOURCES)
    if symbol == "Annotated" and members:
        return [(node.value, False), (members[0], True)]
    return [(node.value, False), *((member, symbol != "Literal") for member in members)]


def _record_required(node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool | None:
    if node.type_params:
        return None
    if any(not _untouched(base, provenance) for base in node.bases):
        return None
    decorators = [
        decorator
        for decorator in node.decorator_list
        if not (
            _untouched(decorator, provenance)
            and context.module_imports.resolves(decorator, sources=TYPING_SOURCES, symbol="final")
        )
    ]
    if decorators:
        return _direct_dataclass(node, context, provenance, decorators)
    if len(node.bases) != 1:
        return None
    if context.module_imports.resolves(node.bases[0], sources=MODEL_SOURCES, symbol="BaseModel"):
        return True if not node.keywords else None
    if not context.module_imports.resolves(node.bases[0], sources=TYPING_SOURCES, symbol="TypedDict"):
        return None
    required = True
    for keyword in node.keywords:
        if keyword.arg != "total" or not isinstance(keyword.value, ast.Constant):
            return None
        if not isinstance(keyword.value.value, bool):
            return None
        required = keyword.value.value
    return required


def _direct_dataclass(
    node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance, decorators: list[ast.expr]
) -> bool | None:
    if node.bases or node.keywords or len(decorators) != 1:
        return None
    decorator = decorators[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not _untouched(target, provenance) or not context.module_imports.resolves(
        target, sources=_DATACLASS_SOURCES, symbol="dataclass"
    ):
        return None
    return True


def _literal_value(node: ast.expr) -> _Domain:
    match node:
        case ast.Constant(value=(str() | bytes() | int()) as value):
            return _Domain(frozenset({_tag(value)}))
        case ast.Constant(value=None):
            return _Domain(frozenset({_tag(None)}))
        case ast.UnaryOp(op=op, operand=ast.Constant(value=int() as number)) if (
            isinstance(op, ast.USub | ast.UAdd) and type(number) is int
        ):
            return _Domain(frozenset({_tag(-number if isinstance(op, ast.USub) else number)}))
        case _:
            return _Domain(opaque=True)


def _subscript_members(node: ast.Subscript) -> tuple[ast.expr, ...]:
    return tuple(node.slice.elts) if isinstance(node.slice, ast.Tuple) else (node.slice,)


def _tag(value: str | bytes | int | None) -> _Tag:
    return type(value).__name__, value


def _tag_groups(records: list[_Record], domains: list[_Domain]) -> list[list[_Record]]:
    if any(not domain.values or domain.opaque or domain.unresolved for domain in domains):
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


def _namespace_metadata_value(node: ast.ClassDef, attribute: str) -> ast.expr | None:
    if node.bases or node.keywords or node.decorator_list or node.type_params or len(node.body) > _MAX_EXPANSION:
        return None
    values: list[tuple[str, ast.expr]] = []
    for member in node.body:
        binding = _value_binding(member)
        if binding is not None and not binding[0].startswith("__"):
            values.append(binding)
        elif isinstance(member, ast.Pass | ast.Expr) and (
            isinstance(member, ast.Pass)
            or (isinstance(member.value, ast.Constant) and isinstance(member.value.value, str))
        ):
            continue
        else:
            return None
    if len(values) != 1 or values[0][0] != attribute:
        return None
    return values[0][1]


def _metadata_tuple_index(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int:
        if isinstance(node.op, ast.USub):
            return -node.operand.value
        if isinstance(node.op, ast.UAdd):
            return node.operand.value
    return None


def _metadata_alias_graph(tree: ast.Module, bindings: dict[str, list[ast.AST]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for node in tree.body:
        binding = _value_binding(node)
        if binding is None:
            continue
        name, value = binding
        if len(bindings.get(name, ())) != 1 or not isinstance(value, ast.Name):
            continue
        graph.setdefault(name, set()).add(value.id)
        graph.setdefault(value.id, set()).add(name)
    return graph


def _metadata_attribute_writes(
    context: PythonFileContext, tree: ast.Module, provenance: ResourceProvenance
) -> dict[str, list[tuple[str, ast.expr]]]:
    writes: dict[str, list[tuple[str, ast.expr]]] = {}
    for target in context.nodes(ast.Attribute):
        if not isinstance(target.ctx, ast.Store) or not isinstance(target.value, ast.Name):
            continue
        binding = provenance.binding(target.value.id, target)
        if binding is None or provenance.scope(binding) is not tree or provenance.scope(target) is not tree:
            continue
        parent = context.parents.get(target)
        if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is not None:
            writes.setdefault(target.value.id, []).append((target.attr, parent.value))
    return writes


def _value_binding(node: ast.stmt) -> tuple[str, ast.expr] | None:
    match node:
        case (
            ast.Assign(targets=[ast.Name(id=name)], value=value)
            | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
        ):
            return name, value
        case _:
            return None


def _alias_value(
    node: ast.stmt, context: PythonFileContext, provenance: ResourceProvenance | None = None
) -> ast.expr | None:
    match node:
        case ast.TypeAlias(type_params=[]):
            return node.value
        case ast.AnnAssign(target=ast.Name(), annotation=annotation, value=value):
            return (
                value
                if context.module_imports.resolves(annotation, sources=TYPING_SOURCES, symbol="TypeAlias")
                and (provenance is None or _untouched(annotation, provenance))
                else None
            )
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


def _scoped_module_mutations(provenance: ResourceProvenance, tree: ast.Module) -> set[str]:
    original = provenance.mutated
    if not original:
        return original
    bindings = provenance.bindings.get(tree, {})
    owners = {name: bindings[name][0] for name in original if len(bindings.get(name, ())) == 1}
    writes = _module_attribute_mutations(provenance, owners)
    if writes is None:
        return original
    return {
        name
        for name in original
        if name not in owners or name in writes or _module_binding_escaped(name, owners[name], provenance)
    }


def _module_attribute_mutations(provenance: ResourceProvenance, owners: dict[str, ast.AST]) -> set[str] | None:
    changed: set[str] = set()
    count = 0
    for target in provenance.context.nodes(ast.Attribute):
        if not isinstance(target.ctx, ast.Store | ast.Del):
            continue
        count += 1
        if count > _MAX_EXPANSION:
            return None
        root: ast.expr = target
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id not in owners:
            continue
        binding = provenance.binding(root.id, target)
        if binding is None or binding is owners[root.id]:
            changed.add(root.id)
    return changed


def _module_binding_escaped(name: str, owner: ast.AST, provenance: ResourceProvenance) -> bool:
    reads = provenance.reads.get(name, ())
    if len(reads) > _MAX_EXPANSION:
        return True
    return any(
        provenance.binding(name, read) is owner and _module_read_escapes(read, provenance.context) for read in reads
    )


def _module_read_escapes(read: ast.Name, context: PythonFileContext) -> bool:
    current: ast.AST = read
    for _ in range(_MAX_EXPANSION):
        parent = context.parents.get(current)
        if parent is None:
            return False
        step = _module_escape_step(parent, current, context)
        if step is not None:
            return step
        current = parent
    return True


def _module_escape_step(parent: ast.AST, current: ast.AST, context: PythonFileContext) -> bool | None:
    match parent:
        case ast.Call():
            return parent.func is not current
        case ast.Return() | ast.Yield() | ast.YieldFrom() | ast.NamedExpr():
            return True
        case ast.arguments():
            return True if current in parent.defaults or current in parent.kw_defaults else None
        case ast.Assign() | ast.AnnAssign() | ast.AugAssign():
            value = parent.value
            return value is not None and value is current and not _union_expression(value, context)
        case ast.Subscript() if parent.value is not current:
            symbol = context.module_imports.resolved_symbol(parent.value, sources=TYPING_SOURCES)
            if symbol is None:
                return True
        case ast.withitem():
            return parent.context_expr is current
        case _:
            pass
    return False if isinstance(parent, ast.stmt) else None


def _untouched(node: ast.expr, provenance: ResourceProvenance) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    if not isinstance(node, ast.Name) or node.id in provenance.mutated or node.id in provenance.external_bindings:
        return False
    binding = provenance.binding(node.id, node)
    return binding is None or isinstance(binding, ast.alias)


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
        symbol = context.module_imports.resolved_symbol(node.value, sources=TYPING_SOURCES)
        if symbol == "Union":
            return True
        if symbol == "Optional":
            node = node.slice
        elif symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            node = node.slice.elts[0]
        else:
            return False
    return False
