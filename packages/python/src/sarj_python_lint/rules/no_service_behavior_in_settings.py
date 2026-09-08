from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_DATA_NAME_RE = re.compile(r"(?:Settings|Config|Configuration|Options)$")
_DATA_CLASS_RE = re.compile(r"\bclass\s+\w+(?:Settings|Config|Configuration|Options)\b")
_COLLABORATOR_RE = re.compile(
    r"(?:Client|Service|Store|Repository|Repo|Gateway|Provider|Pool|Publisher|Queue|Scheduler)$"
)
_NON_BEHAVIORAL_DECORATORS = frozenset(
    {
        "cached_property",
        "classmethod",
        "computed_field",
        "field_serializer",
        "field_validator",
        "model_serializer",
        "model_validator",
        "property",
        "root_validator",
        "staticmethod",
        "validator",
    }
)


@final
class NoServiceBehaviorInSettings(Rule):
    id: str = "no-service-behavior-in-settings"
    code: str = "SARJ441"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Settings and configuration types should not orchestrate injected collaborators.",
        rationale=(
            "A class named as settings or configuration promises passive data. Calling injected stores, clients, "
            "or services from that object hides orchestration behind a data boundary and couples configuration "
            "construction to runtime behavior."
        ),
        remediation=(
            "Move collaborator calls into a service, coordinator, or compiler with an honest behavioral name; keep "
            "the settings/configuration object as a TypedDict, Pydantic model, attrs class, or dataclass."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct module classes named *Settings, *Config, *Configuration, or *Options are checked.",
            "A finding requires a typed collaborator field and an ordinary public method that calls that field; pure computations, properties, validators, serializers, factories, generated files, and tests are excluded.",
            "The rule does not require every data object to use a particular record library and does not infer behavior from a filename alone.",
        ),
        examples=(
            RuleExample(
                example_id="settings-orchestrates-store",
                title="A settings-named class calls injected persistence",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/batch_settings.py",
                        "class BatchSettings:\n"
                        "    def __init__(self, store: ScheduleStore) -> None:\n"
                        "        self._store = store\n\n"
                        "    async def repoint(self, batch_id: str) -> int:\n"
                        "        return await self._store.repoint(batch_id)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batch_settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="settings-is-data-only",
                title="A settings type remains a passive record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/batch_settings.py",
                        "from dataclasses import dataclass\n\n"
                        "@dataclass(frozen=True, slots=True)\n"
                        "class BatchSettings:\n"
                        "    retry_limit: int\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batch_settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_test_support_path(path)
            or is_generated(path, source)
            or _DATA_CLASS_RE.search(source) is None
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or _DATA_NAME_RE.search(node.name) is None:
                continue
            collaborator_fields = _collaborator_fields(node)
            behavioral_methods = [
                method.name
                for method in _methods(node)
                if _is_behavioral_method(method) and _calls_collaborator(method, collaborator_fields)
            ]
            if not behavioral_methods or is_suppressed(source_lines, node.lineno, self.code):
                continue
            methods = ", ".join(f"`{name}`" for name in behavioral_methods)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"`{node.name}` is named as passive data but {methods} calls an injected collaborator — "
                        "move orchestration to a service/coordinator and keep settings or configuration data-only."
                    ),
                )
            )
        return diagnostics


def _methods(node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [statement for statement in node.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _collaborator_fields(node: ast.ClassDef) -> frozenset[str]:
    fields = {
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and _is_collaborator_annotation(statement.annotation)
    }
    init = next((method for method in _methods(node) if method.name == "__init__"), None)
    if init is None:
        return frozenset(fields)
    collaborator_parameters = {
        parameter.arg
        for parameter in (*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs)
        if parameter.arg != "self" and _is_collaborator_annotation(parameter.annotation)
    }
    for statement in init.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        if not isinstance(value, ast.Name) or value.id not in collaborator_parameters:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        fields.update(
            target.attr
            for target in targets
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
        )
    return frozenset(fields)


def _is_collaborator_annotation(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(
        _COLLABORATOR_RE.search(_dotted_tail(candidate) or "") is not None
        for candidate in ast.walk(annotation)
        if isinstance(candidate, (ast.Name, ast.Attribute))
    )


def _is_behavioral_method(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if method.name.startswith("_"):
        return False
    return not any(
        (_dotted_tail(decorator.func if isinstance(decorator, ast.Call) else decorator) or "")
        in _NON_BEHAVIORAL_DECORATORS
        for decorator in method.decorator_list
    )


def _calls_collaborator(method: ast.FunctionDef | ast.AsyncFunctionDef, fields: frozenset[str]) -> bool:
    return any(
        (field := _self_field(call.func)) is not None and field in fields
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
    )


def _self_field(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        if isinstance(current.value, ast.Name) and current.value.id == "self":
            return current.attr
        current = current.value
    return None


def _dotted_tail(node: ast.expr) -> str | None:
    current = node
    if isinstance(current, ast.Call):
        current = current.func
    if isinstance(current, ast.Subscript):
        current = current.value
    match current:
        case ast.Name():
            return current.id
        case ast.Attribute():
            return current.attr
        case _:
            return None
