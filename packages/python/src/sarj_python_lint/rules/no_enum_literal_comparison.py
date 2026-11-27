from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, module_rebindings, scope_bound_names
from sarj_python_lint.rules._enum_declarations import class_enum_members, stdlib_enum_base
from sarj_python_lint.rules._nominal_project import NominalSource
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet


_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum"})
_VALUE_COMPATIBLE_BASES = frozenset({"StrEnum", "IntEnum"})
_VALUE_LIKE_BASES = frozenset({"str", "int"})
_MAX_RESOLUTION_DEPTH = 8

_EXAMPLE = """\
from enum import StrEnum

class Action(StrEnum):
    BUILD = "build"

def is_build(action: Action) -> bool:
    return action == "build"
"""


@dataclass(frozen=True, slots=True)
class _Class:
    source: NominalSource
    declaration: ast.ClassDef


@final
class NoEnumLiteralComparison(ProjectRule):
    id: str = "no-enum-literal-comparison"
    code: str = "SARJ612"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Compare enum values using named members.",
        rationale=(
            "Raw comparisons bypass the enum declaration. A typo or change to an enum member can silently leave "
            "a comparison or match arm out of sync."
        ),
        remediation=(
            "Use named enum members in comparisons, membership checks, and match arms. Parse raw input at its "
            "boundary when it needs to participate in enum dispatch."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Resolves direct standard-library enum subclasses through declarations and explicit imports.",
            "Skips generated sources, custom enum equality, opaque operands, and types requiring inference.",
        ),
        examples=(
            RuleExample(
                example_id="raw-string",
                title="A raw string repeats an enum value",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("case.py", _EXAMPLE),),
                focus_path=PurePosixPath("case.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-member",
                title="A named enum member anchors the comparison",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("case.py", _EXAMPLE.replace('action == "build"', "action == Action.BUILD")),),
                focus_path=PurePosixPath("case.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated or context.has_wildcard_import:
            return []
        resolver = _EnumResolution(context, tree)
        findings: list[Diagnostic] = []
        for node in context.nodes(ast.Compare, ast.Match):
            match node:
                case ast.Compare():
                    if (name := _comparison_enum(node, resolver)) is not None:
                        findings.append(self._finding(context, node, name))
                case ast.Match():
                    findings.extend(self._match_findings(context, node, resolver))
        return findings

    def _match_findings(
        self, context: PythonFileContext, node: ast.Match, resolver: _EnumResolution
    ) -> list[Diagnostic]:
        patterns = [case.pattern for case in node.cases if _literal_pattern(case.pattern)]
        if not patterns or (name := resolver.enum_operand(node.subject)) is None:
            return []
        return [self._finding(context, pattern, name) for pattern in patterns]

    def _finding(self, context: PythonFileContext, node: ast.expr | ast.pattern, enum: str) -> Diagnostic:
        return Diagnostic(
            path=context.path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=self.code,
            severity=Severity.WARNING,
            message=f"Compare '{enum}' values using named enum members.",
        )


def _comparison_enum(node: ast.Compare, resolver: _EnumResolution) -> str | None:
    for (left, right), operator in zip(pairwise((node.left, *node.comparators)), node.ops, strict=True):
        match operator:
            case ast.In() | ast.NotIn() if _literal_collection(right):
                name = resolver.enum_operand(left)
            case ast.Eq() | ast.NotEq():
                name = _equality_enum(left, right, resolver) or _equality_enum(right, left, resolver)
            case _:
                continue
        if name is not None:
            return name
    return None


def _equality_enum(left: ast.expr, right: ast.expr, resolver: _EnumResolution) -> str | None:
    if _primitive_literal(right):
        return resolver.enum_operand(left)
    if isinstance(left, ast.Attribute) and left.attr == "value" and resolver.python_operand(right):
        return resolver.member_value_owner(left.value)
    return None


def _primitive_literal(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=str()):
            return True
        case (
            ast.Constant(value=int() as number)
            | ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=int() as number))
        ):
            return not isinstance(number, bool)
        case _:
            return False


def _literal_collection(node: ast.expr) -> bool:
    if not isinstance(node, ast.Tuple | ast.List | ast.Set):
        return False
    return any(_primitive_literal(item) for item in node.elts)


def _literal_pattern(pattern: ast.pattern) -> bool:
    match pattern:
        case ast.MatchValue(value=value):
            return _primitive_literal(value)
        case ast.MatchOr(patterns=patterns):
            return any(_literal_pattern(item) for item in patterns)
        case ast.MatchAs(pattern=inner) if inner is not None:
            return _literal_pattern(inner)
        case _:
            return False


