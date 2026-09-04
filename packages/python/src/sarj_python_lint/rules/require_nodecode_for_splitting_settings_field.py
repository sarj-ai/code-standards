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
    Severity,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SETTINGS_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
_SETTINGS_CONFIG_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
_PYDANTIC_CONFIG_SOURCES = frozenset({"pydantic", "pydantic.config"})
_NODECODE_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.sources", "pydantic_settings.sources.types"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.functional_validators"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_COMPLEX_BUILTINS = frozenset({"dict", "frozenset", "list", "set", "tuple"})


@final
class RequireNoDecodeForSplittingSettingsField(Rule):
    id = "require-nodecode-for-splitting-settings-field"
    code = "SARJ424"
    documentation = RuleDocumentation(
        summary="Warn when an unconditional raw-string splitter lacks a pydantic-settings decoding policy.",
        rationale=(
            "pydantic-settings JSON-decodes complex environment fields before field validators run; a raw-string "
            "splitter without NoDecode can fail during process startup."
        ),
        remediation=(
            "After confirming the intended environment format, annotate the field as `Annotated[FieldType, NoDecode]` "
            "or disable decoding for the settings class so the validator receives the raw string."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule checks direct fields and direct field validators on direct BaseSettings subclasses.",
            "Only a single-field before-validator whose sole executable statement returns an expression that splits its value parameter is treated as an unconditional raw splitter.",
            "Classes that statically disable settings decoding through a class keyword, model_config, or Config are excluded.",
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
                        "import os\nfrom pydantic import field_validator\nfrom pydantic_settings import BaseSettings\n\n"
                        "class Settings(BaseSettings):\n"
                        "    emails: list[str]\n"
                        "    @field_validator('emails', mode='before')\n"
                        "    @classmethod\n"
                        "    def split_emails(cls, value):\n"
                        "        return value.split(',')\n\n"
                        "os.environ['EMAILS'] = 'one@example.com,two@example.com'\nSettings()\n",
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
                        "import os\nfrom typing import Annotated\nfrom pydantic import field_validator\n"
                        "from pydantic_settings import BaseSettings, NoDecode\n\n"
                        "class Settings(BaseSettings):\n"
                        "    emails: Annotated[list[str], NoDecode]\n"
                        "    @field_validator('emails', mode='before')\n"
                        "    @classmethod\n"
                        "    def split_emails(cls, value):\n"
                        "        return value.split(',')\n\n"
                        "os.environ['EMAILS'] = 'one@example.com,two@example.com'\nSettings()\n",
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
        if (
            is_test_path(path)
            or is_generated(path, source)
            or "pydantic_settings" not in source
            or "field_validator" not in source
            or "split" not in source
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for model in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_settings(model, imports) or _customises_settings_sources(model):
                continue
            decoding_disabled = _disables_decoding(model, imports)
            fields = {
                statement.target.id: statement
                for statement in model.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and _is_complex_without_nodecode(statement.annotation, imports)
                and (not decoding_disabled or _has_force_decode(statement.annotation, imports))
            }
            reported_fields: set[str] = set()
            for function in (
                statement for statement in model.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                field_name = _single_before_validated_field(function, imports)
                if (
                    field_name is None
                    or field_name not in fields
                    or not _unconditionally_splits_value_parameter(function, imports)
                ):
                    continue
                field = fields[field_name]
                if (
                    field_name in reported_fields
                    or _node_is_suppressed(field, source_lines, self.code)
                    or _node_is_suppressed(function, source_lines, self.code)
                ):
                    continue
                reported_fields.add(field_name)
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=field.annotation.lineno,
                        col=field.annotation.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"Complex setting `{field_name}` is unconditionally split by `{function.name}` but "
                            "environment sources may JSON-decode it first; if the input contract is raw text, "
                            "import `Annotated` and `NoDecode` and add `NoDecode` metadata, or disable settings "
                            "decoding for the class."
                        ),
                    )
                )
        return diagnostics


def _is_direct_settings(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return len(node.bases) == 1 and imports.resolves(node.bases[0], sources=_SETTINGS_SOURCES, symbol="BaseSettings")


def _customises_settings_sources(node: ast.ClassDef) -> bool:
    return any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "settings_customise_sources"
        for statement in node.body
    )


def _disables_decoding(node: ast.ClassDef, imports: ImportIndex) -> bool:
    if any(keyword.arg == "enable_decoding" and _is_literal_false(keyword.value) for keyword in node.keywords):
        return True
    model_config: ast.expr | None = None
    legacy_config: ast.ClassDef | None = None
    for statement in node.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id="model_config")], value=value):
                model_config = value
            case ast.AnnAssign(target=ast.Name(id="model_config"), value=value) if value is not None:
                model_config = value
            case ast.AugAssign(target=ast.Name(id="model_config")):
                model_config = None
            case ast.ClassDef(name="Config"):
                legacy_config = statement
            case _:
                pass
    if model_config is not None and _config_value_disables_decoding(model_config, imports):
        return True
    return legacy_config is not None and _legacy_config_disables_decoding(legacy_config)


