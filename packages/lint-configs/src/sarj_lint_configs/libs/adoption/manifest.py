"""The one file a consumer repo pins, and the versions everything else must match."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from importlib.metadata import PackageNotFoundError, version
import json
import re
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from packaging.version import InvalidVersion, Version

from sarj_lint_configs._meta import CONFIGS_DIR, __version__


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


MANIFEST_NAME: Final = ".sarj-standards.toml"
MANIFEST_SCHEMA: Final = 2
_CONFIGS_KEY: Final = "configs"
Profile = Literal["standard", "application"]
PROFILES: Final[tuple[Profile, ...]] = ("standard", "application")
HookManager = Literal["pre-commit", "lefthook", "none"]
HOOK_MANAGERS: Final[tuple[HookManager, ...]] = ("pre-commit", "lefthook", "none")

PEERS_JSON: Final = CONFIGS_DIR / "eslint.peers.json"

#: Sibling distributions pinned exactly by `sarj-lint-configs`.
LINT_CONFIGS: Final = "sarj-lint-configs"
_PYTHON_LINT: Final = "sarj-python-lint"
SIBLING_PACKAGES: Final = (_PYTHON_LINT, "sarj-sql-lint", "sarj-iac-lint")
_HOOK_ALIASES: Final = MappingProxyType(
    {
        "ban-create-trigger": "sql",
        "ban-postgres-enums": "sql",
        "fakes-in-shared-location": "python",
        "no-raw-connection-in-tests": "python",
        "suppression-ratchet": "python",
    }
)


def adopted_version() -> str:
    """Report the `sarj-lint-configs` version this environment provides."""
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
SHARED_CONFIGS: Final = ("markdownlint", "taplo", "yamllint")
ALL_CONFIGS: Final = (*PYTHON_CONFIGS, *TYPESCRIPT_CONFIGS, *SHARED_CONFIGS)


@dataclass(frozen=True)
class ExclusionOverride:
    """Rule exclusions scoped to repository-relative path patterns."""

    paths: tuple[str, ...]
    rules: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Manifest:
    """A consumer repo's declared adoption of this package."""

    version: str
    configs: tuple[str, ...]
    python_dest: str
    typescript_dest: str
    profile: Profile = "standard"
    verify_paths: tuple[str, ...] = (".",)
    python_baseline: str | None = None
    hook_manager: HookManager = "pre-commit"
    schema: int = dataclass_field(default=MANIFEST_SCHEMA, compare=False)
    disabled_capabilities: tuple[str, ...] = dataclass_field(default=(), compare=False)
    excluded_paths: tuple[str, ...] = ()
    excluded_rules: tuple[str, ...] = ()
    exclusion_overrides: tuple[ExclusionOverride, ...] = ()

    def render(self) -> str:
        """Serialise to the TOML text written at the repo root."""
        disabled = tuple(name for name in ALL_CONFIGS if name not in self.configs)
        disabled_text = ", ".join(f'"{name}"' for name in disabled)
        sections = [
            (
                "# Managed by `sarj-standards setup`; commit this file.\n"
                f"schema = {MANIFEST_SCHEMA}\n"
                f'bundle = "{self.version}"\n'
                f'profile = "{self.profile}"\n'
                'rule_profile = "all"\n'
                "\n"
                "[capabilities]\n"
                f"disable = [{disabled_text}]\n"
                "\n"
                "[artifacts]\n"
                'durable = ["**/README.md", "docs/**", "**/docs/**", "architecture/**", '
                '"**/adr/**", ".github/**", "**/AGENTS.md", "**/CLAUDE.md"]\n'
                "\n"
                "[dest]\n"
                f'python = "{self.python_dest}"\n'
                f'typescript = "{self.typescript_dest}"\n'
                "\n"
                "[hooks]\n"
                f'manager = "{self.hook_manager}"\n'
            )
        ]
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
        if self.python_baseline is not None:
            sections.append(f'\n[gradual]\npython_baseline = "{self.python_baseline}"\n')
        return "".join(sections)


def as_table(value: object) -> dict[str, object]:
    """Read an untyped mapping as a string-keyed table of unknown values."""
    if not isinstance(value, dict):
        return {}
    # Centralize untyped-parser narrowing so downstream tables stay typed.
    entries: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
        if isinstance(key, str):
            entries[key] = item  # ruff: ignore[manual-dict-comprehension] - pyright needs narrowing
    return entries


def text_field(table: Mapping[str, object], key: str) -> str | None:
    """Read one string out of an untyped table."""
    value = table.get(key)
    return value if isinstance(value, str) else None


def list_field(table: Mapping[str, object], key: str) -> list[object]:
    """Read one list out of an untyped table."""
    value = table.get(key)
    return value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType] — a narrowed `list` from an untyped parser has Unknown leaves


