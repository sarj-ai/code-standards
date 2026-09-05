from __future__ import annotations

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.linting import library_policy
from sarj_standards.libs.rules import RuleEngine, warning_levels


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


_RUFF_APPLICATION: Final = CONFIGS_DIR / "ruff.application.toml"
_ESLINT_APPLICATION: Final = CONFIGS_DIR / "eslint.application.mjs"
_RUFF_ALIAS: Final = '# Compatibility alias; all repositories use the same policy.\nextend = "ruff.strict.toml"\n'
_ESLINT_ALIAS: Final = '// Compatibility alias; all repositories use the same policy.\nexport { createConfig, default } from "./eslint.strict.mjs";\n'
_RUFF_MARKER: Final = "[lint.per-file-ignores]"
_ESLINT_MARKER: Final = "          paths: [\n"
_ESLINT_PATTERNS_MARKER: Final = '          patterns: ["*/index", "*/index.ts"],\n'
_ESLINT_CONFIG_END: Final = "\n  ];\n}\n\nconst config = createConfig();\nexport default config;\n"
_WARNING_LEVELS: Final = Path("packages/standards/src/sarj_standards/configs/rule-warning-levels.v1.json")
_ESLINT_STRICT: Final = Path("packages/standards/src/sarj_standards/configs/eslint.strict.mjs")
_ESLINT_APPLICATION_REPO: Final = Path("packages/standards/src/sarj_standards/configs/eslint.application.mjs")
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


def render_eslint_strict(standard: str | None = None) -> str:
    if standard is None:
        standard = (CONFIGS_DIR / "eslint.strict.mjs").read_text(encoding="utf-8")
    standard = _without_generated_policy(standard)
    bans = _typescript_bans()
    entries = "".join(f"            {json.dumps(dict(entry), sort_keys=True)},\n" for entry in bans)
    addition = f"            // BEGIN GENERATED LIBRARY POLICY\n{entries}            // END GENERATED LIBRARY POLICY\n"
    if _ESLINT_MARKER not in standard:
        msg = "eslint.strict.mjs is missing the no-restricted-imports generation marker"
        raise ValueError(msg)
    with_paths = standard.replace(_ESLINT_MARKER, _ESLINT_MARKER + addition, 1)
    patterns = [
        {
            "group": [f"{name}/*"],
            "message": entry.get("message", "Use the preferred library."),
        }
        for entry in bans
        if isinstance(name := entry.get("name"), str)
    ]
    pattern_lines = "".join(f"            {json.dumps(pattern, sort_keys=True)},\n" for pattern in patterns)
    pattern_block = (
        f'          patterns: [{{"group": ["*/index", "*/index.ts"]}},\n'
        f"            // BEGIN GENERATED LIBRARY POLICY\n{pattern_lines}            // END GENERATED LIBRARY POLICY\n"
        "          ],\n"
    )
    if _ESLINT_PATTERNS_MARKER not in with_paths:
        msg = "eslint.strict.mjs is missing the no-restricted-imports patterns generation marker"
        raise ValueError(msg)
    with_static_policy = with_paths.replace(_ESLINT_PATTERNS_MARKER, pattern_block, 1)
    runtime_policy = json.dumps(_typescript_runtime_bans(), indent=2, sort_keys=True)
    indented_runtime_policy = runtime_policy.replace("\n", "\n          ")
    application_block = (
        "  // BEGIN GENERATED LIBRARY POLICY\n"
        "\n  {\n"
        '    files: ["**/*.{ts,tsx,js,jsx,mjs,cjs,mts,cts}"],\n'
        "    rules: {\n"
        '      "@sarj/no-restricted-library-load": [\n'
        '        "error",\n'
        f"        {{ libraries: {indented_runtime_policy} }},\n"
        "      ],\n"
        '      "@sarj/prefer-native-random-uuid": "error",\n'
        '      "@sarj/prefer-shadcn-primitives": "error",\n'
        "    },\n"
        "  },\n"
        "\n  {\n"
        "    files: [\n"
        '      "**/*.{test,spec,e2e}.{js,jsx,ts,tsx}",\n'
        '      "**/test/**",\n'
        '      "**/tests/**",\n'
        '      "**/__tests__/**",\n'
        '      "**/fixtures/**",\n'
        '      "**/e2e/**",\n'
        '      "**/e2e-apps/**",\n'
        '      "**/perf-regression/**",\n'
        '      "**/components/ui/**",\n'
        '      "**/components/design-system/**",\n'
        "    ],\n"
        "    rules: {\n"
        '      "@sarj/prefer-shadcn-primitives": "off",\n'
        "    },\n"
        "  },\n"
        "  // END GENERATED LIBRARY POLICY\n"
    )
    if _ESLINT_CONFIG_END not in with_static_policy:
        msg = "eslint.strict.mjs is missing its library-rule generation marker"
        raise ValueError(msg)
    return with_static_policy.replace(
        _ESLINT_CONFIG_END,
        application_block + _ESLINT_CONFIG_END,
        1,
    )


