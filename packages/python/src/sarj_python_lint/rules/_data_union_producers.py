from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, TypeGuard, final

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins, annotation_reference
from sarj_python_lint.rules._data_union_discriminator import record_required
from sarj_python_lint.rules._declared_contracts import DeclaredContracts
from sarj_python_lint.rules._nullable_outcome import nullable_annotation, nullable_outcome_field, record_fields
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef
from sarj_python_lint.rules._pydantic_field_contract import MODEL_SOURCES, TYPING_SOURCES, model_namespace_hazards


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_MODEL_FIELDS = frozenset({"pydantic.Field", "pydantic.fields.Field"})
_MODEL_CONFIGS = frozenset({"pydantic.ConfigDict", "pydantic.config.ConfigDict"})
_MODEL_BASES = frozenset(f"{module}.BaseModel" for module in MODEL_SOURCES)
_PASSIVE_CONFIG = frozenset({"frozen", "strict", "extra", "hide_input_in_errors"})
_PASSIVE_FIELDS = frozenset({"default", "description", "title", "examples", "repr"})
_REPLACE = frozenset({"copy.replace", "dataclasses.replace"})
_VALUE_CALLS = frozenset({"str", "int", "float", "bool", "bytes", "len", "list", "dict", "tuple", "set", "frozenset"})


@dataclass(frozen=True, slots=True)
class _Domain:
    values: frozenset[str]
    enum: SymbolRef | None = None


@dataclass(frozen=True, slots=True)
class _Record:
    model: ast.ClassDef
    tags: dict[str, _Domain]
    payloads: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Producer:
    facts: AnnotationOrigins
    unit: SourceUnit
    keywords: dict[str, ast.expr]


