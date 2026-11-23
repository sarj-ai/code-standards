from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._secret_names import is_secret_name
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
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, SETTINGS_BASES, DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._pydantic_field_contract import (
    FIELD_SOURCES,
    MODEL_SOURCES,
    SETTINGS_SOURCES,
    TYPING_SOURCES,
    model_namespace_hazards,
)
from sarj_python_lint.rules._value_models import stable_native


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
    from sarj_python_lint.rules._imports import ImportIndex


_FLAG = "hide_input_in_errors"
_CONFIG_SOURCES = frozenset({"pydantic", "pydantic.config"})
_SECRET_SOURCES = frozenset({"pydantic", "pydantic.types"})
_SECRET_TYPES = frozenset({"SecretStr", "SecretBytes"})
_TEXT_TYPES = frozenset({"str", "bytes"})
_ALIAS_KEYWORDS = frozenset({"alias", "validation_alias"})
_NEUTRAL_BASES = ((MODEL_SOURCES, "BaseModel"), (TYPING_SOURCES, "Generic"), (frozenset({"abc"}), "ABC"))
_IMPORTS = "from pydantic import SecretStr\nfrom pydantic_settings import BaseSettings, SettingsConfigDict\n"


class _Flag(Enum):
    UNSET = auto()
    HIDDEN = auto()
    SHOWN = auto()


@dataclass(frozen=True, slots=True)
class _SettingsFacts:
    settings: bool
    flag: _Flag
    exposed: frozenset[str]

    @property
    def reported(self) -> bool:
        return self.settings and self.flag is not _Flag.HIDDEN and bool(self.exposed)


_NATIVE_SETTINGS = _SettingsFacts(settings=True, flag=_Flag.UNSET, exposed=frozenset())
_NEUTRAL = _SettingsFacts(settings=False, flag=_Flag.UNSET, exposed=frozenset())


