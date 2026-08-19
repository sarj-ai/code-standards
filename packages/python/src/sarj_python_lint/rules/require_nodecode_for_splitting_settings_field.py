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


_SETTINGS_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
_NODECODE_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.sources", "pydantic_settings.sources.types"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.functional_validators"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_COMPLEX_BUILTINS = frozenset({"dict", "frozenset", "list", "set", "tuple"})


@final
class RequireNoDecodeForSplittingSettingsField(Rule):
    id = "require-nodecode-for-splitting-settings-field"
    code = "SARJ423"
    documentation = RuleDocumentation(
        summary="Require NoDecode when a before-validator splits a complex pydantic-settings field.",
        rationale=(
            "pydantic-settings JSON-decodes complex environment fields before field validators run; a raw-string "
            "splitter without NoDecode can fail during process startup."
        ),
        remediation="Annotate the field as `Annotated[FieldType, NoDecode]` so the validator receives the raw string.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule checks direct fields and direct field validators on direct BaseSettings subclasses.",
            "A validator is considered a raw splitter only when it calls `.split(...)` on its value parameter.",
            "Custom settings sources and indirect splitter helpers are outside the rule's scope.",
        ),
        examples=(
            RuleExample(
                example_id="complex-setting-split-without-nodecode",
                title="Raw splitter without NoDecode",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from pydantic import field_validator\nfrom pydantic_settings import BaseSettings\n\n"
                        "class Settings(BaseSettings):\n"
                        "    emails: list[str]\n"
                        "    @field_validator('emails', mode='before')\n"
                        "    @classmethod\n"
                        "    def split_emails(cls, value):\n"
                        "        return value.split(',')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="complex-setting-split-with-nodecode",
                title="Raw splitter receives undecoded input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from typing import Annotated\nfrom pydantic import field_validator\n"
                        "from pydantic_settings import BaseSettings, NoDecode\n\n"
                        "class Settings(BaseSettings):\n"
                        "    emails: Annotated[list[str], NoDecode]\n"
                        "    @field_validator('emails', mode='before')\n"
                        "    @classmethod\n"
                        "    def split_emails(cls, value):\n"
                        "        return value.split(',')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
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
        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for model in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_settings(model, imports):
                continue
            fields = {
                statement.target.id: statement
                for statement in model.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and _is_complex_without_nodecode(statement.annotation, imports)
            }
            for function in (
                statement for statement in model.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                validated = _before_validated_fields(function, imports) & fields.keys()
                if not validated or not _splits_value_parameter(function):
                    continue
                for field_name in sorted(validated):
                    field = fields[field_name]
                    diagnostics.append(
                        Diagnostic(
                            path=path,
                            line=field.annotation.lineno,
                            col=field.annotation.col_offset + 1,
                            code=self.code,
                            message=(
                                f"Complex setting `{field_name}` is split by a before-validator but lacks `NoDecode`; "
                                "wrap its type in `Annotated[..., NoDecode]`."
                            ),
                        )
                    )
        return diagnostics


def _is_direct_settings(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return len(node.bases) == 1 and imports.resolves(node.bases[0], sources=_SETTINGS_SOURCES, symbol="BaseSettings")


def _is_complex_without_nodecode(node: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(node, ast.Subscript) and imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        if any(imports.resolves(item, sources=_NODECODE_SOURCES, symbol="NoDecode") for item in members[1:]):
            return False
        return bool(members) and _is_complex_without_nodecode(members[0], imports)
    if isinstance(node, ast.Subscript):
        value = node.value
        if isinstance(value, ast.Name) and value.id in _COMPLEX_BUILTINS and imports.builtin_is_unshadowed(value.id):
            return True
        return any(
            imports.resolves(value, sources=_TYPING_SOURCES, symbol=name)
            for name in ("Dict", "FrozenSet", "List", "Set", "Tuple")
        )
    return False


def _before_validated_fields(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> frozenset[str]:
    fields: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not imports.resolves(
            decorator.func, sources=_PYDANTIC_SOURCES, symbol="field_validator"
        ):
            continue
        is_before = any(
            keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "before"
            for keyword in decorator.keywords
        )
        if not is_before:
            continue
        fields.update(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
    return frozenset(fields)


def _splits_value_parameter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    positional = [*node.args.posonlyargs, *node.args.args]
    if not positional:
        return False
    value = positional[0].arg
    if len(positional) > 1:
        value = positional[1].arg
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr == "split"
            and isinstance(current.func.value, ast.Name)
            and current.func.value.id == value
        ):
            return True
        stack.extend(ast.iter_child_nodes(current))
    return False