@final
class ProducerCorrelations:
    def __init__(self, project: ProjectIndexSet) -> None:
        self.project = project
        self._session = AnalysisSession()
        self._session.project = project

    def diagnostics(self, context: PythonFileContext, code: str) -> list[Diagnostic]:
        unit = self.project.unit(context.path)
        if unit is None or unit.module is None or unit.source != context.source:
            return []
        return [
            Diagnostic(context.path, model.lineno, model.col_offset + 1, code, message, severity=Severity.ERROR)
            for model, message in self._findings.get(unit.module, ())
            if not context.suppressions.is_suppressed(model.lineno, code)
        ]

    @cached_property
    def _findings(self) -> dict[str, list[tuple[ast.ClassDef, str]]]:
        records = self._records()
        findings: dict[str, list[tuple[ast.ClassDef, str]]] = {}
        for symbol, producers in self._producers(frozenset(records)).items():
            record = records[symbol]
            if (message := _message(record, producers)) is not None:
                findings.setdefault(symbol.module, []).append((record.model, message))
        return findings

    def _records(self) -> dict[SymbolRef, _Record]:
        records: dict[SymbolRef, _Record] = {}
        for unit in self.project.source_units:
            if unit.tree is None or unit.module is None or self.project.source_unit(unit.module) is not unit:
                continue
            if is_test_path(unit.path) or is_test_support_path(unit.path) or unit.path.suffix != ".py":
                continue
            context = PythonFileContext(unit.path, unit.source, self._session)
            if context.generated:
                continue
            records.update(
                (SymbolRef(unit.module, record.model.name), record)
                for record in self._unit_records(unit, context, unit.tree)
            )
        return records

    def _unit_records(self, unit: SourceUnit, context: PythonFileContext, tree: ast.Module) -> Iterator[_Record]:
        typed_dict_hint = "TypedDict" in unit.source
        models = [node for node in tree.body if _potential_record(node, typed_dict_hint=typed_dict_hint)]
        if not models or model_namespace_hazards(context, escape_symbols=_MODEL_FIELDS | _MODEL_BASES):
            return
        facts = AnnotationOrigins(context)
        for model in models:
            if (record := self._model_record(unit, model, facts)) is not None:
                yield record

    def _model_record(self, unit: SourceUnit, model: ast.ClassDef, facts: AnnotationOrigins) -> _Record | None:
        pydantic = len(model.bases) == 1 and facts.qualified(model.bases[0], model.bases[0]) in _MODEL_BASES
        required = True if pydantic else record_required(model, facts.context, facts.provenance, {})
        if required is None or facts.provenance.bindings.get(unit.tree, {}).get(model.name) != (model,):
            return None
        fields = record_fields(model, facts)
        if (
            not _passive_record(model, facts, pydantic=pydantic)
            or nullable_outcome_field(model, fields, facts) is not None
        ):
            return None
        typed_dict = bool(model.bases) and facts.context.module_imports.resolves(
            model.bases[0], sources=TYPING_SOURCES, symbol="TypedDict"
        )
        payloads = tuple(
            name
            for name, field in fields.items()
            if _nullable_payload(field, facts, required=required, typed_dict=typed_dict)
        )
        if not payloads:
            return None
        tags = {
            name: domain
            for name, field in fields.items()
            if (domain := self._domain(field.annotation, facts, unit)) is not None
        }
        return _Record(model, tags, payloads) if tags else None

    def _domain(self, annotation: ast.expr, facts: AnnotationOrigins, unit: SourceUnit) -> _Domain | None:
        resolved = facts.resolve_annotation(annotation)
        if resolved is None:
            return None
        node, at = resolved.expression, resolved.at
        if facts.builtin(node, "bool", at) or facts.qualified(node, at) == "builtins.bool":
            return _Domain(frozenset({"True", "False"}))
        if isinstance(node, ast.Subscript) and facts.qualified(node.value, at) in {
            "typing.Literal",
            "typing_extensions.Literal",
        }:
            return _literal_domain(node)
        symbol = _resolved_symbol(unit, node, facts, at=at)
        owner = self.project.source_unit(symbol.module) if symbol is not None else None
        if owner is None or owner.tree is None or symbol is None:
            return None
        enum_facts = (
            facts if owner is unit else AnnotationOrigins(PythonFileContext(owner.path, owner.source, self._session))
        )
        return _enum_domain(symbol, owner.tree, enum_facts)

    def _producers(self, records: frozenset[SymbolRef]) -> dict[SymbolRef, list[_Producer]]:
        if not records:
            return {}
        contexts: dict[Path, AnnotationOrigins] = {}
        calls: dict[SymbolRef, list[_Producer]] = {}
        blocked: set[SymbolRef] = set()
        for unit, reference, targets in self.project.class_references(records):
            if reference is None or (unit.module is not None and self.project.source_unit(unit.module) is not unit):
                blocked.update(targets)
                continue
            if unit.path not in contexts:
                contexts[unit.path] = AnnotationOrigins(PythonFileContext(unit.path, unit.source, self._session))
            facts = contexts[unit.path]
            context = facts.context
            parent = context.parents.get(reference)
            if annotation_reference(reference, context):
                continue
            if (
                not isinstance(parent, ast.Call)
                or parent.func is not reference
                or (target := _resolved_symbol(unit, reference, facts)) is None
                or targets != {target}
                or (producer := _producer(parent, facts, unit)) is None
            ):
                blocked.update(targets)
            else:
                calls.setdefault(target, []).append(producer)
        if not self.project.value_origins_complete:
            return {}
        blocked.update(self._replaced_records())
        return {symbol: producers for symbol, producers in calls.items() if symbol not in blocked}

    def _replaced_records(self) -> Iterator[SymbolRef]:
        for unit in self.project.source_units:
            if is_test_path(unit.path) or is_test_support_path(unit.path) or unit.tree is None:
                continue
            if "model_copy" not in unit.source and "replace" not in unit.source:
                continue
            context = PythonFileContext(unit.path, unit.source, self._session)
            facts = AnnotationOrigins(context)
            contracts = DeclaredContracts(context)
            for call in context.nodes(ast.Call):
                if (receiver := _replacement_receiver(call, context)) is not None and (
                    symbol := _receiver_symbol(unit, receiver, facts, contracts)
                ) is not None:
                    yield symbol


def _potential_record(node: ast.stmt, *, typed_dict_hint: bool) -> TypeGuard[ast.ClassDef]:
    return (
        isinstance(node, ast.ClassDef)
        and not node.type_params
        and (
            typed_dict_hint
            or any(isinstance(field, ast.AnnAssign) and _none_default(field.value) for field in node.body)
        )
    )


def _nullable_payload(field: ast.AnnAssign, facts: AnnotationOrigins, *, required: bool, typed_dict: bool) -> bool:
    omitted = _omittable_key(field, facts, required=required) if typed_dict else _none_default(field.value)
    return omitted and not _is_none(field.annotation) and nullable_annotation(field.annotation, facts)


def _literal_domain(node: ast.Subscript) -> _Domain | None:
    literals = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    values: set[str] = set()
    for literal in literals:
        if (value := _literal_tag(literal)) is None:
            return None
        values.add(value)
    return _Domain(frozenset(values)) if len(values) > 1 else None


