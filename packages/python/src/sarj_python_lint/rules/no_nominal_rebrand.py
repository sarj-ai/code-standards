from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from pathlib import PurePosixPath
import sys
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint._file_context import PythonFileContext
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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._domain_boundaries import NEW_TYPE_ORIGINS
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rules._nominal_project import NominalSource


_CARRIERS = frozenset({"int", "str", "bytes", "float", "complex", "object"})
_QUALIFIED_CARRIERS = frozenset({"uuid.UUID", *(f"builtins.{name}" for name in _CARRIERS)})
_EXAMPLE = (
    'from typing import NewType\n\nUserId = NewType("UserId", str)\nOrgId = NewType("OrgId", str)\n\n'
    "def user_key(organization: OrgId) -> UserId:\n    return UserId(organization)\n"
)


@final
class NoNominalRebrand(Rule):
    id = "no-nominal-rebrand"
    code = "SARJ608"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Preserve NewType identity across constructor calls.",
        rationale=(
            "NewType returns its argument unchanged at runtime. Converting directly between nominal types "
            "with a shared carrier can pass type checking and cross a domain boundary without validation."
        ),
        remediation="Keep the declared nominal type, or validate and translate the value at the domain boundary.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct declarations using typing.NewType or typing_extensions.NewType with supported builtin carriers, uuid.UUID or a same-module class. Both declarations must resolve in current or accessible first-party source.",
            "Checks explicitly annotated parameters, locals and direct class fields. Type inference, re-exports, nested nominal declarations, inherited fields, unknown carriers and ambiguous bindings are outside the source proof.",
        ),
        examples=(
            RuleExample(
                example_id="organization-key-is-used-as-user-key",
                title="Keep organization and user keys distinct",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/identities.py", _EXAMPLE),),
                focus_path=PurePosixPath("app/identities.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="user-key-is-created-from-raw-input",
                title="Introduce a user key from its raw carrier",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/identities.py", _EXAMPLE.replace("organization: OrgId", "organization: str")
                    ),
                ),
                focus_path=PurePosixPath("app/identities.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        if not (
            context.nodes(ast.AnnAssign)
            or any(parameter.annotation is not None for parameter in context.nodes(ast.arg))
        ):
            return []
        bindings = _NominalBindings(context)
        if "NewType" not in context.symbol_source and not bindings.imports_nominal_source():
            return []
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if len(call.args) != 1 or call.keywords or context.suppressions.is_suppressed(call.lineno, self.code):
                continue
            [value] = call.args
            if not isinstance(value, ast.Name | ast.Attribute):
                continue
            source = bindings.annotation_brand(value)
            if source is None or (target := bindings.brand(call.func, call.func, runtime=True)) is None:
                continue
            if source.declaration is target.declaration or source.carrier != target.carrier:
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    call.lineno,
                    call.col_offset + 1,
                    self.code,
                    f"`{target.declaration.id}` would relabel a `{source.declaration.id}` value. "
                    "Validate and translate it at the domain boundary.",
                    severity=Severity.WARNING,
                )
            )
        return findings


@dataclass(frozen=True, slots=True)
class _Brand:
    declaration: ast.Name
    carrier: str | ast.ClassDef