def _root(node: ast.expr) -> ast.Name | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node if isinstance(node, ast.Name) else None


class _EnumResolution:
    def __init__(self, context: PythonFileContext, tree: ast.Module) -> None:
        self.context = context
        self.local = NominalSource(context.path, context.source, tree)
        self.project: ProjectIndexSet | None = context.session.project
        self._modules: dict[Path, dict[str, NominalSource | None]] = {}
        self._classes: dict[NominalSource, dict[str, _Class]] = {}
        self._annotations: dict[NominalSource, AnnotationSemantics] = {}

    def enum_operand(self, operand: ast.expr) -> str | None:
        model = self._value_class(operand)
        if model is None and isinstance(operand, ast.Attribute) and operand.attr == "value":
            model = self._value_class(operand.value)
        return model.declaration.name if model is not None and _enum_kind(model) is not None else None

    def member_value_owner(self, member: ast.expr) -> str | None:
        if not isinstance(member, ast.Attribute):
            return None
        model = self._class_reference(member.value, self.local, member)
        if model is None or _enum_kind(model) not in _VALUE_COMPATIBLE_BASES:
            return None
        declaration = model.declaration
        return declaration.name if member.attr in class_enum_members(declaration) else None

    def python_operand(self, operand: ast.expr) -> bool:
        root = _root(operand)
        if root is None:
            return False
        match self._binding(root):
            case ast.arg():
                return True
            case ast.Name() as binding:
                match self.context.parents.get(binding):
                    case ast.For() | ast.AsyncFor() | ast.comprehension() | ast.AnnAssign():
                        return True
                    case ast.Assign(value=value):
                        return _primitive_literal(value)
                    case _:
                        return False
            case _:
                return False

    def _binding(self, name: ast.Name) -> ast.AST | None:
        scope = self.context.binding_inventory.scope(name)
        provenance = self.context.static_resource_provenance
        if isinstance(scope, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            return provenance.runtime_binding(name.id, name)
        return provenance.binding(name.id, name)

    def _value_class(self, operand: ast.expr, *, depth: int = 0) -> _Class | None:
        if depth >= _MAX_RESOLUTION_DEPTH:
            return None
        if isinstance(operand, ast.Name):
            binding = self._binding(operand)
            if isinstance(binding, ast.arg):
                return self._parameter_class(binding)
            statement = self.context.parents.get(binding) if binding is not None else None
            if isinstance(statement, ast.AnnAssign) and statement.lineno <= operand.lineno:
                return self._annotation_class(statement.annotation, self.local)
        if isinstance(operand, ast.Attribute):
            owner = self._value_class(operand.value, depth=depth + 1)
            if owner is not None and (field := _field_annotation(owner.declaration, operand.attr)) is not None:
                return self._annotation_class(field, owner.source)
        return None

    def _parameter_class(self, argument: ast.arg) -> _Class | None:
        parameters = self.context.parents.get(argument)
        if not isinstance(parameters, ast.arguments) or argument in {parameters.vararg, parameters.kwarg}:
            return None
        if argument.annotation is not None:
            return self._annotation_class(argument.annotation, self.local)
        function = self.context.parents.get(parameters)
        owner = self.context.parents.get(function) if function is not None else None
        if isinstance(owner, ast.ClassDef) and function is not None and _instance_parameter(function) is argument:
            return _Class(self.local, owner)
        return None

    def _annotation_class(self, annotation: ast.expr, source: NominalSource) -> _Class | None:
        tree = source.tree
        if tree is None:
            return None
        if source not in self._annotations:
            self._annotations[source] = (
                self.context.annotation_semantics if source is self.local else AnnotationSemantics.from_tree(tree)
            )
        members = [
            member
            for member in self._annotations[source].transparent_members(annotation)
            if not (isinstance(member, ast.Constant) and member.value is None)
        ]
        if len(members) != 1:
            return None
        return self._class_reference(members[0], source, annotation)

    def _class_reference(self, reference: ast.expr, source: NominalSource, anchor: ast.expr) -> _Class | None:
        root = _root(reference)
        if root is None:
            return None
        if source is self.local:
            provenance = self.context.static_resource_provenance
            binding = provenance.binding(root.id, anchor)
            if root.id in provenance.mutated:
                return None
            if isinstance(binding, ast.ClassDef) and isinstance(reference, ast.Name):
                return self._class(source, binding.name)
            if not isinstance(binding, ast.alias):
                return None
            qualified = import_name_for_binding(reference, binding, self.context.parents.get(binding))
        else:
            if isinstance(reference, ast.Name) and (declaration := self._class(source, reference.id)) is not None:
                return declaration
            qualified = source.imports.resolved_qualified_name(reference)
        return self._imported_class(reference, source, qualified)

    def _imported_class(self, reference: ast.expr, source: NominalSource, qualified: str | None) -> _Class | None:
        target_name = qualified or self._indexed_import(reference, source)
        for _ in range(_MAX_RESOLUTION_DEPTH):
            if target_name is None:
                return None
            module, _, name = target_name.rpartition(".")
            target = self._module(source.path, module)
            if target is None:
                return None
            if (declaration := self._class(target, name)) is not None:
                return declaration
            reference = ast.Name(id=name, ctx=ast.Load())
            target_name = target.imports.resolved_qualified_name(reference) or self._indexed_import(reference, target)
            source = target
        return None

    def _indexed_import(self, reference: ast.expr, source: NominalSource) -> str | None:
        if self.project is None or (unit := self.project.unit(source.path)) is None:
            return None
        suffix: list[str] = []
        while isinstance(reference, ast.Attribute):
            suffix.append(reference.attr)
            reference = reference.value
        if not isinstance(reference, ast.Name) or reference.id in source.imports.shadowed_names:
            return None
        symbol = unit.imports.get(reference.id)
        if symbol is None:
            return None
        return ".".join(filter(None, (symbol.module, symbol.name, *reversed(suffix))))

    def _module(self, origin: Path, module: str) -> NominalSource | None:
        modules = self._modules.setdefault(origin, {})
        if module not in modules:
            modules[module] = self._load_module(origin, module)
        return modules[module]

    def _load_module(self, origin: Path, module: str) -> NominalSource | None:
        unit = self.project.source_unit(module) if self.project is not None else None
        if unit is not None:
            return None if is_generated(unit.path, unit.source) else NominalSource(unit.path, unit.source, unit.tree)
        session = self.context.session
        path = session.local_source.resolve_module(origin, module, 0, facts=session.first_party)
        source = session.local_source.read_module(path) if path is not None else None
        if source is None or is_generated(source.path, source.source):
            return None
        return NominalSource(source.path, source.source, source.tree)

    def _class(self, source: NominalSource, name: str) -> _Class | None:
        if source not in self._classes:
            tree = source.tree
            self._classes[source] = _declared_classes(source, tree) if tree is not None else {}
        return self._classes[source].get(name)


def _declared_classes(source: NominalSource, tree: ast.Module) -> dict[str, _Class]:
    rebound = module_rebindings(tree)
    return {
        statement.name: _Class(source, statement)
        for statement in tree.body
        if isinstance(statement, ast.ClassDef) and statement.name not in rebound
    }


def _enum_kind(model: _Class) -> str | None:
    declaration = model.declaration
    if declaration.keywords:
        return None
    imports = model.source.imports
    for decorator in declaration.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if imports.resolved_qualified_name(target) not in {
            "enum.unique",
            "enum.verify",
            "typing.final",
            "typing_extensions.final",
        }:
            return None
    kind: str | None = None
    for base in declaration.bases:
        resolved = stdlib_enum_base(base, imports)
        if resolved in _ENUM_BASES and kind is None:
            kind = resolved
        elif not (
            isinstance(base, ast.Name) and base.id in _VALUE_LIKE_BASES and imports.builtin_is_unshadowed(base.id)
        ):
            return None
    if not {"__eq__", "__ne__"}.isdisjoint(scope_bound_names(declaration.body)):
        return None
    return kind


def _instance_parameter(node: ast.AST) -> ast.arg | None:
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.decorator_list:
        return None
    parameters = node.args.posonlyargs + node.args.args
    return parameters[0] if parameters and parameters[0].arg == "self" else None


def _field_annotation(declaration: ast.ClassDef, name: str) -> ast.expr | None:
    annotations = [
        statement.annotation
        for statement in declaration.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == name
    ]
    for method in declaration.body:
        if not isinstance(method, ast.FunctionDef) or method.name != "__init__" or _instance_parameter(method) is None:
            continue
        annotations.extend(
            statement.annotation
            for statement in method.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(target := statement.target, ast.Attribute)
            and target.attr == name
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        )
    return annotations[0] if len(annotations) == 1 else None