def _resolved_symbol(
    unit: SourceUnit, expression: ast.expr, facts: AnnotationOrigins, *, at: ast.expr | None = None
) -> SymbolRef | None:
    if not isinstance(expression, ast.Name | ast.Attribute):
        return None
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    provenance = facts.provenance
    if (
        not isinstance(root, ast.Name)
        or root.id in provenance.mutated | provenance.external_bindings
        or provenance.wildcard
        or provenance.dynamic_namespace
    ):
        return None
    binding = provenance.runtime_binding(root.id, root) if at is None else facts.binding(root.id, at)
    if isinstance(binding, ast.ClassDef) and expression is root and provenance.scope(binding) is unit.tree:
        return ProjectIndexSet.resolve(unit, root)
    parent = facts.context.parents.get(binding) if binding is not None else None
    if isinstance(parent, ast.Import | ast.ImportFrom):
        return ProjectIndexSet.imported_symbol(unit, expression, parent)
    return None


def _enum_domain(symbol: SymbolRef, tree: ast.Module, facts: AnnotationOrigins) -> _Domain | None:
    provenance = facts.provenance
    if (
        provenance.wildcard
        or provenance.dynamic_namespace
        or symbol.name in provenance.mutated | provenance.external_bindings
    ):
        return None
    bindings = provenance.bindings.get(tree, {}).get(symbol.name, ())
    if len(bindings) != 1 or not isinstance(model := bindings[0], ast.ClassDef):
        return None
    if (
        model.keywords
        or model.decorator_list
        or len(model.bases) != 1
        or facts.qualified(model.bases[0], model.bases[0]) not in {"enum.Enum", "enum.StrEnum"}
    ):
        return None
    members: dict[str, str | int | bytes] = {}
    for statement in model.body:
        match statement:
            case ast.Expr(value=ast.Constant(value=str())):
                continue
            case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=(str() | int() | bytes()) as value)):
                if name.startswith("_") or name in members or value in members.values():
                    return None
                members[name] = value
            case _:
                return None
    return _Domain(frozenset(members), symbol) if len(members) > 1 else None


def _passive_record(model: ast.ClassDef, facts: AnnotationOrigins, *, pydantic: bool) -> bool:
    if pydantic and (
        model.decorator_list
        or any(kw.arg not in _PASSIVE_CONFIG or not isinstance(kw.value, ast.Constant) for kw in model.keywords)
    ):
        return False
    return all(_passive_member(member, facts, pydantic=pydantic) for member in model.body) and all(
        not decorator.args
        and all(
            keyword.arg is not None
            and (keyword.arg != "init" or (isinstance(keyword.value, ast.Constant) and keyword.value.value is True))
            for keyword in decorator.keywords
        )
        for decorator in model.decorator_list
        if isinstance(decorator, ast.Call)
    )


def _passive_member(member: ast.stmt, facts: AnnotationOrigins, *, pydantic: bool) -> bool:
    match member:
        case (
            ast.AnnAssign(target=ast.Name(id="model_config"), value=ast.Call() as value)
            | ast.Assign(targets=[ast.Name(id="model_config")], value=ast.Call() as value)
        ) if pydantic:
            return _plain_options(value, facts, _MODEL_CONFIGS, _PASSIVE_CONFIG)
        case ast.AnnAssign(target=ast.Name(), value=ast.Call() as value):
            return (
                _plain_options(value, facts, _MODEL_FIELDS, _PASSIVE_FIELDS, positional=True)
                if pydantic
                else _plain_options(value, facts, frozenset({"dataclasses.field"}), frozenset({"default", "repr"}))
            )
        case (
            ast.AnnAssign(target=ast.Name(), value=ast.Constant() | None)
            | ast.Pass()
            | ast.Expr(value=ast.Constant(value=str()))
        ):
            return True
        case _:
            return False


def _plain_options(
    value: ast.Call,
    facts: AnnotationOrigins,
    constructors: frozenset[str],
    options: frozenset[str],
    *,
    positional: bool = False,
) -> bool:
    return (
        facts.qualified(value.func, value) in constructors
        and len(value.args) <= int(positional)
        and all(isinstance(arg, ast.Constant) for arg in value.args)
        and all(keyword.arg in options and isinstance(keyword.value, ast.Constant) for keyword in value.keywords)
    )


def _omittable_key(field: ast.AnnAssign, facts: AnnotationOrigins, *, required: bool) -> bool:
    resolved = facts.resolve_annotation(field.annotation)
    if field.value is not None or resolved is None:
        return False
    outer, at = resolved.expression, resolved.at
    if isinstance(outer, ast.Subscript):
        wrapper = facts.qualified(outer.value, at)
        if wrapper in {"typing.NotRequired", "typing_extensions.NotRequired"}:
            return True
        if wrapper in {"typing.Required", "typing_extensions.Required"}:
            return False
    return not required


