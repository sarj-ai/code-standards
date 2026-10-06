from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_PYDANTIC = frozenset({"pydantic", "pydantic.functional_validators"})
_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_SETTINGS_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_Function = ast.FunctionDef | ast.AsyncFunctionDef


@final
class PreferDeclarativeNonEmptyString(Rule):
    id = "prefer-declarative-non-empty-string"
    code = "SARJ484"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare non-empty strings at existing Pydantic validation boundaries.",
        rationale="A manual empty-string rejection leaves the schema advertising an unconstrained string and duplicates validation that the boundary can express declaratively.",
        remediation="Use Field(min_length=1) on the model field or an Annotated constrained string on the validated parameter. Preserve existing aliases and review custom error contracts before removing the guard.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct BaseModel/BaseSettings fields with plain builtin str annotations and trivial after field validators, or import-resolved validate_call functions with a leading empty rejection, are checked.",
            "Only not value and equality with the empty string followed by a sole ValueError raise are recognized. Model validators must then return the unchanged value.",
            "Optional, constrained, aliased or unknown annotations, defaulted validated parameters, private model attributes, asynchronous model validators, before/plain/wrap validators, transformations, whitespace checks, additional model validation, unknown decorators, and shadowed imports are excluded.",
            "Models containing any additional import-resolved field or model validator, including class-body validator proxies, are excluded because declarative constraints run before after-validator transformations.",
            "Generated/vendor and test files are excluded. Import and builtin shadow analysis is conservative; files that mutate imported Pydantic module attributes are excluded. No project-wide alias or inheritance resolution is attempted.",
            "No autofix is offered because declarative constraints change error types, messages, and validation order.",
        ),
        examples=(
            RuleExample(
                example_id="model-empty-guard",
                title="An after validator only rejects an empty string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\nclass Label(BaseModel):\n    value: str\n    @field_validator('value')\n    @classmethod\n    def require_value(cls, value):\n        if not value:\n            raise ValueError('empty')\n        return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="model-length-contract",
                title="The field publishes its non-empty constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, Field\nclass Label(BaseModel):\n    value: str = Field(min_length=1)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="validated-parameter-guard",
                title="An already validated function rejects an empty parameter",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/labels.py",
                        "from pydantic import validate_call\n@validate_call\ndef label(value: str):\n    if value == '':\n        raise ValueError('empty')\n    return f'label:{value}'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/labels.py"),
                expected_count=1,
                public=True,
                scenario="validated-parameter",
            ),
            RuleExample(
                example_id="validated-parameter-contract",
                title="The validated parameter declares its constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/labels.py",
                        "from typing import Annotated\nfrom pydantic import Field, validate_call\n@validate_call\ndef label(value: Annotated[str, Field(min_length=1)]):\n    return f'label:{value}'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/labels.py"),
                expected_count=0,
                public=True,
                scenario="validated-parameter",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or is_test_path(context.path) or context.tree is None:
            return []
        if _has_rebound_imports(context):
            return []
        imports = context.imports
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            body = _body(function)
            if not body or (value := _empty_rejection(body[0], imports)) is None:
                continue
            parent = context.parents.get(function)
            if not (
                _validated_parameter(function, value, imports)
                or (isinstance(parent, ast.ClassDef) and _model_validator(parent, function, value, imports))
            ) or is_suppressed(context.source_lines, body[0].lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=body[0].lineno,
                    col=body[0].col_offset + 1,
                    code=self.code,
                    message="This Pydantic boundary manually rejects an empty string; declare Field(min_length=1) or a validated constrained string, preserving aliases and custom error contracts.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _has_rebound_imports(context: PythonFileContext) -> bool:
    imports = context.imports
    if any(
        context.parents.get(statement) is not context.tree
        and any(
            (alias.asname or alias.name.partition(".")[0]) in imports.bindings
            or (alias.asname or alias.name.partition(".")[0]) in {"str", "ValueError", "classmethod"}
            for alias in statement.names
        )
        for statement in context.nodes(ast.Import, ast.ImportFrom)
    ):
        return True
    return any(
        isinstance(attribute.ctx, (ast.Store, ast.Del))
        and (qualified := imports.resolved_qualified_name(attribute)) is not None
        and qualified.startswith(("pydantic.", "pydantic_settings."))
        for attribute in context.nodes(ast.Attribute)
    )


def _body(function: _Function) -> list[ast.stmt]:
    return function.body[1:] if ast.get_docstring(function, clean=False) is not None else function.body


def _empty_rejection(statement: ast.stmt, imports: ImportIndex) -> str | None:
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return None
    raised = statement.body[0]
    if not (
        isinstance(raised, ast.Raise)
        and isinstance(raised.exc, ast.Call)
        and isinstance(raised.exc.func, ast.Name)
        and raised.exc.func.id == "ValueError"
        and imports.builtin_is_unshadowed("ValueError")
    ):
        return None
    match statement.test:
        case (
            ast.UnaryOp(op=ast.Not(), operand=ast.Name(id=value))
            | ast.Compare(left=ast.Name(id=value), ops=[ast.Eq()], comparators=[ast.Constant(value="")])
            | ast.Compare(left=ast.Constant(value=""), ops=[ast.Eq()], comparators=[ast.Name(id=value)])
        ):
            return value
        case _:
            return None


def _validated_parameter(function: _Function, value: str, imports: ImportIndex) -> bool:
    if len(function.decorator_list) != 1:
        return False
    decorator = function.decorator_list[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not imports.resolves(
        target, sources=frozenset({"pydantic", "pydantic.validate_call_decorator"}), symbol="validate_call"
    ):
        return False
    positional = (*function.args.posonlyargs, *function.args.args)
    defaulted = {argument.arg for argument in positional[len(positional) - len(function.args.defaults) :]} | {
        argument.arg
        for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
        if default is not None
    }
    return value not in defaulted and any(
        argument.arg == value and _plain_string(argument.annotation, imports)
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    )


def _model_validator(model: ast.ClassDef, function: _Function, value: str, imports: ImportIndex) -> bool:
    if isinstance(function, ast.AsyncFunctionDef):
        return False
    if len(model.bases) != 1 or not (
        imports.resolves(model.bases[0], sources=_MODEL_SOURCES, symbol="BaseModel")
        or imports.resolves(model.bases[0], sources=_SETTINGS_SOURCES, symbol="BaseSettings")
    ):
        return False
    validator = _after_validator(function, imports)
    if not _unchanged_value(function, value) or validator is None or _has_other_validators(model, function, imports):
        return False
    fields = [
        argument.value
        for argument in validator.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    ]
    if not fields or len(fields) != len(validator.args):
        return False
    plain_fields = {
        member.target.id
        for member in model.body
        if isinstance(member, ast.AnnAssign)
        and isinstance(member.target, ast.Name)
        and not member.target.id.startswith("_")
        and _plain_string(member.annotation, imports)
        and not _has_length_constraint(member.value, imports)
    }
    return all(field in plain_fields for field in fields)


def _has_other_validators(model: ast.ClassDef, candidate: _Function, imports: ImportIndex) -> bool:
    return any(
        isinstance(node, ast.Call)
        and imports.resolved_symbol(node.func, sources=_PYDANTIC) in {"field_validator", "model_validator"}
        for member in model.body
        if member is not candidate
        for node in ast.walk(member)
    )


def _plain_string(annotation: ast.expr | None, imports: ImportIndex) -> bool:
    return isinstance(annotation, ast.Name) and annotation.id == "str" and imports.builtin_is_unshadowed("str")


def _unchanged_value(function: _Function, value: str) -> bool:
    match (_body(function), (*function.args.posonlyargs, *function.args.args)):
        case ([_, ast.Return(value=ast.Name(id=returned))], (_, ast.arg(arg=parameter))) if (
            returned == parameter == value
        ):
            return not (function.args.kwonlyargs or function.args.vararg or function.args.kwarg)
        case _:
            return False


def _after_validator(function: _Function, imports: ImportIndex) -> ast.Call | None:
    validator: ast.Call | None = None
    for decorator in function.decorator_list:
        match decorator:
            case ast.Name(id="classmethod") if imports.builtin_is_unshadowed("classmethod"):
                continue
            case ast.Call() if validator is None and imports.resolves(
                decorator.func, sources=_PYDANTIC, symbol="field_validator"
            ):
                validator = decorator
            case _:
                return None
    if validator is None:
        return None
    if any(
        keyword.arg is None
        or (keyword.arg == "mode" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value == "after"))
        for keyword in validator.keywords
    ):
        return None
    return validator


def _has_length_constraint(value: ast.expr | None, imports: ImportIndex) -> bool:
    return (
        isinstance(value, ast.Call)
        and imports.resolves(value.func, sources=_FIELD_SOURCES, symbol="Field")
        and any(keyword.arg in {None, "min_length"} for keyword in value.keywords)
    )