@final
class RequireHiddenSettingsInput(ProjectRule):
    id = "require-hidden-settings-input"
    code = "SARJ575"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Hide validation inputs on settings classes that load secrets.",
        rationale="A pydantic-settings ValidationError echoes the loaded input. One missing required field prints the whole input mapping, including every secret already read from the environment, and SecretStr masks only the validated value, not that raw input.",
        remediation="Set hide_input_in_errors=True in the model_config of this class or of a shared settings base it inherits from.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "A field is secret when its annotation is SecretStr or SecretBytes, or when it holds plain str/bytes text and its name or a literal alias/validation_alias passes the shared secret-name vocabulary. Paths, numbers, flags and nested models are references or structure, not credential text, and stay out of scope.",
            "The flag is read the way Pydantic merges configuration: class keywords, then the class's own model_config, then its bases from last to first. Literal ConfigDict, SettingsConfigDict, dict() and dict-literal configurations are read; computed configurations, legacy Config classes, metaclasses, external model_config writes and unresolved bases make the class opaque and silent.",
            "Bases resolve through the project index. Each exposure is reported once, at the first settings class that leaves it visible; subclasses of a reported base stay silent for the inherited fields.",
            "Only module-level classes are inspected. Files with wildcard imports, rebound pydantic or pydantic_settings names, or dynamic namespace access are skipped.",
        ),
        examples=(
            RuleExample(
                example_id="exposed-secret-settings",
                title="A settings secret is echoed by validation errors",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        _IMPORTS + "class Settings(BaseSettings):\n    api_token: SecretStr\n    region: str\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="hidden-secret-settings",
                title="The settings class hides validation inputs",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        _IMPORTS
                        + "class Settings(BaseSettings):\n"
                        + "    model_config = SettingsConfigDict(hide_input_in_errors=True)\n"
                        + "    api_token: SecretStr\n    region: str\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="exposed-imported-base",
                scenario="inherited-config",
                title="An imported base leaves its subclass's secret visible",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "\n"),
                    ExampleFile.python(
                        "app/base.py",
                        _IMPORTS
                        + "class SecretSettings(BaseSettings):\n"
                        + "    model_config = SettingsConfigDict(env_prefix='APP_')\n",
                    ),
                    ExampleFile.python(
                        "app/settings.py",
                        "from app.base import SecretSettings\nclass Settings(SecretSettings):\n    client_secret: str\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="hidden-imported-base",
                scenario="inherited-config",
                title="A subclass inherits the flag from an imported base",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "\n"),
                    ExampleFile.python(
                        "app/base.py",
                        _IMPORTS
                        + "class SecretSettings(BaseSettings):\n"
                        + "    model_config = SettingsConfigDict(hide_input_in_errors=True)\n",
                    ),
                    ExampleFile.python(
                        "app/settings.py",
                        "from app.base import SecretSettings\nclass Settings(SecretSettings):\n    client_secret: str\n",
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
        tree = context.tree
        if tree is None or context.generated:
            return []
        candidates = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.bases]
        if not candidates or model_namespace_hazards(
            context, include_settings=True, escape_symbols=MODEL_BASES | SETTINGS_BASES
        ):
            return []
        resolver = _SettingsResolver(context)
        unit = resolver.contracts.unit
        if unit is None:
            return []
        findings: list[Diagnostic] = []
        for declaration in candidates:
            facts = resolver.facts(DeclaredClass(unit, declaration))
            if facts is None or not facts.reported or context.suppressions.is_suppressed(declaration.lineno, self.code):
                continue
            findings.append(_diagnostic(declaration, facts.exposed, context, self.code))
        return findings


class _SettingsResolver:
    def __init__(self, context: PythonFileContext) -> None:
        self.contracts = DeclaredContracts(context)
        self._facts: dict[ast.ClassDef, _SettingsFacts | None] = {}
        self._external_config: dict[ast.Module, frozenset[str]] = {}

    def facts(self, model: DeclaredClass) -> _SettingsFacts | None:
        declaration = model.declaration
        if declaration in self._facts:
            return self._facts[declaration]
        self._facts[declaration] = None
        facts = self._resolve(model)
        self._facts[declaration] = facts
        return facts

    def _resolve(self, model: DeclaredClass) -> _SettingsFacts | None:
        imports = self.contracts.imports_for(model.unit)
        if not self._plain_declaration(model, imports) or (own_flag := _own_flag(model.declaration, imports)) is None:
            return None
        inherited = self._inherited(model, imports)
        if inherited is None:
            return None
        exposed = set(inherited.exposed)
        semantics = self.contracts.semantics_for(model.unit)
        for name, field in self.contracts.model_fields(model).items():
            if _secret_field(name, field, semantics):
                exposed.add(name)
            else:
                exposed.discard(name)
        flag = inherited.flag if own_flag is _Flag.UNSET else own_flag
        return _SettingsFacts(inherited.settings, flag, frozenset(exposed))

    def _inherited(self, model: DeclaredClass, imports: ImportIndex) -> _SettingsFacts | None:
        settings = False
        flag = _Flag.UNSET
        exposed: set[str] = set()
        for base in model.declaration.bases:
            facts = self._base_facts(base, model, imports)
            if facts is None:
                return None
            settings = settings or facts.settings
            if facts.flag is not _Flag.UNSET:
                flag = facts.flag
            if not facts.reported:
                exposed |= facts.exposed
        return _SettingsFacts(settings, flag, frozenset(exposed))

    def _base_facts(self, base: ast.expr, model: DeclaredClass, imports: ImportIndex) -> _SettingsFacts | None:
        if stable_native(base, model) and imports.resolves(base, sources=SETTINGS_SOURCES, symbol="BaseSettings"):
            return _NATIVE_SETTINGS
        if _neutral_base(base, model, imports):
            return _NEUTRAL
        parent = self.contracts.class_type(base, model.unit)
        return self.facts(parent) if parent is not None else None

    def _plain_declaration(self, model: DeclaredClass, imports: ImportIndex) -> bool:
        declaration = model.declaration
        tree = model.unit.tree
        return (
            tree is not None
            and not declaration.type_params
            and all(
                imports.resolves(node, sources=TYPING_SOURCES, symbol="final") for node in declaration.decorator_list
            )
            and declaration.name not in self._externally_configured(tree)
        )

    def _externally_configured(self, tree: ast.Module) -> frozenset[str]:
        names = self._external_config.get(tree)
        if names is None:
            names = self._external_config[tree] = frozenset(
                node.value.id
                for node in nodes(tree, ast.Attribute)
                if node.attr == "model_config" and isinstance(node.value, ast.Name)
            )
        return names


def _own_flag(declaration: ast.ClassDef, imports: ImportIndex) -> _Flag | None:
    flag: _Flag | None = _Flag.UNSET
    for statement in declaration.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id="model_config")], value=value)
                | ast.AnnAssign(target=ast.Name(id="model_config"), value=ast.expr() as value)
            ):
                flag = _config_flag(value, imports)
            case ast.ClassDef(name="Config") | ast.AugAssign(target=ast.Name(id="model_config")):
                return None
            case _:
                continue
        if flag is None:
            return None
    for keyword in declaration.keywords:
        if keyword.arg is None or keyword.arg == "metaclass":
            return None
        if keyword.arg == _FLAG:
            return _literal_flag(keyword.value)
    return flag


