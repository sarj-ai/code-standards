from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final, Literal

from packaging.version import InvalidVersion, Version

from sarj_standards._meta import CONFIGS_DIR, __version__


if TYPE_CHECKING:
    from collections.abc import Mapping


MANIFEST_NAME: Final = ".sarj-standards.toml"
MANIFEST_SCHEMA: Final = 3
Profile = Literal["standard", "application"]
PROFILES: Final[tuple[Profile, ...]] = ("standard", "application")
HookManager = Literal["pre-commit", "lefthook", "none"]
HOOK_MANAGERS: Final[tuple[HookManager, ...]] = ("pre-commit", "lefthook", "none")

PEERS_JSON: Final = CONFIGS_DIR / "eslint.peers.json"
_ESLINT_RULE_KEY: Final = re.compile(
    r'^\s+"(?P<rule>[^"]+)":\s*(?:"(?:off|warn|error)"|\[)',
    re.MULTILINE,
)
_SARJ_RULE_ENGINES: Final = frozenset({"python", "sql", "iac", "text"})


class _UpstreamRuleEngine(StrEnum):
    ESLINT = "eslint"
    SHELLCHECK = "shellcheck"


#: Sibling distributions pinned exactly by `code-standards`.
LINT_CONFIGS: Final = "code-standards"
_PYTHON_LINT: Final = "sarj-python-lint"
SIBLING_PACKAGES: Final = (_PYTHON_LINT, "sarj-sql-lint", "sarj-iac-lint")


