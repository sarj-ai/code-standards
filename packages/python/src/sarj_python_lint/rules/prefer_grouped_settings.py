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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MIN_GROUP_FIELDS = 2
_MODIFIER_PREFIXES = frozenset({"is", "has", "min", "max", "num", "total", "default", "enable", "disable"})


@final
class PreferGroupedSettings(ProjectRule):
    id = "prefer-grouped-settings"
    code = "SARJ532"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
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
            "Boolean and quantitative modifiers such as is, has, min, max, num, total and default do not establish component namespaces. A prefix already present as a field is left for explicit API review.",
            "ClassVar, Final, private attributes, model_config, computed fields, tests, generated code, unknown decorators and unresolved bases are excluded. Each namespace produces one warning, anchored at its first field; an exact class or first-field suppression is honored.",
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

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        contracts = DeclaredContracts(context)
        findings: list[Diagnostic] = []
        for declaration in context.tree.body:
            if not isinstance(declaration, ast.ClassDef):
                continue
            model = contracts.class_type(ast.Name(id=declaration.name))
            if model is None or not contracts.inherits(model, SETTINGS_BASES):
                continue
            if is_suppressed(context.source_lines, declaration.lineno, self.code):
                continue
            for prefix, members in _settings_groups(contracts.model_fields(model)).items():
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
                        Severity.WARNING,
                    )
                )
        return findings


def _settings_groups(fields: dict[str, ast.AnnAssign]) -> dict[str, dict[str, ast.AnnAssign]]:
    groups: dict[str, dict[str, ast.AnnAssign]] = defaultdict(dict)
    for name, field in fields.items():
        prefix, separator, tail = name.partition("_")
        if separator and tail and prefix not in _MODIFIER_PREFIXES and prefix not in fields:
            groups[prefix][name] = field
    return {prefix: members for prefix, members in groups.items() if len(members) >= _MIN_GROUP_FIELDS}
