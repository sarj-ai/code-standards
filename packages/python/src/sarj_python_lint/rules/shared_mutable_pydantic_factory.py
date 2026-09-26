from __future__ import annotations

import ast
from collections import Counter
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
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_MUTABLE_BUILTINS = frozenset({"list", "dict", "set", "bytearray"})
_MESSAGE = (
    "This default factory returns a shared mutable object, so separate model instances share its state. "
    "Construct a fresh value inside the factory or explicitly copy the intended initial state."
)


@final
class SharedMutablePydanticFactory(Rule):
    id = "shared-mutable-pydantic-factory"
    code = "SARJ459"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Pydantic default factories should not return a captured mutable singleton.",
        rationale=(
            "A default factory returning an existing mutable object gives different models the same state. "
            "Mutating one model can therefore silently change another model."
        ),
        remediation="Construct a fresh value in the factory, or deliberately copy the required initial state.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct module-level BaseModel subclasses without configuration or methods and public annotated Field declarations are inspected.",
            "Factories must be zero-argument lambdas or undecorated module functions containing one return, optionally after a docstring.",
            "Captured values require unique, acyclic module bindings to built-in mutable containers or direct unconfigured BaseModel instances.",
            "Rebound names, shadowed imports, inherited or configured models, unknown services, nested scopes, and generated files are excluded.",
            "Fields enabling default validation or supplying unknown keyword options are excluded because validation may copy or transform the factory result.",
            "Factories producing new values, explicit copies, or values derived from validated data are excluded; intentional sharing needs a local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="captured-list",
                title="A factory returns the same mutable list for every model",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, Field\nSHARED = []\nclass Model(BaseModel):\n    values: list[int] = Field(default_factory=lambda: SHARED)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fresh-list",
                title="The factory creates an independent list",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    values: list[int] = Field(default_factory=list)\n",
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
        if "default_factory" not in context.source or context.generated or context.tree is None:
            return []
        tree = context.tree
        imports = ImportIndex.from_tree(tree)
        bindings = _stable_bindings(tree)
        models = {
            model for model in tree.body if isinstance(model, ast.ClassDef) and _unconfigured_model(model, imports)
        }
        diagnostics: list[Diagnostic] = []
        for field in context.nodes(ast.AnnAssign):
            if context.parents.get(field) not in models:
                continue
            factory = _field_factory(field, imports)
            if factory is None:
                continue
            result = _factory_result(factory, bindings)
            if not isinstance(result, ast.Name) or not _shared_mutable(result, bindings, imports):
                continue
            if is_suppressed(context.source_lines, field.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=field.lineno,
                    col=field.col_offset + 1,
                    code=self.code,
                    message=_MESSAGE,
                    severity=Severity.WARNING,
                )
            )
        return diagnostics


def _stable_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    writes: Counter[str] = Counter()
    for node in ast.walk(tree):
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                writes[name] += 1
            case ast.Import(names=names):
                writes.update(alias.asname or alias.name.partition(".")[0] for alias in names)
            case ast.ImportFrom(names=names):
                writes.update(alias.asname or alias.name for alias in names)
            case _:
                pass
    bindings: dict[str, ast.AST] = {}
    for node in tree.body:
        match node:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                bindings[name] = value
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
                bindings[name] = value
            case ast.FunctionDef(name=name) | ast.ClassDef(name=name):
                bindings[name] = node
            case _:
                pass
    return {name: value for name, value in bindings.items() if writes[name] == 1}


def _resolve(node: ast.AST, bindings: dict[str, ast.AST]) -> ast.AST | None:
    seen: set[str] = set()
    while isinstance(node, ast.Name):
        if node.id in seen or node.id not in bindings:
            return None
        seen.add(node.id)
        node = bindings[node.id]
    return node


def _unconfigured_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return (
        len(node.bases) == 1
        and imports.resolves(node.bases[0], sources=_MODEL_SOURCES, symbol="BaseModel")
        and not node.decorator_list
        and not node.keywords
        and not any(_customizes_model(statement) for statement in node.body)
    )


def _field_factory(node: ast.stmt, imports: ImportIndex) -> ast.expr | None:
    if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
        return None
    if node.target.id.startswith("_") or node.target.id == "model_config":
        return None
    annotation = node.annotation.value if isinstance(node.annotation, ast.Subscript) else node.annotation
    if imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="ClassVar"):
        return None
    if not isinstance(node.value, ast.Call) or not imports.resolves(
        node.value.func, sources=_FIELD_SOURCES, symbol="Field"
    ):
        return None
    for keyword in node.value.keywords:
        if keyword.arg is None:
            return None
        if keyword.arg == "validate_default" and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        ):
            return None
    return next((keyword.value for keyword in node.value.keywords if keyword.arg == "default_factory"), None)


def _factory_result(factory: ast.expr, bindings: dict[str, ast.AST]) -> ast.expr | None:
    resolved = _resolve(factory, bindings)
    if not isinstance(resolved, ast.Lambda | ast.FunctionDef) or not _no_arguments(resolved.args):
        return None
    if isinstance(resolved, ast.Lambda):
        return resolved.body
    if resolved.decorator_list:
        return None
    body = list(resolved.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) == 1 and isinstance(body[0], ast.Return):
        return body[0].value
    return None


def _no_arguments(arguments: ast.arguments) -> bool:
    return not (arguments.posonlyargs or arguments.args or arguments.kwonlyargs or arguments.vararg or arguments.kwarg)


def _shared_mutable(reference: ast.Name, bindings: dict[str, ast.AST], imports: ImportIndex) -> bool:
    value = _resolve(reference, bindings)
    if isinstance(value, ast.List | ast.Dict | ast.Set | ast.ListComp | ast.DictComp | ast.SetComp):
        return True
    if not isinstance(value, ast.Call):
        return False
    if (
        isinstance(value.func, ast.Name)
        and value.func.id in _MUTABLE_BUILTINS
        and imports.builtin_is_unshadowed(value.func.id)
    ):
        return True
    model = _resolve(value.func, bindings)
    return isinstance(model, ast.ClassDef) and _unconfigured_model(model, imports)


def _customizes_model(statement: ast.stmt) -> bool:
    match statement:
        case ast.ClassDef(name="Config") | ast.FunctionDef() | ast.AsyncFunctionDef():
            return True
        case ast.Assign(targets=targets):
            return any(isinstance(target, ast.Name) and target.id == "model_config" for target in targets)
        case ast.AnnAssign(target=ast.Name(id="model_config")):
            return True
        case _:
            return False