def _none_default(value: ast.expr | None) -> bool:
    return _is_none(value) or (
        isinstance(value, ast.Call)
        and (
            any(_is_none(arg) for arg in value.args)
            or any(k.arg == "default" and _is_none(k.value) for k in value.keywords)
        )
    )


def _producer(call: ast.Call, facts: AnnotationOrigins, unit: SourceUnit) -> _Producer | None:
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}
    if call.args or len(keywords) != len(call.keywords):
        return None
    return _Producer(facts, unit, keywords)


def _replacement_receiver(call: ast.Call, context: PythonFileContext) -> ast.expr | None:
    if isinstance(call.func, ast.Attribute) and call.func.attr == "model_copy":
        return call.func.value if any(kw.arg in {"update", None} for kw in call.keywords) else None
    if context.static_resource_provenance.runtime_import_name(call.func) in _REPLACE:
        return call.args[0] if call.args else next((kw.value for kw in call.keywords if kw.arg == "obj"), None)
    return None


def _receiver_symbol(
    unit: SourceUnit, receiver: ast.expr, facts: AnnotationOrigins, contracts: DeclaredContracts
) -> SymbolRef | None:
    if (model := contracts.value(receiver)) is not None and model.unit.module is not None:
        return SymbolRef(model.unit.module, model.declaration.name)
    value = receiver
    if isinstance(receiver, ast.Name):
        binding = facts.provenance.binding(receiver.id, receiver)
        parent = facts.context.parents.get(binding) if binding is not None else None
        declaration = binding if isinstance(binding, ast.arg) else parent
        if (
            isinstance(declaration, ast.arg | ast.AnnAssign)
            and declaration.annotation is not None
            and (annotation := facts.resolve_annotation(declaration.annotation)) is not None
        ):
            return _resolved_symbol(unit, annotation.expression, facts, at=annotation.at)
        if (constructor := facts.provenance.constructor(receiver, receiver)) is not None:
            value = constructor
    return _resolved_symbol(unit, value.func, facts) if isinstance(value, ast.Call) else None


def _is_none(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is None


def _literal_tag(value: ast.expr) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str | int | bytes):
        return repr(value.value)
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, ast.USub)
        and isinstance(value.operand, ast.Constant)
        and type(value.operand.value) is int
    ):
        return repr(-value.operand.value)
    return None


def _message(record: _Record, producers: list[_Producer]) -> str | None:
    correlations: dict[str, str] = {}
    for tag, domain in record.tags.items():
        grouped = _grouped_producers(producers, tag, domain)
        for payload in record.payloads:
            if present := _present_tags(grouped, payload):
                correlations.setdefault(payload, f"`{payload}` with `{tag}` in {{{', '.join(present)}}}")
    if not correlations:
        return None
    return (
        f"Constructors of `{record.model.name}` consistently supply {', '.join(correlations.values())} only. "
        "Consider a discriminated model union with required payloads in the matching variants."
    )


def _grouped_producers(producers: list[_Producer], field: str, domain: _Domain) -> dict[str, list[_Producer]]:
    grouped: dict[str, list[_Producer]] = {}
    for producer in producers:
        if (tag := _tag_value(producer, field, domain)) is None:
            return {}
        grouped.setdefault(tag, []).append(producer)
    return grouped


def _present_tags(grouped: dict[str, list[_Producer]], payload: str) -> list[str]:
    present: list[str] = []
    for tag, producers in grouped.items():
        states = {_present(producer.keywords.get(payload), producer.facts) for producer in producers}
        if states == {True}:
            present.append(tag)
        elif states != {False}:
            return []
    return sorted(present) if len(present) < len(grouped) else []


def _tag_value(producer: _Producer, field: str, domain: _Domain) -> str | None:
    value = producer.keywords.get(field)
    if value is None:
        return None
    if domain.enum is None:
        literal = _literal_tag(value)
        return literal if literal in domain.values else None
    if (
        isinstance(value, ast.Attribute)
        and value.attr in domain.values
        and _resolved_symbol(producer.unit, value.value, producer.facts) == domain.enum
    ):
        return f"{domain.enum.name}.{value.attr}"
    return None


def _present(value: ast.expr | None, facts: AnnotationOrigins) -> bool | None:
    if value is None or _is_none(value):
        return False
    if (
        isinstance(value, ast.Constant | ast.JoinedStr | ast.List | ast.Dict | ast.Tuple | ast.Set)
        or _literal_tag(value) is not None
    ):
        return True
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        name = value.func.id
        if name in _VALUE_CALLS and facts.builtin(value.func, name, value.func):
            return True
    return None