def _config_flag(value: ast.expr, imports: ImportIndex) -> _Flag | None:
    match value:
        case ast.Call(func=func, args=[], keywords=keywords) if _config_constructor(func, imports):
            entries = [(keyword.arg, keyword.value) for keyword in keywords]
        case ast.Dict(keys=keys, values=values):
            entries = [(_literal_key(key), item) for key, item in zip(keys, values, strict=True)]
        case _:
            return None
    flag: _Flag | None = _Flag.UNSET
    for key, item in entries:
        if key is None:
            flag = None
        elif key == _FLAG:
            flag = _literal_flag(item)
    return flag


def _literal_key(key: ast.expr | None) -> str | None:
    return key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None


def _literal_flag(value: ast.expr) -> _Flag | None:
    match value:
        case ast.Constant(value=bool() as hidden):
            return _Flag.HIDDEN if hidden else _Flag.SHOWN
        case _:
            return None


def _config_constructor(func: ast.expr, imports: ImportIndex) -> bool:
    return (
        imports.resolves(func, sources=_CONFIG_SOURCES, symbol="ConfigDict")
        or imports.resolves(func, sources=SETTINGS_SOURCES, symbol="SettingsConfigDict")
        or (isinstance(func, ast.Name) and func.id == "dict" and imports.builtin_is_unshadowed("dict"))
    )


def _neutral_base(base: ast.expr, model: DeclaredClass, imports: ImportIndex) -> bool:
    target = base.value if isinstance(base, ast.Subscript) else base
    if isinstance(target, ast.Name) and target.id == "object":
        return imports.builtin_is_unshadowed("object")
    return stable_native(target, model) and any(
        imports.resolves(target, sources=sources, symbol=symbol) for sources, symbol in _NEUTRAL_BASES
    )


def _secret_field(name: str, field: ast.AnnAssign, semantics: AnnotationSemantics) -> bool:
    imports = semantics.imports
    members = semantics.transparent_members(field.annotation)
    if any(imports.resolved_symbol(member, sources=_SECRET_SOURCES) in _SECRET_TYPES for member in members):
        return True
    return _text_valued(members, imports) and any(is_secret_name(label) for label in (name, *_aliases(field, imports)))


def _text_valued(members: Sequence[ast.expr], imports: ImportIndex) -> bool:
    values = [member for member in members if not (isinstance(member, ast.Constant) and member.value is None)]
    return bool(values) and all(
        isinstance(member, ast.Name) and member.id in _TEXT_TYPES and imports.builtin_is_unshadowed(member.id)
        for member in values
    )


def _aliases(field: ast.AnnAssign, imports: ImportIndex) -> Iterator[str]:
    for node in ast.walk(field):
        if not isinstance(node, ast.Call) or not imports.resolves(node.func, sources=FIELD_SOURCES, symbol="Field"):
            continue
        for keyword in node.keywords:
            if keyword.arg in _ALIAS_KEYWORDS:
                yield from (
                    alias.value
                    for alias in ast.walk(keyword.value)
                    if isinstance(alias, ast.Constant) and isinstance(alias.value, str)
                )


def _diagnostic(
    declaration: ast.ClassDef, exposed: frozenset[str], context: PythonFileContext, code: str
) -> Diagnostic:
    fields = ", ".join(sorted(exposed))
    return Diagnostic(
        context.path,
        declaration.lineno,
        declaration.col_offset + 1,
        code,
        f"Set hide_input_in_errors=True in the model_config of {declaration.name} or a shared settings base; "
        f"a ValidationError otherwise prints the loaded secret input ({fields}).",
        severity=Severity.ERROR,
    )