def _config_value_disables_decoding(node: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(node, ast.Dict):
        setting: ast.expr | None = None
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                setting = None
                continue
            if isinstance(key, ast.Constant) and key.value == "enable_decoding":
                setting = value
        return _is_literal_false(setting)
    if not isinstance(node, ast.Call) or node.args or any(keyword.arg is None for keyword in node.keywords):
        return False
    is_settings_config = imports.resolves(node.func, sources=_SETTINGS_CONFIG_SOURCES, symbol="SettingsConfigDict")
    is_pydantic_config = imports.resolves(node.func, sources=_PYDANTIC_CONFIG_SOURCES, symbol="ConfigDict")
    is_builtin_dict = (
        isinstance(node.func, ast.Name) and node.func.id == "dict" and imports.builtin_is_unshadowed("dict")
    )
    if not is_settings_config and not is_pydantic_config and not is_builtin_dict:
        return False
    setting = next((keyword.value for keyword in reversed(node.keywords) if keyword.arg == "enable_decoding"), None)
    return _is_literal_false(setting)


def _legacy_config_disables_decoding(node: ast.ClassDef) -> bool:
    setting: ast.expr | None = None
    for statement in node.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id="enable_decoding")], value=value):
                setting = value
            case ast.AnnAssign(target=ast.Name(id="enable_decoding"), value=value) if value is not None:
                setting = value
            case ast.AugAssign(target=ast.Name(id="enable_decoding")):
                setting = None
            case _:
                pass
    return _is_literal_false(setting)


def _is_literal_false(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


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


def _has_force_decode(node: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(node, ast.Subscript) or not imports.resolves(
        node.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        return False
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
    return any(imports.resolves(item, sources=_NODECODE_SOURCES, symbol="ForceDecode") for item in members[1:]) or (
        bool(members) and _has_force_decode(members[0], imports)
    )


def _single_before_validated_field(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> str | None:
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
        if not (
            len(decorator.args) == 1
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            return None
        fields.add(decorator.args[0].value)
    return next(iter(fields)) if len(fields) == 1 else None


def _unconditionally_splits_value_parameter(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> bool:
    positional = [*node.args.posonlyargs, *node.args.args]
    if not positional:
        return False
    is_classmethod = any(
        isinstance(decorator, ast.Name)
        and decorator.id == "classmethod"
        and imports.builtin_is_unshadowed("classmethod")
        for decorator in node.decorator_list
    )
    is_staticmethod = any(
        isinstance(decorator, ast.Name)
        and decorator.id == "staticmethod"
        and imports.builtin_is_unshadowed("staticmethod")
        for decorator in node.decorator_list
    )
    if is_classmethod and is_staticmethod:
        return False
    if is_classmethod or (not is_staticmethod and positional[0].arg == "cls"):
        if not positional[1:]:
            return False
        value = positional[1].arg
    elif not is_staticmethod and positional[0].arg == "self":
        return False
    else:
        value = positional[0].arg
    body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return False
    return _contains_unconditional_split(body[0].value, value)


def _contains_unconditional_split(node: ast.expr, value: str) -> bool:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "split"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == value
    ):
        return True
    match node:
        case ast.Call(func=func, args=args, keywords=keywords):
            eager = [func, *(arg for arg in args if not isinstance(arg, ast.GeneratorExp))]
            eager.extend(keyword.value for keyword in keywords)
            eager.extend(generator.generators[0].iter for generator in args if isinstance(generator, ast.GeneratorExp))
        case ast.BoolOp(values=[first, *_]):
            eager = [first]
        case ast.IfExp(test=test):
            eager = [test]
        case (
            ast.GeneratorExp(generators=[first, *_])
            | ast.ListComp(generators=[first, *_])
            | ast.SetComp(generators=[first, *_])
            | ast.DictComp(generators=[first, *_])
        ):
            eager = [first.iter]
        case ast.UnaryOp(operand=operand) | ast.Await(value=operand) | ast.Starred(value=operand):
            eager = [operand]
        case ast.NamedExpr(value=assigned):
            eager = [assigned]
        case ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items):
            eager = list(items)
        case ast.Dict(keys=keys, values=values):
            eager = [key for key in keys if key is not None]
            eager.extend(values)
        case _:
            return False
    return any(_contains_unconditional_split(child, value) for child in eager)


def _node_is_suppressed(
    node: ast.AnnAssign | ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    code: str,
) -> bool:
    decorators = node.decorator_list if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ()
    start = min((decorator.lineno for decorator in decorators), default=node.lineno)
    return any(is_suppressed(source_lines, line, code) for line in range(start, node.lineno + 1))