def adopted_version() -> str:
    if __version__ != "0.0.0.dev0":
        return __version__
    source_project = CONFIGS_DIR.parents[2] / "pyproject.toml"
    if not source_project.is_file():
        return __version__
    try:
        parsed: object = tomllib.loads(source_project.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return __version__
    declared = text_field(table_field(as_table(parsed), "project"), "version")
    return __version__ if declared is None else declared


#: Config bundle selected for each detected ecosystem.
PYTHON_CONFIGS: Final = ("ruff", "pyright")
TYPESCRIPT_CONFIGS: Final = ("eslint",)
SHARED_CONFIGS: Final = ("markdownlint", "shellcheck", "taplo", "yamllint")
ALL_CONFIGS: Final = (*PYTHON_CONFIGS, *TYPESCRIPT_CONFIGS, *SHARED_CONFIGS)
DEFAULT_DURABLE_ARTIFACTS: Final = (
    "**/README.md",
    "docs/**",
    "**/docs/**",
    "architecture/**",
    "**/adr/**",
    ".github/**",
    "**/AGENTS.md",
    "**/CLAUDE.md",
)


@dataclass(frozen=True)
class ExclusionOverride:
    paths: tuple[str, ...]
    rules: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Manifest:
    version: str
    configs: tuple[str, ...]
    python_dest: str
    typescript_dest: str
    profile: Profile = "standard"
    verify_paths: tuple[str, ...] = (".",)
    hook_manager: HookManager = "pre-commit"
    disabled_capabilities: tuple[str, ...] = dataclass_field(default=(), compare=False)
    excluded_paths: tuple[str, ...] = ()
    excluded_rules: tuple[str, ...] = ()
    exclusion_overrides: tuple[ExclusionOverride, ...] = ()
    durable_artifacts: tuple[str, ...] = DEFAULT_DURABLE_ARTIFACTS
    text_excluded_paths: tuple[str, ...] = ()
    doctor_excluded_paths: tuple[str, ...] = ()
    diagnostic_baseline: str | None = None
    ci_bootstrap: tuple[str, ...] = ()

    def render(self) -> str:
        disabled = tuple(name for name in ALL_CONFIGS if name not in self.configs)
        disabled_text = ", ".join(f'"{name}"' for name in disabled)
        durable_text = ", ".join(json.dumps(value) for value in self.durable_artifacts)
        sections = [
            (
                "# Managed by `code-standards setup`; commit this file.\n"
                f"schema = {MANIFEST_SCHEMA}\n"
                f'bundle = "{self.version}"\n'
                f'profile = "{self.profile}"\n'
                'rule_profile = "all"\n'
                "\n"
                "[capabilities]\n"
                f"disable = [{disabled_text}]\n"
                "\n"
                "[artifacts]\n"
                f"durable = [{durable_text}]\n"
                "\n"
                "[dest]\n"
                f'python = "{self.python_dest}"\n'
                f'typescript = "{self.typescript_dest}"\n'
                "\n"
                "[hooks]\n"
                f'manager = "{self.hook_manager}"\n'
            )
        ]
        if self.verify_paths != (".",):
            paths = ", ".join(json.dumps(value) for value in self.verify_paths)
            sections.append(f"\n[verify]\npaths = [{paths}]\n")
        if self.excluded_paths or self.excluded_rules:
            paths = ", ".join(json.dumps(value) for value in self.excluded_paths)
            rules = ", ".join(json.dumps(value) for value in self.excluded_rules)
            sections.append(f"\n[exclude]\npaths = [{paths}]\nrules = [{rules}]\n")
        for override in self.exclusion_overrides:
            paths = ", ".join(json.dumps(value) for value in override.paths)
            rules = ", ".join(json.dumps(value) for value in override.rules)
            sections.append(
                f"\n[[exclude.overrides]]\npaths = [{paths}]\nrules = [{rules}]\nreason = {json.dumps(override.reason)}\n"
            )
        if self.text_excluded_paths:
            paths = ", ".join(json.dumps(value) for value in self.text_excluded_paths)
            sections.append(f"\n[text]\nexclude = [{paths}]\n")
        if self.doctor_excluded_paths:
            paths = ", ".join(json.dumps(value) for value in self.doctor_excluded_paths)
            sections.append(f"\n[doctor]\nexclude = [{paths}]\n")
        if self.diagnostic_baseline is not None:
            sections.append(f"\n[baseline]\ndiagnostics = {json.dumps(self.diagnostic_baseline)}\n")
        if self.ci_bootstrap:
            commands = ", ".join(json.dumps(command) for command in self.ci_bootstrap)
            sections.append(f"\n[ci]\nbootstrap = [{commands}]\n")
        return "".join(sections)


def as_table(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    # Centralize untyped-parser narrowing so downstream tables stay typed.
    entries: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
        if isinstance(key, str):
            entries[key] = item  # ruff: ignore[manual-dict-comprehension] - pyright needs narrowing
    return entries


def text_field(table: Mapping[str, object], key: str) -> str | None:
    value = table.get(key)
    return value if isinstance(value, str) else None


def list_field(table: Mapping[str, object], key: str) -> list[object]:
    value = table.get(key)
    return value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType] — a narrowed `list` from an untyped parser has Unknown leaves


def table_field(table: Mapping[str, object], key: str) -> dict[str, object]:
    return as_table(table.get(key))


def default_configs(*, has_python: bool, has_typescript: bool) -> tuple[str, ...]:
    selected: set[str] = set(SHARED_CONFIGS)
    if has_python:
        selected.update(PYTHON_CONFIGS)
    if has_typescript:
        selected.update(TYPESCRIPT_CONFIGS)
    order = (*PYTHON_CONFIGS, *TYPESCRIPT_CONFIGS, *SHARED_CONFIGS)
    return tuple(name for name in order if name in selected)


def manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def load(root: Path) -> Manifest | None:  # ruff: ignore[too-many-locals] - one validation boundary keeps manifest errors coherent.
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path} is not valid TOML: {exc}"
        raise ValueError(msg) from exc

    data = as_table(parsed)
    raw_schema = data.get("schema")
    if type(raw_schema) is not int or raw_schema != MANIFEST_SCHEMA:
        msg = f"{path} `schema` must equal {MANIFEST_SCHEMA}"
        raise ValueError(msg)
    legacy_fields = tuple(field for field in ("version", "configs", "gradual") if field in data)
    if legacy_fields:
        msg = f"{path} uses removed manifest fields: {', '.join(legacy_fields)}"
        raise ValueError(msg)
    declared = text_field(data, "bundle")
    if data.get("rule_profile", "all") != "all":
        msg = f"{path} `rule_profile` currently supports only: all"
        raise ValueError(msg)
    raw_profile = data.get("profile", "standard")
    capabilities_table = _manifest_table(data, "capabilities")
    disabled = _string_list(capabilities_table, "disable", label="manifest [capabilities].disable")
    unknown_capabilities = sorted(set(disabled) - set(ALL_CONFIGS))
    if unknown_capabilities:
        msg = f"manifest disables unknown capabilities: {', '.join(unknown_capabilities)}"
        raise ValueError(msg)
    names = [name for name in ALL_CONFIGS if name not in disabled]
    if declared is None:
        msg = f"{path} must set a string `bundle` declaration"
        raise TypeError(msg)
    try:
        Version(declared)
    except InvalidVersion as exc:
        msg = f"{path} `bundle` must be a valid PEP 440 version"
        raise ValueError(msg) from exc
    if not isinstance(raw_profile, str) or raw_profile not in PROFILES:
        msg = f"{path} `profile` must be one of: {', '.join(PROFILES)}"
        raise ValueError(msg)
    profile: Profile = raw_profile

    dest_table = _manifest_table(data, "dest")
    verify_table = _manifest_table(data, "verify")
    hooks_table = _manifest_table(data, "hooks")
    exclude_table = _manifest_table(data, "exclude")
    artifacts_table = _manifest_table(data, "artifacts")
    text_table = _manifest_table(data, "text")
    doctor_table = _manifest_table(data, "doctor")
    baseline_table = _manifest_table(data, "baseline")
    ci_table = _manifest_table(data, "ci")
    raw_hook_manager = hooks_table.get("manager", "pre-commit")
    if not isinstance(raw_hook_manager, str) or raw_hook_manager not in HOOK_MANAGERS:
        msg = f"manifest [hooks].manager must be one of: {', '.join(HOOK_MANAGERS)}"
        raise ValueError(msg)
    hook_manager: HookManager = raw_hook_manager
    return Manifest(
        version=declared,
        configs=tuple(names),
        python_dest=_dest_value(dest_table, "python"),
        typescript_dest=_dest_value(dest_table, "typescript"),
        profile=profile,
        verify_paths=_verify_paths(root, verify_table),
        hook_manager=hook_manager,
        disabled_capabilities=disabled,
        excluded_paths=_path_patterns(root, exclude_table, "paths"),
        excluded_rules=_rule_selectors(exclude_table, "rules"),
        exclusion_overrides=_exclusion_overrides(root, exclude_table),
        durable_artifacts=_string_list(
            artifacts_table,
            "durable",
            label="manifest [artifacts].durable",
            default=DEFAULT_DURABLE_ARTIFACTS,
        ),
        text_excluded_paths=_string_list(text_table, "exclude", label="manifest [text].exclude"),
        doctor_excluded_paths=_string_list(doctor_table, "exclude", label="manifest [doctor].exclude"),
        diagnostic_baseline=_relative_file(root, baseline_table, "diagnostics"),
        ci_bootstrap=_ci_bootstrap(ci_table),
    )


