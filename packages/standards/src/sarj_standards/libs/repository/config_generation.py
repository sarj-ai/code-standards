"""Generate the standalone application-profile configs from canonical inputs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.linting import library_policy


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


_RUFF_APPLICATION: Final = CONFIGS_DIR / "ruff.application.toml"
_ESLINT_APPLICATION: Final = CONFIGS_DIR / "eslint.application.mjs"
_RUFF_MARKER: Final = "[lint.per-file-ignores]"
_ESLINT_MARKER: Final = "          paths: [\n"
_ESLINT_PATTERNS_MARKER: Final = '          patterns: ["*/index", "*/index.ts"],\n'
_ESLINT_CONFIG_END: Final = "\n  ];\n}\n\nconst config = createConfig();\nexport default config;\n"


def render_ruff_application() -> str:
    """Return a complete Ruff config with application-only import policy merged in."""
    standard = (CONFIGS_DIR / "ruff.strict.toml").read_text(encoding="utf-8")
    entries = "".join(
        f"{json.dumps(name)}.msg = {json.dumps(message)}\n" for name, message in sorted(_python_bans().items())
    )
    addition = f"# Generated application-profile library policy. Edit the catalog, not this file.\n{entries}\n"
    if _RUFF_MARKER not in standard:
        msg = f"ruff.strict.toml is missing generation marker {_RUFF_MARKER!r}"
        raise ValueError(msg)
    return standard.replace(_RUFF_MARKER, addition + _RUFF_MARKER, 1)


def _python_bans() -> Mapping[str, str]:
    """Read the catalog's Ruff adapter."""
    return library_policy.python_banned_api()


def render_eslint_application() -> str:
    """Return a complete ESLint config with application-only import policy merged in."""
    standard = (CONFIGS_DIR / "eslint.strict.mjs").read_text(encoding="utf-8")
    bans = _typescript_bans()
    entries = "".join(f"            {json.dumps(dict(entry), sort_keys=True)},\n" for entry in bans)
    addition = (
        f"            // Generated application-profile library policy. Edit the catalog, not this file.\n{entries}"
    )
    if _ESLINT_MARKER not in standard:
        msg = "eslint.strict.mjs is missing the no-restricted-imports generation marker"
        raise ValueError(msg)
    with_paths = standard.replace(_ESLINT_MARKER, _ESLINT_MARKER + addition, 1)
    patterns = [
        {
            "group": [f"{name}/*"],
            "message": entry.get("message", "Use the application profile's preferred library."),
        }
        for entry in bans
        if isinstance(name := entry.get("name"), str)
    ]
    pattern_lines = "".join(f"            {json.dumps(pattern, sort_keys=True)},\n" for pattern in patterns)
    pattern_block = (
        f'          patterns: [\n            {{"group": ["*/index", "*/index.ts"]}},\n{pattern_lines}          ],\n'
    )
    if _ESLINT_PATTERNS_MARKER not in with_paths:
        msg = "eslint.strict.mjs is missing the no-restricted-imports patterns generation marker"
        raise ValueError(msg)
    with_static_policy = with_paths.replace(_ESLINT_PATTERNS_MARKER, pattern_block, 1)
    runtime_policy = json.dumps(_typescript_runtime_bans(), indent=2, sort_keys=True)
    indented_runtime_policy = runtime_policy.replace("\n", "\n          ")
    application_block = (
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
    )
    if _ESLINT_CONFIG_END not in with_static_policy:
        msg = "eslint.strict.mjs is missing its application-rule generation marker"
        raise ValueError(msg)
    return with_static_policy.replace(
        _ESLINT_CONFIG_END,
        application_block + _ESLINT_CONFIG_END,
        1,
    )


def _typescript_bans() -> Sequence[Mapping[str, object]]:
    """Read the catalog's ESLint adapter."""
    return tuple(
        {"name": entry.name, "message": entry.message} for entry in library_policy.typescript_restricted_imports()
    )


def _typescript_runtime_bans() -> list[dict[str, str]]:
    """Translate TypeScript catalog entries to the custom runtime-loader rule schema."""
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
    """Return every generated application artifact and its expected content."""
    return {
        _RUFF_APPLICATION: render_ruff_application(),
        _ESLINT_APPLICATION: render_eslint_application(),
    }


def sync(*, check: bool) -> bool:
    """Write generated artifacts, or report whether committed copies are current."""
    expected = generated_configs()
    if check:
        return all(
            path.is_file() and path.read_text(encoding="utf-8") == contents for path, contents in expected.items()
        )
    for path, contents in expected.items():
        _ = path.write_text(contents, encoding="utf-8")
    return True