def table_field(table: Mapping[str, object], key: str) -> dict[str, object]:
    """Read one nested table out of an untyped table."""
    return as_table(table.get(key))


def default_configs(*, has_python: bool, has_typescript: bool) -> tuple[str, ...]:
    """Pick the config set for a repo's detected ecosystems."""
    selected: set[str] = set(SHARED_CONFIGS)
    if has_python:
        selected.update(PYTHON_CONFIGS)
    if has_typescript:
        selected.update(TYPESCRIPT_CONFIGS)
    order = (*PYTHON_CONFIGS, *TYPESCRIPT_CONFIGS, *SHARED_CONFIGS)
    return tuple(name for name in order if name in selected)


def manifest_path(root: Path) -> Path:
    """Locate the manifest for a repo root."""
    return root / MANIFEST_NAME


def load(root: Path) -> Manifest | None:  # ruff: ignore[too-many-locals] - one validation boundary keeps manifest errors coherent.
    """Read a repo's manifest."""
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path} is not valid TOML: {exc}"
        raise ValueError(msg) from exc

    data = as_table(parsed)
    raw_schema = data.get("schema", 1)
    if type(raw_schema) is not int or raw_schema not in {1, MANIFEST_SCHEMA}:
        msg = f"{path} `schema` must be one of: 1, {MANIFEST_SCHEMA}"
        raise ValueError(msg)
    schema = raw_schema
    declared = text_field(data, "bundle" if schema == MANIFEST_SCHEMA else "version")
    if schema == MANIFEST_SCHEMA and data.get("rule_profile", "all") != "all":
        msg = f"{path} `rule_profile` currently supports only: all"
        raise ValueError(msg)
    raw_profile = data.get("profile", "standard")
    capabilities_table = table_field(data, "capabilities")
    disabled = _string_list(capabilities_table, "disable", label="manifest [capabilities].disable")
    if schema == 1:
        names = list_field(data, _CONFIGS_KEY)
        declares_a_list = isinstance(_configs_entry(data), list)
    else:
        unknown_capabilities = sorted(set(disabled) - set(ALL_CONFIGS))
        if unknown_capabilities:
            msg = f"manifest disables unknown capabilities: {', '.join(unknown_capabilities)}"
            raise ValueError(msg)
        names = [name for name in ALL_CONFIGS if name not in disabled]
        declares_a_list = True
    if declared is None or not declares_a_list:
        fields = "`bundle` and `[capabilities]`" if schema == MANIFEST_SCHEMA else "`version` and `configs`"
        msg = f"{path} must set a string {fields} declaration"
        raise TypeError(msg)
    try:
        Version(declared)
    except InvalidVersion as exc:
        field = "bundle" if schema == MANIFEST_SCHEMA else "version"
        msg = f"{path} `{field}` must be a valid PEP 440 version"
        raise ValueError(msg) from exc
    if not all(isinstance(name, str) for name in names):
        msg = f"{path} `configs` must contain only strings"
        raise TypeError(msg)
    if not isinstance(raw_profile, str) or raw_profile not in PROFILES:
        msg = f"{path} `profile` must be one of: {', '.join(PROFILES)}"
        raise ValueError(msg)
    profile: Profile = raw_profile

    dest_table = table_field(data, "dest")
    verify_table = table_field(data, "verify")
    gradual_table = table_field(data, "gradual")
    hooks_table = table_field(data, "hooks")
    exclude_table = table_field(data, "exclude")
    raw_hook_manager = hooks_table.get("manager", "pre-commit")
    if not isinstance(raw_hook_manager, str) or raw_hook_manager not in HOOK_MANAGERS:
        msg = f"manifest [hooks].manager must be one of: {', '.join(HOOK_MANAGERS)}"
        raise ValueError(msg)
    hook_manager: HookManager = raw_hook_manager
    return Manifest(
        version=declared,
        configs=tuple(name for name in names if isinstance(name, str)),
        python_dest=_dest_value(dest_table, "python"),
        typescript_dest=_dest_value(dest_table, "typescript"),
        profile=profile,
        verify_paths=_verify_paths(root, verify_table),
        python_baseline=_optional_contained_path(root, gradual_table, "python_baseline"),
        hook_manager=hook_manager,
        schema=schema,
        disabled_capabilities=disabled,
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


def _string_list(table: Mapping[str, object], key: str, *, label: str) -> tuple[str, ...]:
    if key not in table:
        return ()
    values = list_field(table, key)
    if not all(type(value) is str and value for value in values):
        msg = f"{label} must contain only non-empty strings"
        raise TypeError(msg)
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str)))