def _manifest_table(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"manifest [{key}] must be a table"
        raise TypeError(msg)
    return as_table(value)  # pyright: ignore[reportUnknownArgumentType] -- runtime dict narrowed above; as_table validates keys


def load_for_setup(root: Path) -> Manifest | None:
    try:
        return load(root)
    except ValueError:
        legacy = _load_schema_less_manifest(root)
        if legacy is None:
            raise
        return legacy


def _load_schema_less_manifest(  # ruff: ignore[too-many-locals] -- validate the complete legacy policy atomically.
    root: Path,
) -> Manifest | None:
    path = manifest_path(root)
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    data = as_table(parsed)
    if "schema" in data or "version" not in data or "configs" not in data:
        return None
    declared = text_field(data, "version")
    raw_configs = list_field(data, "configs")
    if declared is None or not all(isinstance(item, str) and item in ALL_CONFIGS for item in raw_configs):
        return None
    try:
        Version(declared)
    except InvalidVersion:
        return None
    raw_profile = data.get("profile", "standard")
    if not isinstance(raw_profile, str) or raw_profile not in PROFILES:
        return None
    profile: Profile = raw_profile
    dest = table_field(data, "dest")
    try:
        python_dest = _dest_value(dest, "python")
        typescript_dest = _dest_value(dest, "typescript")
    except TypeError:
        return None
    gradual_table = table_field(data, "gradual")
    if "python_baseline" in gradual_table:
        _ = _relative_file(root, gradual_table, "python_baseline")
        msg = (
            "cannot losslessly migrate legacy [gradual].python_baseline to the fingerprint-based "
            "[baseline].diagnostics format; preserve the legacy manifest and replace or retire its baseline "
            "before rerunning setup"
        )
        raise ValueError(msg)
    verify_table = table_field(data, "verify")
    hooks_table = table_field(data, "hooks")
    exclude_table = table_field(data, "exclude")
    raw_hook_manager = hooks_table.get("manager", "pre-commit")
    if not isinstance(raw_hook_manager, str) or raw_hook_manager not in HOOK_MANAGERS:
        msg = f"manifest [hooks].manager must be one of: {', '.join(HOOK_MANAGERS)}"
        raise ValueError(msg)
    hook_manager: HookManager = raw_hook_manager
    return Manifest(
        version=declared,
        configs=tuple(dict.fromkeys(item for item in raw_configs if isinstance(item, str))),
        python_dest=python_dest,
        typescript_dest=typescript_dest,
        profile=profile,
        verify_paths=_verify_paths(root, verify_table),
        hook_manager=hook_manager,
        excluded_paths=_path_patterns(root, exclude_table, "paths"),
        excluded_rules=_rule_selectors(exclude_table, "rules"),
        exclusion_overrides=_exclusion_overrides(root, exclude_table),
    )


def _applicable_configs(root: Path) -> tuple[str, ...]:
    has_python = any((root / name).is_file() for name in ("pyproject.toml", "uv.lock", "poetry.lock", "pdm.lock"))
    has_typescript = any(
        path.is_file()
        for path in (
            root / "package.json",
            root / "package-lock.json",
            root / "pnpm-lock.yaml",
            root / "yarn.lock",
            root / "bun.lock",
            root / "bun.lockb",
        )
    )
    return default_configs(has_python=has_python, has_typescript=has_typescript)


def _string_list(
    table: Mapping[str, object],
    key: str,
    *,
    label: str,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if key not in table:
        return default
    values = list_field(table, key)
    if not all(type(value) is str and value for value in values):
        msg = f"{label} must contain only non-empty strings"
        raise TypeError(msg)
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str)))


