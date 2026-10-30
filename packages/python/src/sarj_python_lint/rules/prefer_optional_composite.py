from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, bit_or_members, scope_bound_names
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pydantic_field_contract import unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_MIN_GROUP = 2
_TYPING = ("typing", "typing_extensions")
_MAX_ALIAS_DEPTH = 32
_PYDANTIC_BASES = frozenset({"pydantic.BaseModel", "pydantic.main.BaseModel"})
_ANNOTATION_NAMES = frozenset({"__annotations__", "__annotate__", "__annotate_func__"})


@final
class PreferOptionalComposite(Rule):
    id = "prefer-optional-composite"
    code = "SARJ541"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Review related optional fields as one optional composite value.",
        rationale=(
            "Several nullable fields with a common record prefix can scatter one optional value across "
            "a larger model, requiring repeated presence checks and obscuring which partial states are intentional. "
            "A nested value can give that concept one boundary while retaining independently nullable children."
        ),
        remediation=(
            "Review whether the fields represent one value and, if so, introduce a typed composite with one optional "
            "outer field. Preserve valid partial states, omitted-key behavior, defaults, aliases, validation and "
            "wire/storage compatibility. Keep independent optional children nullable. A shared prefix does not "
            "prove that all fields must be present together."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is a broad modeling review warning, not proof of an all-or-nothing invariant or an invalid runtime state. A shared underscore-delimited prefix and at least two explicitly nullable fields are the deterministic trigger; independent same-prefix settings can also match and should remain independent when that is their contract.",
            "Checks stable direct module-level source-declared Pydantic BaseModels, plain direct dataclasses and TypedDicts. This advisory relationship follows unshadowed runtime model imports and explicit namespace writes, without proving the runtime effects of unrelated callbacks. PEP 604, Optional, Union, Annotated, quoted annotations and bounded module type aliases are recognized; container-element nullability alone is not field nullability. Runtime ClassVar metadata and dataclass InitVar/KW_ONLY metadata are excluded; dataclasses retain Annotated metadata wrappers and PEP 695 metadata aliases as fields. A required or unresolved same-prefix sibling prevents grouping that broader prefix.",
            "Larger overlapping groups take precedence, with the longest common prefix for the same field set. Each field belongs to at most one finding. Inherited/generic models, unknown decorators or namespaces, replaced annotation providers, rebound owners, tests, generated and vendor code are excluded.",
            "The rule does not infer relationships from shared suffixes, enforce non-null child fields or automatically nest public models. SARJ510 owns proven tag-dependent variant payloads.",
        ),
        examples=(
            RuleExample(
                example_id="scattered-optional-value",
                title="Review a usage value split across nullable fields",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass State(BaseModel):\n"
                        "    in_use_by: str | None\n    in_use_by_name: str | None\n    in_use_since: str | None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="one-optional-composite",
                title="A present usage value can still have an unavailable actor name",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass Usage(BaseModel):\n"
                        "    actor_id: str\n    actor_name: str | None\n    since: str\n"
                        "class State(BaseModel):\n    in_use: Usage | None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
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
        if not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts):
            return []
        provenance = context.static_resource_provenance
        if provenance.wildcard or provenance.dynamic_namespace:
            return []
        findings: list[Diagnostic] = []
        pydantic_imports_stable = _pydantic_imports_stable(context, provenance)
        for model in context.tree.body:
            if (
                not isinstance(model, ast.ClassDef)
                or provenance.binding(model.name, model) is not model
                or model.name in provenance.mutated
                or not _ANNOTATION_NAMES.isdisjoint(scope_bound_names(model.body))
            ):
                continue
            if not (pydantic_imports_stable and _pydantic_record(model, context, provenance)) and not _plain_record(
                model, context, provenance
            ):
                continue
            findings.extend(_model_diagnostics(model, context, self.code))
        return findings


def _model_diagnostics(model: ast.ClassDef, context: PythonFileContext, code: str) -> list[Diagnostic]:
    fields = _optional_fields(model, context)
    findings: list[Diagnostic] = []
    for prefix, group in _field_groups(fields, _required_names(model, fields, context)):
        anchor = group[0]
        if is_suppressed(context.source_lines, anchor.lineno, code):
            continue
        names = ", ".join(f"`{field.target.id}`" for field in group if isinstance(field.target, ast.Name))
        findings.append(
            Diagnostic(
                context.path,
                anchor.lineno,
                anchor.col_offset + 1,
                code,
                f"Review {model.name}'s nullable {prefix}_ fields ({names}) as one optional composite. "
                "Preserve independent child nullability and valid partial states; names alone do not "
                "prove an all-or-nothing invariant or authorize a wire/storage change.",
                severity=Severity.WARNING,
            )
        )
    return findings


def _pydantic_record(model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    return (
        not model.type_params
        and not model.decorator_list
        and not model.keywords
        and len(model.bases) == 1
        and _pydantic_base(model.bases[0], context, provenance)
        and all(
            isinstance(member, ast.AnnAssign | ast.Assign | ast.FunctionDef | ast.AsyncFunctionDef | ast.Pass)
            or _plain_member(member)
            for member in model.body
        )
    )


def _pydantic_base(base: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    root = base
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in provenance.mutated:
        return False
    binding = provenance.runtime_binding(root.id, base)
    statement = provenance.parents.get(binding) if isinstance(binding, ast.alias) else None
    return (
        isinstance(statement, ast.Import | ast.ImportFrom)
        and provenance.parents.get(statement) is context.tree
        and _stable_qualified_name(base, context) in _PYDANTIC_BASES
    )


def _pydantic_imports_stable(context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    tree = context.tree
    if tree is None or not tree.body:
        return False
    for name, target in context.module_imports.bindings.items():
        qualified = f"{target.module}.{target.symbol}" if target.symbol is not None else target.module
        if qualified not in _PYDANTIC_BASES | {"pydantic", "pydantic.main"} or name not in provenance.reads:
            continue
        binding = provenance.runtime_binding(name, tree.body[0])
        if not isinstance(binding, ast.alias):
            return False
        for read in provenance.reads.get(name, ()):
            resolved = provenance.runtime_binding(name, read)
            lexical = provenance.binding(name, read)
            uncertain_class_capture = (
                resolved is None and lexical is not None and isinstance(provenance.scope(lexical), ast.ClassDef)
            )
            if (
                resolved is binding or (resolved is None and lexical is binding) or uncertain_class_capture
            ) and not _pydantic_import_read(read, context):
                return False
    return True


def _pydantic_import_read(read: ast.Name, context: PythonFileContext) -> bool:
    reference: ast.expr = read
    parent = context.parents.get(reference)
    while isinstance(parent, ast.Attribute) and parent.value is reference:
        reference, parent = parent, context.parents.get(parent)
    qualified = context.module_imports.resolved_qualified_name(reference)
    if qualified is not None and not any(
        qualified == base or qualified.startswith(f"{base}.") for base in _PYDANTIC_BASES
    ):
        return True
    if (isinstance(parent, ast.Call) and parent.func is reference) or (
        isinstance(parent, ast.ClassDef) and reference in parent.bases
    ):
        return True
    while isinstance(parent, ast.expr) and not isinstance(parent, ast.Call):
        reference, parent = parent, context.parents.get(parent)
    return (isinstance(parent, ast.AnnAssign | ast.arg) and parent.annotation is reference) or (
        isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is reference
    )


def _plain_record(model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if model.type_params or any(not _plain_member(member) for member in model.body):
        return False
    if len(model.decorator_list) == 1 and not model.bases and not model.keywords:
        decorator = model.decorator_list[0]
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        return _stable_qualified_name(target, context) == "dataclasses.dataclass" and provenance.imported(
            target, "dataclasses.dataclass"
        )
    return (
        not model.decorator_list
        and len(model.bases) == 1
        and any(provenance.imported(model.bases[0], f"{module}.TypedDict") for module in _TYPING)
        and all(
            keyword.arg == "total" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool)
            for keyword in model.keywords
        )
    )


def _plain_member(member: ast.stmt) -> bool:
    return isinstance(member, ast.AnnAssign | ast.Pass) or (
        isinstance(member, ast.Expr) and isinstance(member.value, ast.Constant) and isinstance(member.value.value, str)
    )


def _optional_fields(model: ast.ClassDef, context: PythonFileContext) -> list[ast.AnnAssign]:
    unique = unique_members(model)
    class_names = scope_bound_names(model.body)
    fields: list[ast.AnnAssign] = []
    for member in model.body:
        if not isinstance(member, ast.AnnAssign) or not isinstance(member.target, ast.Name):
            continue
        name = member.target.id
        if name.startswith("_") or name not in unique or "_" not in name:
            continue
        if _optional_annotation(member.annotation, class_names, context, dataclass=bool(model.decorator_list)):
            fields.append(member)
    return fields


def _optional_annotation(
    annotation: ast.expr, class_names: set[str], context: PythonFileContext, *, dataclass: bool
) -> bool:
    parsed = _unshadowed_annotation(annotation, class_names)
    return (
        parsed is not None
        and not _metadata_annotation(parsed, context, dataclass=dataclass)
        and _nullable(parsed, context)
    )


def _unshadowed_annotation(annotation: ast.expr, class_names: set[str]) -> ast.expr | None:
    parsed = AnnotationSemantics.parse(annotation)
    if parsed is None or any(isinstance(node, ast.Name) and node.id in class_names for node in ast.walk(parsed)):
        return None
    return parsed


def _stable_qualified_name(expression: ast.expr, context: PythonFileContext) -> str | None:
    qualified = context.module_imports.resolved_qualified_name(expression)
    if qualified is None:
        return None
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    tree = context.tree
    if (
        not isinstance(root, ast.Name)
        or tree is None
        or not tree.body
        or not isinstance(context.static_resource_provenance.runtime_binding(root.id, tree.body[0]), ast.alias)
    ):
        return None
    owner = qualified.partition(".")[0]
    for name in context.static_resource_provenance.mutated:
        binding = context.module_imports.bindings.get(name)
        if binding is not None and binding.module.partition(".")[0] == owner:
            return None
    return qualified


def _nullable(annotation: ast.expr, context: PythonFileContext, *, seen: frozenset[str] = frozenset()) -> bool:
    if len(seen) >= _MAX_ALIAS_DEPTH:
        return False
    parsed = AnnotationSemantics.parse(annotation)
    if parsed is None:
        return False
    if isinstance(parsed, ast.Name) and parsed.id in context.annotation_semantics.aliases:
        if parsed.id in seen:
            return False
        return _nullable(context.annotation_semantics.aliases[parsed.id], context, seen=seen | {parsed.id})
    if isinstance(parsed, ast.BinOp) and isinstance(parsed.op, ast.BitOr):
        return _nullable_union(bit_or_members(parsed), context, seen)
    if not isinstance(parsed, ast.Subscript):
        return False
    qualified = _stable_qualified_name(parsed.value, context)
    wrapper = (
        qualified.rpartition(".")[2] if qualified is not None and qualified.rpartition(".")[0] in _TYPING else None
    )
    if wrapper == "Optional":
        return True
    members = parsed.slice.elts if isinstance(parsed.slice, ast.Tuple) else [parsed.slice]
    if wrapper == "Union":
        return _nullable_union(members, context, seen)
    return (
        wrapper in {"Annotated", "Required", "NotRequired", "ReadOnly"}
        and bool(members)
        and _nullable(members[0], context, seen=seen)
    )


def _nullable_union(members: list[ast.expr], context: PythonFileContext, seen: frozenset[str]) -> bool:
    return any(
        (isinstance(member, ast.Constant) and member.value is None) or _nullable(member, context, seen=seen)
        for member in members
    )


def _required_names(model: ast.ClassDef, optional: list[ast.AnnAssign], context: PythonFileContext) -> frozenset[str]:
    optional_nodes = {id(member) for member in optional}
    class_names = scope_bound_names(model.body)
    required: set[str] = set()
    for member in model.body:
        if (
            not isinstance(member, ast.AnnAssign)
            or not isinstance(member.target, ast.Name)
            or id(member) in optional_nodes
            or member.target.id.startswith("_")
        ):
            continue
        parsed = _unshadowed_annotation(member.annotation, class_names)
        if parsed is None or not _metadata_annotation(parsed, context, dataclass=bool(model.decorator_list)):
            required.add(member.target.id)
    return frozenset(required)


def _metadata_annotation(
    annotation: ast.expr,
    context: PythonFileContext,
    *,
    dataclass: bool,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if len(seen) >= _MAX_ALIAS_DEPTH:
        return False
    resolved = AnnotationSemantics.parse(annotation)
    if isinstance(resolved, ast.Name) and resolved.id in context.annotation_semantics.aliases:
        bindings = context.static_resource_provenance.bindings.get(context.tree, {}).get(resolved.id, ())
        if resolved.id in seen or len(bindings) != 1 or not isinstance(context.parents.get(bindings[0]), ast.AnnAssign):
            return False
        return _metadata_annotation(
            context.annotation_semantics.aliases[resolved.id],
            context,
            dataclass=dataclass,
            seen=seen | {resolved.id},
        )
    if resolved is None:
        return False
    target = resolved.value if isinstance(resolved, ast.Subscript) else resolved
    qualified = _stable_qualified_name(target, context)
    if qualified in {f"{module}.ClassVar" for module in _TYPING} or (
        dataclass
        and (
            qualified == "dataclasses.InitVar"
            or (qualified == "dataclasses.KW_ONLY" and not isinstance(resolved, ast.Subscript))
        )
    ):
        return True
    if (
        not dataclass
        and isinstance(resolved, ast.Subscript)
        and qualified in {f"{module}.Annotated" for module in _TYPING}
    ):
        first = (
            resolved.slice.elts[0] if isinstance(resolved.slice, ast.Tuple) and resolved.slice.elts else resolved.slice
        )
        return _metadata_annotation(first, context, dataclass=dataclass, seen=seen)
    return False


def _field_groups(fields: list[ast.AnnAssign], required: frozenset[str]) -> list[tuple[str, list[ast.AnnAssign]]]:
    candidates: dict[str, list[ast.AnnAssign]] = defaultdict(list)
    for field in fields:
        if not isinstance(field.target, ast.Name):
            continue
        parts = field.target.id.split("_")
        for size in range(1, len(parts)):
            if all(parts[:size]):
                candidates["_".join(parts[:size])].append(field)
    ranked = sorted(candidates.items(), key=lambda item: (-len(item[1]), -len(item[0]), item[0]))
    consumed: set[int] = set()
    groups: list[tuple[str, list[ast.AnnAssign]]] = []
    for prefix, group in ranked:
        if (
            len(group) < _MIN_GROUP
            or any(id(field) in consumed for field in group)
            or any(name.startswith(f"{prefix}_") for name in required)
        ):
            continue
        consumed.update(id(field) for field in group)
        groups.append((prefix, group))
    return sorted(groups, key=lambda item: item[1][0].lineno)
