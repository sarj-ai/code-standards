from __future__ import annotations

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards._meta import CONFIGS_DIR, OXLINT_STRICT
from sarj_standards.libs.linting import library_policy
from sarj_standards.libs.repository import rule_catalog_artifact
from sarj_standards.libs.rules import RuleEngine


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


_RUFF_APPLICATION: Final = CONFIGS_DIR / "ruff.application.toml"
_RUFF_ALIAS: Final = '# Compatibility alias; all repositories use the same policy.\nextend = "ruff.strict.toml"\n'
_RUFF_MARKER: Final = "[lint.per-file-ignores]"
_OXLINT_POLICY: Final = re.compile(
    r"(?ms)^// BEGIN GENERATED LIBRARY POLICY\n.*?^// END GENERATED LIBRARY POLICY\n",
)
_RULE_CATALOG: Final = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
_OXLINT_STRICT: Final = Path("packages/standards/src/sarj_standards/configs/oxlint.strict.mts")
_TYPESCRIPT_PRESET: Final = Path("packages/typescript/src/index.ts")
_RULE_LEVEL = re.compile(r'(?m)^(?P<prefix>\s+"@sarj/(?P<rule>[a-z0-9-]+)":\s*)(?P<array>(?:\[\s*)?)"(?:warn|error)"')


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


def render_oxlint_strict(standard: str | None = None) -> str:
    if standard is None:
        standard = OXLINT_STRICT.read_text(encoding="utf-8")
    if len(_OXLINT_POLICY.findall(standard)) != 1:
        msg = "oxlint.strict.mts needs exactly one GENERATED LIBRARY POLICY block"
        raise ValueError(msg)
    bans = _typescript_bans()
    patterns = [
        {"group": [f"{name}/*"], "message": entry.get("message", "Use the preferred library.")}
        for entry in bans
        if isinstance(name := entry.get("name"), str)
    ]
    block = (
        "// BEGIN GENERATED LIBRARY POLICY\n"
        f"{_constant('LIBRARY_IMPORT_PATHS', bans)}"
        f"{_constant('LIBRARY_IMPORT_PATTERNS', patterns)}"
        f"{_constant('LIBRARY_LOADS', _typescript_runtime_bans())}"
        "// END GENERATED LIBRARY POLICY\n"
    )
    return _OXLINT_POLICY.sub(lambda _: block, standard, count=1)


def _constant(name: str, entries: Sequence[Mapping[str, str | Sequence[str]]]) -> str:
    lines = "".join(f"  {json.dumps(dict(entry), sort_keys=True)},\n" for entry in entries)
    return f"const {name} = [\n{lines}];\n"


def _without_generated_policy(source: str) -> str:
    source = re.sub(
        r"(?m)^[ \t]*# BEGIN GENERATED LIBRARY POLICY\n.*?^[ \t]*# END GENERATED LIBRARY POLICY\n",
        "",
        source,
        flags=re.DOTALL,
    )
    return source.replace("\n\n[lint.per-file-ignores]", "\n[lint.per-file-ignores]")


def _typescript_bans() -> Sequence[Mapping[str, str]]:
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
        OXLINT_STRICT: render_oxlint_strict(),
        _RUFF_APPLICATION: _RUFF_ALIAS,
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
    warnings = frozenset(
        str(selector.rule_id)
        for selector in rule_catalog_artifact.warning_selectors(repository / _RULE_CATALOG)
        if selector.engine is RuleEngine.OXLINT
    )

    strict_path = repository / _OXLINT_STRICT
    strict = strict_path.read_text(encoding="utf-8")
    return {strict_path: _render_rule_levels(strict, warnings)}


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


def _render_rule_levels(source: str, warnings: frozenset[str]) -> str:
    configured = {match.group("rule") for match in _RULE_LEVEL.finditer(source)}
    missing = sorted(warnings - configured)
    if missing:
        msg = f"oxlint.strict.mts is missing warning-stage Oxlint rules: {', '.join(missing)}"
        raise ValueError(msg)

    def replace(match: re.Match[str]) -> str:
        level = "warn" if match.group("rule") in warnings else "error"
        return f'{match.group("prefix")}{match.group("array")}"{level}"'

    return _RULE_LEVEL.sub(replace, source)


def sync(*, check: bool) -> bool:
    repository = CONFIGS_DIR.parents[4]
    warning_levels_are_managed = (repository / _RULE_CATALOG).is_file() and (repository / _OXLINT_STRICT).is_file()
    if warning_levels_are_managed and not sync_warning_levels(repository, check=check):
        return False
    expected = generated_configs()
    if check:
        return all(
            path.is_file() and path.read_text(encoding="utf-8") == contents for path, contents in expected.items()
        )
    for path, contents in expected.items():
        path.write_text(contents, encoding="utf-8")
    return True