class _NominalBindings:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self._modules: dict[Path, AnnotationOrigins] = {}

    @cached_property
    def origins(self) -> AnnotationOrigins:
        return AnnotationOrigins(self.context)

    @cached_property
    def sources(self) -> dict[str, NominalSource]:
        context = self.context
        if not context.path.is_file():
            return {}
        session = context.session
        return session.nominal_project.sources(context.path, session.first_party, project=session.project)

    def imports_nominal_source(self) -> bool:
        for statement in self.context.nodes(ast.Import, ast.ImportFrom):
            for binding in statement.names:
                reference = ast.Name(id=binding.asname or binding.name, ctx=ast.Load())
                target = binding.name if isinstance(statement, ast.Import) else self._import_name(reference, binding)
                if target and (self._nominal_source(target) or self._nominal_source(target.rpartition(".")[0])):
                    return True
        return False

    def annotation_brand(self, value: ast.Name | ast.Attribute) -> _Brand | None:
        annotation = self._value_annotation(value)
        parsed = self.context.annotation_semantics.parse(annotation)
        return self.brand(parsed, annotation) if parsed is not None and annotation is not None else None

    def brand(self, expression: ast.expr, at: ast.expr, *, runtime: bool = False) -> _Brand | None:
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        provenance = self.origins.provenance
        if (
            not isinstance(root, ast.Name)
            or provenance.wildcard
            or provenance.dynamic_namespace
            or root.id in provenance.external_bindings | provenance.mutated
            or self.origins.shadowed(root.id, at)
        ):
            return None
        binding = provenance.runtime_binding(root.id, at) if runtime else self.origins.binding(root.id, at)
        if isinstance(expression, ast.Name) and isinstance(binding, ast.Name):
            return _declared_brand(self.origins, binding)
        if isinstance(binding, ast.alias):
            return self._imported_brand(expression, binding)
        return None

    def _imported_brand(self, expression: ast.expr, binding: ast.alias) -> _Brand | None:
        qualified = self._import_name(expression, binding)
        if qualified is None:
            return None
        module, _, name = qualified.rpartition(".")
        context = self.context
        source = self._nominal_source(module)
        if source is None or source.tree is None:
            return None
        if source.path == context.path.resolve():
            origins = self.origins
        else:
            if source.path not in self._modules:
                self._modules[source.path] = AnnotationOrigins(
                    PythonFileContext(source.path, source.text, context.session)
                )
            origins = self._modules[source.path]
        declarations = origins.provenance.bindings.get(origins.context.tree, {}).get(name, ())
        if len(declarations) == 1 and isinstance(declarations[0], ast.Name):
            return _declared_brand(origins, declarations[0])
        return None

    def _nominal_source(self, module: str) -> NominalSource | None:
        if not module or module.partition(".")[0] in sys.stdlib_module_names:
            return None
        source = self.sources.get(module)
        return source if source is not None and "NewType" in source.text else None

    def _import_name(self, expression: ast.expr, binding: ast.alias) -> str | None:
        parent = self.context.parents.get(binding)
        if isinstance(parent, ast.ImportFrom) and parent.level:
            return self._relative_name(expression, parent, binding)
        return import_name_for_binding(expression, binding, parent)

    def _relative_name(self, expression: ast.expr, parent: ast.ImportFrom, binding: ast.alias) -> str | None:
        path = self.context.path.resolve()
        module = next((module for module, source in self.sources.items() if source.path == path), None)
        if module is None:
            return None
        parts = module.split(".")
        if path.name != "__init__.py":
            parts.pop()
        if parent.level > len(parts):
            return None
        prefix = ".".join((*parts[: len(parts) - parent.level + 1], parent.module or "")).rstrip(".")
        return import_name_for_binding(expression, binding, ast.ImportFrom(module=prefix, names=[binding], level=0))

    def _value_annotation(self, value: ast.Name | ast.Attribute) -> ast.expr | None:
        if isinstance(value, ast.Name):
            binding = self.origins.provenance.runtime_binding(value.id, value)
            if isinstance(binding, ast.arg):
                return binding.annotation
            declaration = self.context.parents.get(binding) if binding is not None else None
            return declaration.annotation if isinstance(declaration, ast.AnnAssign) else None
        if not isinstance(value.value, ast.Name):
            return None
        owner = self._record_owner(value.value)
        if not isinstance(owner, ast.ClassDef):
            return None
        fields = self.origins.provenance.bindings.get(owner, {}).get(value.attr, ())
        if len(fields) != 1:
            return None
        field = self.context.parents.get(fields[0])
        return field.annotation if isinstance(field, ast.AnnAssign) else None

    def _record_owner(self, receiver: ast.Name) -> ast.AST | None:
        if (annotation := self._value_annotation(receiver)) is not None:
            parsed = self.context.annotation_semantics.parse(annotation)
            return self.origins.binding(parsed.id, annotation) if isinstance(parsed, ast.Name) else None
        argument = self.origins.provenance.runtime_binding(receiver.id, receiver)
        arguments = self.context.parents.get(argument) if isinstance(argument, ast.arg) else None
        if not isinstance(arguments, ast.arguments):
            return None
        positional = [*arguments.posonlyargs, *arguments.args]
        method = self.context.parents.get(arguments)
        if (
            positional
            and positional[0] is argument
            and isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
            and not method.decorator_list
        ):
            return self.context.parents.get(method)
        return None


def _declared_brand(origins: AnnotationOrigins, binding: ast.Name) -> _Brand | None:
    provenance = origins.provenance
    if provenance.wildcard or provenance.dynamic_namespace or binding.id in provenance.external_bindings:
        return None
    declaration = origins.context.parents.get(binding)
    if declaration is None or origins.context.parents.get(declaration) is not origins.context.tree:
        return None
    match declaration:
        case ast.Assign(
            targets=[target], value=ast.Call(func=func, args=[ast.Constant(value=name), carrier], keywords=[])
        ) if target is binding and name == binding.id and origins.qualified(func, func) in NEW_TYPE_ORIGINS:
            resolved = _carrier_identity(carrier, origins)
            return _Brand(binding, resolved) if resolved is not None else None
        case _:
            return None


def _carrier_identity(carrier: ast.expr, origins: AnnotationOrigins) -> str | ast.ClassDef | None:
    qualified = origins.qualified(carrier, carrier)
    if qualified is not None and qualified in _QUALIFIED_CARRIERS:
        return qualified
    match carrier:
        case ast.Name(id=name) if name in _CARRIERS and origins.builtin(carrier, name, carrier):
            return f"builtins.{name}"
        case ast.Name(id=name) if isinstance(owner := origins.binding(name, carrier), ast.ClassDef):
            return owner if origins.context.parents.get(owner) is origins.context.tree else None
        case _:
            return None