def _without_generated_policy(source: str) -> str:
    source = re.sub(
        r"(?m)^[ \t]*(?:#|//) BEGIN GENERATED LIBRARY POLICY\n.*?^[ \t]*(?:#|//) END GENERATED LIBRARY POLICY\n",
        "",
        source,
        flags=re.DOTALL,
    )
    source = source.replace("\n\n[lint.per-file-ignores]", "\n[lint.per-file-ignores]")
    for prefix in ('"*/index", "*/index.ts"', '{"group": ["*/index", "*/index.ts"]}'):
        source = source.replace(f"          patterns: [{prefix},\n          ],\n", _ESLINT_PATTERNS_MARKER)
    return source


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


def generated_configs() -> Mapping[Path, str]:
    ruff = render_ruff_strict()
    configs = {
        CONFIGS_DIR / "ruff.strict.toml": ruff,
        CONFIGS_DIR / "eslint.strict.mjs": render_eslint_strict(),
        _RUFF_APPLICATION: _RUFF_ALIAS,
        _ESLINT_APPLICATION: _ESLINT_ALIAS,
    }
    repository = CONFIGS_DIR.parents[4]
    if (repository / _TYPESCRIPT_PRESET).is_file():
        configs[repository / ".ruff-strict.toml"] = ruff
        configs[repository / "packages/typescript/src/library-policy.ts"] = (
            "// Generated from the Standards library catalog.\n"
            f"export const LIBRARY_POLICY = {json.dumps(_typescript_runtime_bans(), indent=2, sort_keys=True)} as const;\n"
        )
    return configs


def warning_level_artifacts(repository: Path) -> Mapping[Path, str]:
    warning_path = repository / _WARNING_LEVELS
    warnings = frozenset(
        str(selector.rule_id) for selector in warning_levels.load(warning_path) if selector.engine is RuleEngine.ESLINT
    )

    preset_path = repository / _TYPESCRIPT_PRESET
    strict_path = repository / _ESLINT_STRICT
    preset = preset_path.read_text(encoding="utf-8")
    strict = strict_path.read_text(encoding="utf-8")
    rendered_preset = _render_typescript_preset(preset, warnings)
    rendered_strict = _render_rule_levels(strict, warnings, label="eslint.strict.mjs")
    return {
        preset_path: rendered_preset,
        strict_path: rendered_strict,
        repository / _ESLINT_APPLICATION_REPO: _ESLINT_ALIAS,
    }


def sync_warning_levels(repository: Path, *, check: bool) -> bool:
    expected = warning_level_artifacts(repository)
    if check:
        return all(path.is_file() and path.read_text(encoding="utf-8") == text for path, text in expected.items())
    for path, text in expected.items():
        _ = path.write_text(text, encoding="utf-8")
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
        msg = f"{label} is missing warning-stage ESLint rules: {', '.join(missing)}"
        raise ValueError(msg)

    def replace(match: re.Match[str]) -> str:
        level = "warn" if match.group("rule") in warnings else "error"
        return f'{match.group("prefix")}{match.group("array")}"{level}"'

    return _RULE_LEVEL.sub(replace, source)


def sync(*, check: bool) -> bool:
    repository = CONFIGS_DIR.parents[4]
    warning_levels_are_managed = (repository / _WARNING_LEVELS).is_file() and (
        repository / _TYPESCRIPT_PRESET
    ).is_file()
    if warning_levels_are_managed and not sync_warning_levels(repository, check=check):
        return False
    expected = generated_configs()
    if check:
        return all(
            path.is_file() and path.read_text(encoding="utf-8") == contents for path, contents in expected.items()
        )
    for path, contents in expected.items():
        _ = path.write_text(contents, encoding="utf-8")
    return True
