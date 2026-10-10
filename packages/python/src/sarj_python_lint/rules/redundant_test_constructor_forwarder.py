from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
    is_suppressed,
)
from sarj_python_lint.rules._closed_helpers import (
    call_matches,
    closed_references,
    direct_call,
    executable_body,
    stable_class,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import SourceUnit


_BUILTINS = frozenset({"str", "int", "float", "bool", "bytes", "list", "dict", "set", "tuple", "object"})
_BAD = "from pydantic import BaseModel\nclass Record(BaseModel):\n    value: str\ndef _record(value: str) -> Record:\n    return Record(value=value)\ndef test_record():\n    assert _record('item').value == 'item'\n"
_GOOD = "from pydantic import BaseModel\nclass Record(BaseModel):\n    value: str\ndef test_record():\n    assert Record(value='item').value == 'item'\n"


@final
class RedundantTestConstructorForwarder(ProjectRule):
    id = "redundant-test-constructor-forwarder"
    code = "SARJ487"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A private test helper mirrors a resolved value-record constructor without adding a contract.",
        rationale="A forwarding helper repeats the constructor's fields and types, creating a second signature to maintain without scenario defaults or setup.",
        remediation="Use the real typed constructor at known callers. Keep helpers that choose defaults, transform data, own resources, narrow types, or provide an intentional patch boundary.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only undecorated private module-level helpers in authored test files are considered; conftest, generated and vendor sources are excluded.",
            "The helper has only an optional docstring and one keyword construction, no defaults, and one required bare parameter per supplied field with equivalent resolved annotations.",
            "Only non-generic first-party Pydantic records with statically known fields, plain ancestry, and no custom methods, decorators or field aliases are proven; application modules are never imported.",
            "Unknown calls, unpacking, escapes, reflection, rebinding, patch strings, narrower parameter types, and unresolved constructor ownership are excluded. No autofix preserves intentional seams.",
        ),
        examples=tuple(
            RuleExample(
                example_id=name,
                title=title,
                outcome=outcome,
                files=(ExampleFile.python("tests/test_record.py", source),),
                focus_path=PurePosixPath("tests/test_record.py"),
                expected_count=count,
                public=True,
            )
            for name, title, outcome, source, count in (
                (
                    "mirrored-constructor",
                    "Required parameters only repeat record fields",
                    ExampleOutcome.MATCH,
                    _BAD,
                    1,
                ),
                (
                    "direct-constructor",
                    "The record owns its signature and validation",
                    ExampleOutcome.NO_MATCH,
                    _GOOD,
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if not is_test_path(context.path) or context.path.name == "conftest.py" or context.generated or tree is None:
            return []
        project = context.session.project or ProjectIndexSet.single(context.path, context.source)
        unit = project.unit_or_source(context.path, context.source, tree)
        if unit is None:
            return []
        provenance = ResourceProvenance(context)
        findings: list[Diagnostic] = []
        for function in tree.body:
            if not isinstance(function, ast.FunctionDef) or (constructor := _forwarded_constructor(function)) is None:
                continue
            references = closed_references(context, function, provenance)
            if references is None or any(
                (call := direct_call(reference, context)) is None or not call_matches(function, call)
                for reference in references
            ):
                continue
            record = _record_fields(project, unit, constructor.func, context, provenance)
            if record is None or not _same_contract(function, constructor, record, project, unit):
                continue
            if not is_suppressed(context.source_lines, function.lineno, self.code):
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=function.lineno,
                        col=function.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"`{function.name}` only forwards required fields to the resolved record constructor; use that constructor at known callers, or retain an intentional narrower contract or patch seam.",
                    )
                )
        return findings


def _forwarded_constructor(function: ast.FunctionDef) -> ast.Call | None:
    if function.args.defaults or any(function.args.kw_defaults):
        return None
    body = executable_body(function)
    if len(body) != 1 or not isinstance(body[0], ast.Return) or not isinstance(body[0].value, ast.Call):
        return None
    constructor = body[0].value
    parameters = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    if constructor.args or len(constructor.keywords) != len(parameters) or not parameters:
        return None
    mapped = [keyword.value.id for keyword in constructor.keywords if isinstance(keyword.value, ast.Name)]
    if (
        len(mapped) != len(parameters)
        or set(mapped) != {arg.arg for arg in parameters}
        or len({keyword.arg for keyword in constructor.keywords}) != len(parameters)
    ):
        return None
    return constructor


def _same_contract(
    function: ast.FunctionDef,
    constructor: ast.Call,
    record: tuple[SourceUnit, dict[str, ast.expr], set[str]],
    project: ProjectIndexSet,
    unit: SourceUnit,
) -> bool:
    if function.returns is None or project.resolve(unit, function.returns) != project.resolve(unit, constructor.func):
        return False
    owner, fields, required = record
    if not required <= {keyword.arg for keyword in constructor.keywords}:
        return False
    arguments = {arg.arg: arg for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]}
    return all(
        keyword.arg in fields
        and (annotation := _annotation(unit, arguments[keyword.value.id].annotation)) is not None
        and annotation == _annotation(owner, fields[keyword.arg])
        for keyword in constructor.keywords
        if isinstance(keyword.value, ast.Name)
    )


