from __future__ import annotations

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.linting import library_policy
from sarj_standards.libs.repository import rule_catalog_artifact
from sarj_standards.libs.rules import RuleEngine


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


_RUFF_ALIAS: Final = '# Compatibility alias; all repositories use the same policy.\nextend = "ruff.strict.toml"\n'
_OXLINT_STRICT_TEXT: Final = (
    'import { createStrictOxlintConfig } from "@sarj/oxlint-plugin/config";\n\n'
    "export { createStrictOxlintConfig };\n"
    "export default await createStrictOxlintConfig({ root: import.meta.dirname });\n"
)
_RUFF_MARKER: Final = "[lint.per-file-ignores]"
_RULE_CATALOG: Final = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
_OXLINT_STRICT: Final = Path("packages/standards/src/sarj_standards/configs/oxlint.strict.mjs")
_TYPESCRIPT_PRESET: Final = Path("packages/typescript/src/index.ts")
_ADVISORY_START: Final = "const ADVISORY_RULES = [\n"
_ADVISORY_END: Final = "] as const;"
_RULE_LEVEL = re.compile(r'(?m)^(?P<prefix>\s+"@sarj/(?P<rule>[a-z0-9-]+)":\s*)(?P<array>\[?)"(?:warn|error)"')


def render_ruff_strict() -> str:
    standard = (CONFIGS_DIR / "ruff.strict.toml").read_text(encoding="utf-8")
    standard = _without_generated_policy(standard)
    entries = "".join(
        f"{json.dumps(name)}.msg = {json.dumps(message)}\n" for name, message in sorted(_python_bans().items())
    )
    addition = f"# BEGIN GENERATED LIBRARY POLICY\n{entries}# END GENERATED LIBRARY POLICY\n\n"
    if _RUFF_MARKER not in standard:
        msg = f"ruff.strict.toml is missing generation marker {_RUFF_MARKER!r}"
        raise ValueError(msg)
    return standard.replace(_RUFF_MARKER, addition + _RUFF_MARKER, 1)


def _python_bans() -> Mapping[str, str]:
    return library_policy.python_banned_api()


def _without_generated_policy(source: str) -> str:
    source = re.sub(
        r"(?m)^[ \t]*(?:#|//) BEGIN GENERATED LIBRARY POLICY\n.*?^[ \t]*(?:#|//) END GENERATED LIBRARY POLICY\n",
        "",
        source,
        flags=re.DOTALL,
    )
    return source.replace("\n\n[lint.per-file-ignores]", "\n[lint.per-file-ignores]")


def generated_configs(repository: Path) -> Mapping[Path, str]:
    ruff = render_ruff_strict()
    configs_dir = repository / _OXLINT_STRICT.parent
    configs = {
        configs_dir / "ruff.strict.toml": ruff,
        configs_dir / "oxlint.strict.mjs": _OXLINT_STRICT_TEXT,
        configs_dir / "ruff.application.toml": _RUFF_ALIAS,
    }
    if (repository / _TYPESCRIPT_PRESET).is_file():
        configs[repository / ".ruff-strict.toml"] = ruff
        configs[repository / "packages/typescript/src/library-policy.ts"] = (
            "// Generated from the Standards library catalog.\n"
            f"export const LIBRARY_POLICY = {json.dumps(_typescript_runtime_bans(), indent=2, sort_keys=True)} as const;\n"
            f"export const LIBRARY_IMPORT_RESTRICTIONS = {json.dumps(_typescript_bans(), indent=2, sort_keys=True)} as const;\n"
        )
    return configs


def _typescript_bans() -> Sequence[Mapping[str, object]]:
    return tuple(
        {"name": entry.name, "message": entry.message} for entry in library_policy.typescript_restricted_imports()
    )


def _typescript_runtime_bans() -> list[dict[str, str]]:
    restrictions: list[dict[str, str]] = []
    for entry in library_policy.catalog():
        if entry.ecosystem != "typescript":
            continue
        restrictions.extend(
            {
                "id": entry.id,
                "module": module,
                "replacement": entry.replacement,
                "note": entry.message,
            }
            for module in entry.imports
        )
    return restrictions


def warning_level_artifacts(repository: Path) -> Mapping[Path, str]:
    warnings = frozenset(
        str(selector.rule_id)
        for selector in rule_catalog_artifact.warning_selectors(repository / _RULE_CATALOG)
        if selector.engine is RuleEngine.OXLINT
    )

    preset_path = repository / _TYPESCRIPT_PRESET
    strict_path = repository / _OXLINT_STRICT
    preset = preset_path.read_text(encoding="utf-8")
    rendered_preset = _render_typescript_preset(preset, warnings)
    return {
        preset_path: rendered_preset,
        strict_path: _OXLINT_STRICT_TEXT,
    }


def sync_warning_levels(repository: Path, *, check: bool, writer: Callable[[Path, str], None] | None = None) -> bool:
    expected = warning_level_artifacts(repository)
    if check:
        return all(path.is_file() and path.read_text(encoding="utf-8") == text for path, text in expected.items())
    for path, text in expected.items():
        if writer is None:
            path.write_text(text, encoding="utf-8")
        else:
            writer(path, text)
    return True


def _render_typescript_preset(source: str, warnings: frozenset[str]) -> str:
    if source.count(_ADVISORY_START) != 1 or source.count(_ADVISORY_END) < 1:
        msg = "TypeScript preset is missing the advisory-rule generation markers"
        raise ValueError(msg)
    start = source.index(_ADVISORY_START) + len(_ADVISORY_START)
    end = source.index(_ADVISORY_END, start)
    advisory = "".join(f'  "@sarj/{name}",\n' for name in sorted(warnings))
    with_advisory = source[:start] + advisory + source[end:]
    return _render_rule_levels(with_advisory, warnings, label="TypeScript presets")


def _render_rule_levels(source: str, warnings: frozenset[str], *, label: str) -> str:
    configured = {match.group("rule") for match in _RULE_LEVEL.finditer(source)}
    missing = sorted(warnings - configured)
    if missing:
        msg = f"{label} is missing warning-stage Oxlint rules: {', '.join(missing)}"
        raise ValueError(msg)

    def replace(match: re.Match[str]) -> str:
        level = "warn" if match.group("rule") in warnings else "error"
        return f'{match.group("prefix")}{match.group("array")}"{level}"'

    return _RULE_LEVEL.sub(replace, source)


def sync(repository: Path, *, check: bool) -> bool:
    warning_levels_are_managed = (repository / _RULE_CATALOG).is_file() and (repository / _TYPESCRIPT_PRESET).is_file()
    if warning_levels_are_managed and not sync_warning_levels(repository, check=check):
        return False
    expected = generated_configs(repository)
    if check:
        return all(
            path.is_file() and path.read_text(encoding="utf-8") == contents for path, contents in expected.items()
        )
    for path, contents in expected.items():
        path.write_text(contents, encoding="utf-8")
    return True