def _path_patterns(root: Path, table: Mapping[str, object], key: str) -> tuple[str, ...]:
    patterns = _string_list(table, key, label=f"manifest [exclude].{key}")
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        if normalized.startswith(("/", "!")) or ".." in normalized.split("/"):
            msg = f"manifest exclusion pattern must be a repository-relative denylist pattern: {pattern}"
            raise ValueError(msg)
        if normalized in {MANIFEST_NAME, f"**/{MANIFEST_NAME}"}:
            msg = "manifest exclusion cannot hide the Standards manifest"
            raise ValueError(msg)
        _ = root
    return patterns


def _rule_selectors(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    selectors = _string_list(table, key, label=f"manifest [exclude].{key}")
    for selector in selectors:
        engine, separator, rule = selector.partition(":")
        if (
            not separator
            or engine not in {"ruff", "basedpyright", "eslint", "python", "sql", "iac", "text"}
            or not rule
        ):
            msg = f"manifest rule exclusion must use a canonical engine:rule selector: {selector}"
            raise ValueError(msg)
    return selectors


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


def _configs_entry(table: Mapping[str, object]) -> object:
    """Read the raw `configs` entry so its TYPE can be validated, not just its contents."""
    return table.get(_CONFIGS_KEY)


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


def _optional_contained_path(root: Path, table: dict[str, object], key: str) -> str | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, str) or not value:
        msg = f"manifest [gradual].{key} must be a non-empty string"
        raise TypeError(msg)
    try:
        (root / value).resolve().relative_to(root.resolve())
    except ValueError as exc:
        msg = f"manifest [gradual].{key} escapes repository root: {value}"
        raise ValueError(msg) from exc
    return value


def record_python_baseline(root: Path, relative_path: str) -> None:
    """Record the shrink-only baseline while preserving consumer-owned manifest tables."""
    from . import (  # ruff: ignore[import-outside-top-level] -- breaks an adoption transaction import cycle.
        transaction,
    )

    _ = _optional_contained_path(root, {"python_baseline": relative_path}, "python_baseline")
    path = manifest_path(root)
    transaction.validate_targets(root, (path,))
    text = path.read_text(encoding="utf-8")
    parsed: object = tomllib.loads(text)
    gradual = table_field(as_table(parsed), "gradual")
    if "python_baseline" in gradual:
        text = re.sub(
            r'(?m)^(python_baseline\s*=\s*)["\'][^"\']*["\']\s*$',
            rf'\g<1>"{relative_path}"',
            text,
            count=1,
        )
    elif "[gradual]" in text:
        text = text.replace("[gradual]\n", f'[gradual]\npython_baseline = "{relative_path}"\n', 1)
    else:
        separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        text += f'{separator}[gradual]\npython_baseline = "{relative_path}"\n'
    transaction.validate_targets(root, (path,))
    _ = path.write_text(text, encoding="utf-8")


def installed_versions() -> dict[str, str]:
    """Report the versions of every Sarj distribution in the current environment."""
    found = {LINT_CONFIGS: adopted_version()}
    for name in SIBLING_PACKAGES:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def expected_precommit_rev(hook_ids: Sequence[str] = ()) -> str | None:
    """Derive the `rev:` a repo's pre-commit config must carry."""
    if not hook_ids:
        installed = text_field(installed_versions(), _PYTHON_LINT)
        return None if installed is None else f"python-v{installed}"
    if "sarj-standards" in hook_ids:
        return f"lint-configs-v{adopted_version()}"
    from sarj_lint_configs.libs.repository import (  # ruff: ignore[import-outside-top-level] -- avoid adoption import cycle
        ledger,
    )

    rules = ledger.load().rules
    families: set[str] = set()
    for hook_id in hook_ids:
        rule_id = hook_id.removeprefix("sarj-")
        if alias := _HOOK_ALIASES.get(rule_id):
            families.add(alias)
        elif rule_id.endswith("-iac") and rule_id.removesuffix("-iac") in rules.get("iac", ()):
            families.add("iac")
        elif rule_id in rules.get("python", ()):
            families.add("python")
        elif rule_id in rules.get("sql", ()):
            families.add("sql")
        elif rule_id in rules.get("iac", ()):
            families.add("iac")
        else:
            return None
    if len(families) != 1:
        return f"lint-configs-v{adopted_version()}"
    family = next(iter(families))
    installed = text_field(installed_versions(), f"sarj-{family}-lint")
    return None if installed is None else f"{family}-v{installed}"


def eslint_peers() -> dict[str, str]:
    """Read the tested npm version set for the bundled ESLint config."""
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    table = table_field(as_table(parsed), "peers")
    if not table:
        msg = f"{PEERS_JSON} must contain a `peers` object"
        raise TypeError(msg)
    return {name: pin for name, pin in table.items() if isinstance(pin, str)}


def eslint_overrides() -> dict[str, object]:
    """Read the npm `overrides` the peer set needs to install at all."""
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    return table_field(as_table(parsed), "npmOverrides")
