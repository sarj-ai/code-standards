from __future__ import annotations

import ast
from enum import Enum, auto
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
)
from sarj_python_lint.rules._declared_contracts import MODEL_BASES
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CONFIG_FACTORIES = frozenset({"pydantic.ConfigDict", "pydantic.config.ConfigDict"})
_FINAL_DECORATORS = frozenset({"typing.final", "typing_extensions.final"})
_CONFIG_HOOKS = frozenset({"Config", "__init_subclass__", "__pydantic_init_subclass__", "__pydantic_on_complete__"})


class _Strict(Enum):
    UNSET = auto()
    ENABLED = auto()
    DISABLED = auto()


@final
class RequireStrictPydanticModel(Rule):
    id = "require-strict-pydantic-model"
    code = "SARJ609"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require strict validation on Pydantic models.",
        rationale="Lax validation can silently coerce input to the declared type and hide a mismatch at the model boundary.",
        remediation="Set strict=True in the model configuration or inherit it from a strict model.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks module-level Pydantic v2 BaseModel subclasses and resolves effective configuration through bases defined in the same file.",
            "Resolves ConfigDict keyword arguments, literal dictionaries, and class keywords. Dynamic configuration, unresolved bases, generic declarations, custom class hooks, Pydantic Settings, RootModel, and dataclasses are excluded.",
            "Tests and generated files are excluded.",
            "With strict validation, Python-mode model_validate rejects string inputs for UUID and datetime fields. JSON-mode validation accepts their JSON string representations.",
        ),
        examples=(
            RuleExample(
                example_id="lax-model",
                title="Default validation can coerce an integer string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\n\nclass RetryPolicy(BaseModel):\n    attempts: int\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inherited-strict-model",
                title="An inherited configuration keeps validation strict",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, ConfigDict\n\n"
                        "class StrictModel(BaseModel, strict=True):\n    pass\n\n"
                        "class RetryPolicy(StrictModel):\n    model_config = ConfigDict(frozen=True)\n    attempts: int\n",
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
        if (
            "BaseModel" not in context.symbol_source
            or is_test_path(context.path)
            or context.generated
            or (tree := context.tree) is None
        ):
            return []
        inventory = context.binding_inventory
        config_read_scopes = {inventory.scope(read) for read in inventory.reads.get("model_config", ())}
        config_receivers = [node.value for node in context.nodes(ast.Attribute) if node.attr == "model_config"]
        if any(
            context.static_resource_provenance.runtime_import_name(receiver) in MODEL_BASES
            for receiver in config_receivers
        ):
            return []
        local_config_owners = {receiver.id for receiver in config_receivers if isinstance(receiver, ast.Name)}
        inherited: dict[ast.ClassDef, _Strict] = {}
        diagnostics: list[Diagnostic] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node in config_read_scopes or node.name in local_config_owners:
                continue
            setting = _effective_strict(node, context, inherited)
            if setting is None:
                continue
            inherited[node] = setting
            if setting is not _Strict.ENABLED and not context.suppressions.is_suppressed(node.lineno, self.code):
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        node.lineno,
                        node.col_offset + 1,
                        self.code,
                        "Set strict=True on this Pydantic model to prevent lax validation from coercing inputs.",
                        severity=Severity.WARNING,
                    )
                )
        return diagnostics


def _effective_strict(
    node: ast.ClassDef, context: PythonFileContext, inherited: dict[ast.ClassDef, _Strict]
) -> _Strict | None:
    provenance = context.static_resource_provenance
    members = context.binding_inventory.bindings.get(node, {})
    if (
        not node.bases
        or node.type_params
        or not _CONFIG_HOOKS.isdisjoint(members)
        or any(provenance.runtime_import_name(decorator) not in _FINAL_DECORATORS for decorator in node.decorator_list)
        or any(keyword.arg in {None, "metaclass"} for keyword in node.keywords)
    ):
        return None

    effective = _Strict.UNSET
    for base in node.bases:
        if provenance.runtime_import_name(base) in MODEL_BASES:
            continue
        parent = provenance.runtime_binding(base.id, base) if isinstance(base, ast.Name) else None
        match parent:
            case ast.ClassDef() if (setting := inherited.get(parent)) is not None:
                if setting is not _Strict.UNSET:
                    effective = setting
            case _:
                return None

    config = _class_config(node, context)
    if config is None:
        return None
    if (keyword := _keyword_strict(node.keywords)) is not _Strict.UNSET:
        return keyword
    return effective if config is _Strict.UNSET else config


def _class_config(node: ast.ClassDef, context: PythonFileContext) -> _Strict | None:
    writes = context.binding_inventory.bindings.get(node, {}).get("model_config", ())
    if not writes:
        return _Strict.UNSET
    if len(writes) != 1:
        return None
    [target] = writes
    statement = context.parents.get(target)
    if not isinstance(target, ast.Name) or statement is None or context.parents.get(statement) is not node:
        return None
    match statement:
        case ast.Assign(targets=[only], value=value) if only is target:
            return _config_value(value, context)
        case ast.AnnAssign(target=only, value=ast.expr() as value) if only is target:
            return _config_value(value, context)
        case _:
            return None


def _config_value(value: ast.expr, context: PythonFileContext) -> _Strict | None:
    match value:
        case ast.Call(args=[], func=func, keywords=keywords) if all(keyword.arg is not None for keyword in keywords):
            factory = context.static_resource_provenance.runtime_import_name(func)
            return _keyword_strict(keywords) if factory in _CONFIG_FACTORIES else None
        case ast.Dict(keys=keys, values=values):
            setting = _Strict.UNSET
            for key, item in zip(keys, values, strict=True):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    return None
                if key.value == "strict":
                    setting = _literal_strict(item)
            return setting
        case _:
            return None


def _keyword_strict(keywords: list[ast.keyword]) -> _Strict | None:
    return next((_literal_strict(keyword.value) for keyword in keywords if keyword.arg == "strict"), _Strict.UNSET)


def _literal_strict(value: ast.expr) -> _Strict | None:
    match value:
        case ast.Constant(value=True):
            return _Strict.ENABLED
        case ast.Constant(value=False | None):
            return _Strict.DISABLED
        case _:
            return None