def _ci_bootstrap(table: Mapping[str, object]) -> tuple[str, ...]:
    commands = _string_list(table, "bootstrap", label="manifest [ci].bootstrap")
    if any(command != command.strip() or "\n" in command or "\r" in command for command in commands):
        msg = "manifest [ci].bootstrap commands must be trimmed single-line strings"
        raise ValueError(msg)
    return commands


def _path_patterns(root: Path, table: Mapping[str, object], key: str) -> tuple[str, ...]:
    patterns = _string_list(table, key, label=f"manifest [exclude].{key}")
    return tuple(validate_excluded_path(root, pattern) for pattern in patterns)


def _rule_selectors(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    selectors = _string_list(table, key, label=f"manifest [exclude].{key}")
    return tuple(validate_excluded_rule(selector) for selector in selectors)


def validate_excluded_path(root: Path, pattern: str) -> str:
    normalized = pattern.replace("\\", "/")
    if normalized.startswith(("/", "!")) or ".." in normalized.split("/"):
        msg = f"manifest exclusion pattern must be a repository-relative denylist pattern: {pattern}"
        raise ValueError(msg)
    if normalized in {".", "*", "**", "**/*"}:
        msg = f"manifest exclusion pattern is too broad: {pattern}"
        raise ValueError(msg)
    if normalized in {MANIFEST_NAME, f"**/{MANIFEST_NAME}"}:
        msg = "manifest exclusion cannot hide the Standards manifest"
        raise ValueError(msg)
    _ = root
    return normalized


def validate_excluded_rule(selector: str) -> str:
    engine, separator, rule = selector.partition(":")
    if (
        not separator
        or engine not in {"ruff", "basedpyright", "eslint", "shellcheck", "python", "sql", "iac", "text"}
        or not rule
        or rule != rule.strip()
    ):
        msg = f"manifest rule exclusion must use a canonical engine:rule selector: {selector}"
        raise ValueError(msg)
    _validate_known_rule(engine, rule, selector)
    return selector


def _validate_known_rule(engine: str, rule: str, selector: str) -> None:
    from sarj_standards.libs.linting import (  # ruff: ignore[import-outside-top-level] -- avoid a manifest/policy import cycle.
        library_policy,
    )
    from sarj_standards.libs.repository import (  # ruff: ignore[import-outside-top-level] -- avoid a manifest/ledger import cycle.
        ledger,
    )

    shipped = ledger.load()
    if engine in _SARJ_RULE_ENGINES:
        known = frozenset((*shipped.rules.get(engine, ()), *shipped.codes.get(engine, ())))
        if engine == "python":
            known |= frozenset(item.id for item in library_policy.CATALOG)
        if rule not in known:
            msg = f"unknown Standards rule exclusion: {selector}"
            raise ValueError(msg)
        return
    try:
        upstream = _UpstreamRuleEngine(engine)
    except ValueError:
        return
    if upstream is _UpstreamRuleEngine.SHELLCHECK:
        if re.fullmatch(r"SC[0-9]{4}", rule) is None:
            msg = f"unknown Standards rule exclusion: {selector}"
            raise ValueError(msg)
        return
    if rule.startswith("@sarj/"):
        known = frozenset(f"@sarj/{name}" for name in shipped.rules.get(ledger.ESLINT, ()))
    elif "/" not in rule:
        config = (CONFIGS_DIR / "eslint.strict.mjs").read_text(encoding="utf-8")
        known = frozenset(match.group("rule") for match in _ESLINT_RULE_KEY.finditer(config))
    else:
        return
    if rule not in known:
        msg = f"unknown Standards rule exclusion: {selector}"
        raise ValueError(msg)


def _exclusion_overrides(root: Path, table: Mapping[str, object]) -> tuple[ExclusionOverride, ...]:
    values = list_field(table, "overrides")
    overrides: list[ExclusionOverride] = []
    for value in values:
        item = as_table(value)
        paths = _path_patterns(root, item, "paths")
        rules = _rule_selectors(item, "rules")
        reason = text_field(item, "reason")
        if not paths or not rules or reason is None or not reason.strip():
            msg = "each [[exclude.overrides]] entry must set non-empty paths, rules, and reason"
            raise ValueError(msg)
        overrides.append(ExclusionOverride(paths, rules, reason))
    return tuple(overrides)


def _dest_value(table: dict[str, object], key: str) -> str:
    if key not in table:
        return "."
    value = table[key]
    if not isinstance(value, str) or not value:
        msg = f"manifest [dest].{key} must be a non-empty string"
        raise TypeError(msg)
    return value


def _verify_paths(root: Path, table: dict[str, object]) -> tuple[str, ...]:
    if "paths" not in table:
        return (".",)
    values = list_field(table, "paths")
    if not values or not all(isinstance(value, str) and value for value in values):
        msg = "manifest [verify].paths must be a non-empty list of non-empty strings"
        raise TypeError(msg)
    paths = tuple(value for value in values if isinstance(value, str))
    for value in paths:
        try:
            (root / value).resolve().relative_to(root.resolve())
        except ValueError as exc:
            msg = f"manifest [verify].paths entry escapes repository root: {value}"
            raise ValueError(msg) from exc
    return paths


def _relative_file(root: Path, table: Mapping[str, object], key: str) -> str | None:
    if key not in table:
        return None
    value = text_field(table, key)
    if value is None or not value.strip():
        msg = f"manifest [baseline].{key} must be a non-empty repository-relative path"
        raise TypeError(msg)
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
        msg = f"manifest [baseline].{key} must be a repository-relative JSON path: {value}"
        raise ValueError(msg)
    try:
        (root / path).resolve().relative_to(root.resolve())
    except ValueError as exc:
        msg = f"manifest [baseline].{key} escapes repository root: {value}"
        raise ValueError(msg) from exc
    return path.as_posix()


def installed_versions() -> dict[str, str]:
    found = {LINT_CONFIGS: adopted_version()}
    for name in SIBLING_PACKAGES:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def eslint_peers() -> dict[str, str]:
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    table = table_field(as_table(parsed), "peers")
    if not table:
        msg = f"{PEERS_JSON} must contain a `peers` object"
        raise TypeError(msg)
    return {name: pin for name, pin in table.items() if isinstance(pin, str)}


def eslint_overrides() -> dict[str, object]:
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    return table_field(as_table(parsed), "npmOverrides")
