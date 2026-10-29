from __future__ import annotations

import ast
from collections import defaultdict
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
    is_suppressed,
)
from sarj_python_lint.rules._declared_contracts import SETTINGS_BASES, DeclaredContracts
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._declared_contracts import DeclaredClass
    from sarj_python_lint.rules._project_index import ProjectIndexSet


_MIN_GROUP_FIELDS = 2
_MODIFIER_PREFIXES = frozenset(
    {"is", "has", "min", "max", "num", "total", "default", "enable", "disable", "expected", "use"}
)


@final
class PreferGroupedSettings(ProjectRule):
    id = "prefer-grouped-settings"
    code = "SARJ532"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Group settings fields that share a Python namespace prefix into a nested settings object.",
        rationale=(
            "Repeated namespace prefixes flatten one component's configuration across the parent settings API. "
            "A focused settings object gives that component an explicit boundary."
        ),
        remediation=(
            "Move the related fields into a focused nested settings object, normally constructed with "
            "Field(default_factory=...). Preserve existing environment aliases, prefixes, validation, defaults "
            "and source precedence, and verify real environment loading before changing the settings API."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only source-proven Pydantic BaseSettings classes and directly owned public fields are checked. Two distinct fields must share the first complete snake-case namespace token; character prefixes, environment aliases, inherited fields and unrelated data classes do not establish a group.",
            "Boolean, expectation and quantitative modifiers such as is, has, use, expected, min, max, num, total and default do not establish component namespaces. A prefix already present as a field is left for explicit API review.",
            "ClassVar, Final, private attributes, model_config, computed fields, tests, generated code, unknown decorators and unresolved bases are excluded. Each namespace produces one error, anchored at its first field; an exact class or first-field suppression is honored.",
            "Source-proven nested BaseSettings fields do not count as flat candidates. A source-proven nested child already groups a namespace when its parent field has the same first complete Python namespace token, or when its public directly owned fields share that prefix apart from bare fields that are not other source-proven nested settings objects. A competing namespace or nested settings component under a different parent namespace retains subgroup findings. Class names alone, unknown annotations and unknown parent types do not establish ownership.",
            "There is no automatic rewrite: nesting may change environment-variable decoding, aliases, source precedence and consumer access paths.",
        ),
        examples=(
            RuleExample(
                example_id="flat-component-settings",
                title="Related settings expose a repeated component namespace",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from pydantic_settings import BaseSettings\n"
                        "class Settings(BaseSettings):\n"
                        "    embedder_url: str\n"
                        "    embedder_token: str\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nested-component-settings",
                title="The component owns its settings and environment prefix",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from pydantic import Field\n"
                        "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
                        "class EmbedderSettings(BaseSettings):\n"
                        "    model_config = SettingsConfigDict(env_prefix='EMBEDDER_')\n"
                        "    url: str\n"
                        "    token: str\n"
                        "class Settings(BaseSettings):\n"
                        "    embedder: EmbedderSettings = Field(default_factory=EmbedderSettings)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def __init__(self) -> None:
        self._ownership_project: ProjectIndexSet | None = None
        self._ownership: dict[tuple[Path, str], frozenset[str]] = {}

    @override
    def prepare(self, indexes: ProjectIndexSet) -> None:
        super().prepare(indexes)
        self._ownership_project = None
        self._ownership.clear()

    def _namespaces(self, contracts: DeclaredContracts, model: DeclaredClass) -> frozenset[str]:
        if self._ownership_project is not contracts.project:
            self._ownership = _nested_ownership_index(contracts)
            self._ownership_project = contracts.project
        return self._ownership.get((model.unit.path, model.declaration.name), frozenset())

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        contracts = DeclaredContracts(context)
        findings: list[Diagnostic] = []
        for model in _settings_models(contracts):
            if not is_suppressed(context.source_lines, model.declaration.lineno, self.code):
                findings.extend(self._model_diagnostics(context, contracts, model))
        return findings

    def _model_diagnostics(
        self, context: PythonFileContext, contracts: DeclaredContracts, model: DeclaredClass
    ) -> list[Diagnostic]:
        fields = contracts.model_fields(model)
        nested_fields = frozenset(
            name
            for name, field in fields.items()
            if (child := contracts.annotation(field.annotation, model.unit)) is not None
            and contracts.inherits(child, SETTINGS_BASES)
        )
        groups = _settings_groups(fields, nested_fields=nested_fields)
        if not groups:
            return []
        namespaces = self._namespaces(contracts, model)
        findings: list[Diagnostic] = []
        for prefix, members in groups.items():
            if _already_grouped(prefix, fields, namespaces, nested_fields=nested_fields):
                continue
            first = next(iter(members.values()))
            if is_suppressed(context.source_lines, first.lineno, self.code):
                continue
            names = ", ".join(f"`{name}`" for name in members)
            findings.append(
                Diagnostic(
                    context.path,
                    first.lineno,
                    first.col_offset + 1,
                    self.code,
                    f"Settings fields {names} share the `{prefix}_` namespace; group them under a focused `{prefix}` settings object while preserving environment loading.",
                    Severity.ERROR,
                )
            )
        return findings


def _settings_models(contracts: DeclaredContracts) -> Iterator[DeclaredClass]:
    unit = contracts.unit
    if unit is None or unit.tree is None:
        return
    for declaration in unit.tree.body:
        if not isinstance(declaration, ast.ClassDef):
            continue
        model = contracts.class_type(ast.Name(id=declaration.name))
        if model is not None and contracts.inherits(model, SETTINGS_BASES):
            yield model


def _already_grouped(
    prefix: str, fields: dict[str, ast.AnnAssign], namespaces: frozenset[str], *, nested_fields: frozenset[str]
) -> bool:
    if any(name.partition("_")[0] == prefix for name in namespaces):
        return True
    return bool(namespaces) and all(
        name.startswith(f"{prefix}_") or ("_" not in name and name not in nested_fields) for name in fields
    )


def _settings_groups(
    fields: dict[str, ast.AnnAssign], *, nested_fields: frozenset[str] = frozenset()
) -> dict[str, dict[str, ast.AnnAssign]]:
    groups: dict[str, dict[str, ast.AnnAssign]] = defaultdict(dict)
    for name, field in fields.items():
        if name in nested_fields:
            continue
        prefix, separator, tail = name.partition("_")
        if separator and tail and prefix not in _MODIFIER_PREFIXES and prefix not in fields:
            groups[prefix][name] = field
    return {prefix: members for prefix, members in groups.items() if len(members) >= _MIN_GROUP_FIELDS}


def _nested_ownership_index(contracts: DeclaredContracts) -> dict[tuple[Path, str], frozenset[str]]:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- defer the context import until the rule registry and analysis session finish initializing.

    ownership: dict[tuple[Path, str], set[str]] = defaultdict(set)
    for source in contracts.project.source_snapshot().units:
        unit = contracts.project.unit(source.key)
        if unit is None or unit.tree is None or is_test_path(unit.path) or is_generated(unit.path, unit.source):
            continue
        context = PythonFileContext(unit.path, unit.source)
        context.session.project = contracts.project
        local = DeclaredContracts(context)
        for parent in _settings_models(local):
            for name, field in local.model_fields(parent).items():
                child = local.annotation(field.annotation)
                if child is not None:
                    ownership[child.unit.path, child.declaration.name].add(name)
    return {identity: frozenset(namespaces) for identity, namespaces in ownership.items()}