def _record_fields(
    project: ProjectIndexSet,
    unit: SourceUnit,
    expression: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> tuple[SourceUnit, dict[str, ast.expr], set[str]] | None:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- defer until the rule registry finishes loading.

    summary = project.class_for(unit, expression)
    if (
        summary is None
        or (owner := project.source_unit(summary.symbol.module)) is None
        or owner.tree is None
        or is_generated(owner.path, owner.source)
    ):
        return None
    root = expression.value if isinstance(expression, ast.Attribute) else expression
    if (
        not isinstance(root, ast.Name)
        or not isinstance(provenance.binding(root.id, expression), ast.ClassDef | ast.alias)
        or root.id in provenance.mutated
    ):
        return None
    definition_context = (
        context if owner.path == context.path else PythonFileContext(owner.path, owner.source, context.session)
    )
    definition_provenance = provenance if definition_context is context else ResourceProvenance(definition_context)
    declaration = next(
        (node for node in definition_context.nodes(ast.ClassDef) if node.name == summary.symbol.name), None
    )
    if (
        declaration is None
        or declaration.type_params
        or not stable_class(definition_context, declaration, definition_provenance)
        or len(declaration.bases) != 1
        or definition_context.imports.resolved_qualified_name(declaration.bases[0]) != "pydantic.BaseModel"
    ):
        return None
    shape = _record_shape(declaration, definition_context)
    return (owner, *shape) if shape is not None else None


def _record_shape(
    declaration: ast.ClassDef, definition_context: PythonFileContext
) -> tuple[dict[str, ast.expr], set[str]] | None:
    fields: dict[str, ast.expr] = {}
    required: set[str] = set()
    for statement in declaration.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            return None
        if statement.target.id.startswith("_") or statement.target.id == "model_config":
            return None
        if isinstance(statement.value, ast.Call) and (
            definition_context.imports.resolved_qualified_name(statement.value.func) != "pydantic.Field"
            or any(
                keyword.arg in {None, "alias", "validation_alias", "alias_priority"}
                for keyword in statement.value.keywords
            )
        ):
            return None
        fields[statement.target.id] = statement.annotation
        if _required_field(statement.value):
            required.add(statement.target.id)
    return fields, required


def _required_field(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Call):
        value = (
            value.args[0]
            if value.args
            else next(
                (keyword.value for keyword in value.keywords if keyword.arg in {"default", "default_factory"}), None
            )
        )
    return value is None or (isinstance(value, ast.Constant) and value.value is Ellipsis)


def _annotation(unit: SourceUnit, annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    match annotation:
        case ast.Name(id=name):
            if (
                name in _BUILTINS
                and unit.tree is not None
                and not ImportIndex.from_tree(unit.tree).builtin_is_unshadowed(name)
            ):
                return None
            imported = unit.imports.get(name)
            return (
                f"{imported.module}.{imported.name}"
                if imported is not None
                else f"builtins.{name}"
                if name in _BUILTINS
                else f"{unit.module}.{name}"
            )
        case ast.Attribute():
            symbol = ProjectIndexSet.resolve(unit, annotation)
            return f"{symbol.module}.{symbol.name}" if symbol is not None else None
        case ast.Constant(value=None):
            return "None"
        case ast.Subscript(value=value, slice=slice_value):
            root, item = _annotation(unit, value), _annotation(unit, slice_value)
            return f"{root}[{item}]" if root is not None and item is not None else None
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            lhs, rhs = _annotation(unit, left), _annotation(unit, right)
            return f"{lhs}|{rhs}" if lhs is not None and rhs is not None else None
        case _:
            return None
