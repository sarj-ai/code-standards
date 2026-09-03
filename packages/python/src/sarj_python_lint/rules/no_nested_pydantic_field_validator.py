from __future__ import annotations

import ast
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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PYDANTIC_BASE_MODEL_SOURCES = frozenset(
    {"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"}
)
_PYDANTIC_SETTINGS_SOURCES = frozenset({"pydantic", "pydantic.v1", "pydantic_settings"})
_FIELD_VALIDATOR_SOURCES = frozenset({"pydantic", "pydantic.functional_validators"})
_LEGACY_VALIDATOR_SOURCES = frozenset(
    {"pydantic", "pydantic.class_validators", "pydantic.v1", "pydantic.v1.class_validators"}
)
_CLASS_VAR_SOURCES = frozenset({"typing", "typing_extensions"})


@final
class NoNestedPydanticFieldValidator(Rule):
    id = "no-nested-pydantic-field-validator"
    code = "SARJ425"
    documentation = RuleDocumentation(
        summary="Outer-model Pydantic field validator is owned by a nested helper class.",
        rationale=(
            "Pydantic collects validator metadata from the model class namespace. A decorator indented into a "
            "nested class is therefore invisible to the outer model, so its declared field silently loses validation."
        ),
        remediation="Move the field-validator method into the outer model class.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct BaseModel or BaseSettings subclasses and validators directly owned by one nested class are inspected.",
            "Nested classes with bases are excluded because inherited Pydantic fields cannot be resolved locally.",
            "Intentional reusable validators with check_fields=False are excluded; Pydantic v1 validator syntax is supported.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="validator-nested-in-config",
                title="Nested Config silently does not validate Settings.language",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\n\n"
                        "class Settings(BaseModel):\n"
                        "    language: str\n"
                        "    class Config:\n"
                        "        extra = 'forbid'\n"
                        "        @field_validator('language')\n"
                        "        @classmethod\n"
                        "        def normalize(cls, value):\n"
                        "            return value.lower()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validator-owned-by-model",
                title="Validator belongs to the model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\n\n"
                        "class Settings(BaseModel):\n"
                        "    language: str\n"
                        "    @field_validator('language')\n"
                        "    @classmethod\n"
                        "    def normalize(cls, value):\n"
                        "        return value.lower()\n",
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
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = _module_scope_imports(tree)
        parents = _parent_index(tree)
        diagnostics: list[Diagnostic] = []
        for outer in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_model(outer, imports, parents):
                continue
            outer_fields = _direct_fields(outer, imports)
            for nested in (statement for statement in outer.body if isinstance(statement, ast.ClassDef)):
                # A based nested class may be an indirect Pydantic model whose inherited
                # fields are unavailable to this file-local analysis. Only base-less
                # Config/helper classes provide a deterministic ownership mistake.
                if nested.bases:
                    continue
                nested_fields = _direct_fields(nested, imports)
                for function in (
                    statement
                    for statement in nested.body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    for decorator, fields in _field_validators(function, imports, parents):
                        selected_fields = outer_fields if "*" in fields else fields & outer_fields
                        misplaced = sorted(selected_fields - nested_fields)
                        if not misplaced:
                            continue
                        diagnostics.append(
                            Diagnostic(
                                path=path,
                                line=decorator.lineno,
                                col=decorator.col_offset + 1,
                                code=self.code,
                                message=(
                                    f"Validator for outer field(s) {', '.join(f'`{name}`' for name in misplaced)} "
                                    f"is nested inside `{nested.name}`; move it to `{outer.name}`."
                                ),
                            )
                        )
        return diagnostics


def _is_direct_model(node: ast.ClassDef, imports: ImportIndex, parents: dict[ast.AST, ast.AST]) -> bool:
    return any(
        (
            imports.resolves(base, sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel")
            or imports.resolves(base, sources=_PYDANTIC_SETTINGS_SOURCES, symbol="BaseSettings")
        )
        and not _shadowed_in_enclosing_function(base, node, parents)
        for base in node.bases
    )


def _direct_fields(node: ast.ClassDef, imports: ImportIndex) -> frozenset[str]:
    return frozenset(
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not _is_class_var(statement.annotation, imports)
        and not statement.target.id.startswith("_")
        and statement.target.id != "model_config"
    )


def _field_validators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
    parents: dict[ast.AST, ast.AST],
) -> tuple[tuple[ast.Call, frozenset[str]], ...]:
    validators: list[tuple[ast.Call, frozenset[str]]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or _shadowed_in_enclosing_function(decorator.func, node, parents):
            continue
        is_validator = imports.resolves(
            decorator.func, sources=_FIELD_VALIDATOR_SOURCES, symbol="field_validator"
        ) or imports.resolves(decorator.func, sources=_LEGACY_VALIDATOR_SOURCES, symbol="validator")
        if not is_validator or _literal_check_fields_false(decorator):
            continue
        fields = frozenset(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
        validators.append((decorator, fields))
    return tuple(validators)


def _is_class_var(annotation: ast.expr, imports: ImportIndex) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return imports.resolves(target, sources=_CLASS_VAR_SOURCES, symbol="ClassVar")


def _literal_check_fields_false(decorator: ast.Call) -> bool:
    return any(
        keyword.arg == "check_fields"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in decorator.keywords
    )


def _module_scope_imports(tree: ast.Module) -> ImportIndex:
    body: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body.append(
                ast.Assign(
                    targets=[ast.Name(id=statement.name, ctx=ast.Store())],
                    value=ast.Constant(value=None),
                )
            )
        else:
            body.append(statement)
    return ImportIndex.from_tree(ast.Module(body=body, type_ignores=[]))


def _parent_index(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: owner for owner in ast.walk(tree) for child in ast.iter_child_nodes(owner)}


def _shadowed_in_enclosing_function(
    reference: ast.expr,
    owner: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    root = _root_name(reference)
    if root is None:
        return False
    current = parents.get(owner)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and _function_binds(
            current, root
        ):
            return True
        current = parents.get(current)
    return False


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _function_binds(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str) -> bool:
    arguments = node.args
    if any(
        argument.arg == name
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    ) or (arguments.vararg is not None and arguments.vararg.arg == name) or (
        arguments.kwarg is not None and arguments.kwarg.arg == name
    ):
        return True
    body = node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else [node.body]
    return any(_scope_statement_binds(statement, name) for statement in body)


def _scope_statement_binds(node: ast.AST, name: str) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return node.name == name if not isinstance(node, ast.Lambda) else False
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.id == name
    return any(_scope_statement_binds(child, name) for child in ast.iter_child_nodes(node))
