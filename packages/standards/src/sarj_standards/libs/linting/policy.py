"""One denylist policy shared by every Standards analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self

from pathspec import PathSpec
from pathspec.pattern import Pattern

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, ExclusionOverride, Manifest
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sarj_standards.libs.diagnostics import Diagnostic


_SOURCE_ENGINES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "sarj-python-lint": "python",
        "sarj-sql-lint": "sql",
        "sarj-iac-lint": "iac",
        "sarj-text-lint": "text",
        "sarj-library-policy": "python",
        "ruff": "ruff",
        "basedpyright": "basedpyright",
        "eslint": "eslint",
    }
)
_NON_EXCLUDABLE_CODE: Final = "SARJ206"
_TERRAFORM_TEST_SUFFIXES: Final = (".tftest.hcl", ".tftest.json")


@dataclass(frozen=True, slots=True)
class _Override:
    paths: PathSpec[Pattern]
    rules: frozenset[str]


@dataclass(frozen=True, slots=True)
class Policy:
    """Compiled repository policy; all rules are enabled unless denied."""

    root: Path
    excluded_paths: PathSpec[Pattern]
    excluded_rules: frozenset[str]
    overrides: tuple[_Override, ...]

    @classmethod
    def from_manifest(cls, root: Path, manifest: Manifest | None) -> Self:
        resolved = root.resolve()
        if manifest is None:
            return cls(resolved, PathSpec.from_lines("gitignore", ()), frozenset(), ())
        return cls(
            resolved,
            PathSpec.from_lines("gitignore", manifest.excluded_paths),
            frozenset(manifest.excluded_rules),
            tuple(_compile_override(item) for item in manifest.exclusion_overrides),
        )

    @classmethod
    def corpus_from_manifest(cls, root: Path, manifest: Manifest | None) -> Self:
        """Apply reviewed path scope while deliberately exposing every rule diagnostic."""
        policy = cls.from_manifest(root, manifest)
        return cls(policy.root, policy.excluded_paths, frozenset(), ())

    @classmethod
    def observe_from_manifest(cls, root: Path, manifest: Manifest | None) -> Self:
        """Expose lifecycle warnings while preserving consumer-owned exclusions."""
        resolved = root.resolve()
        if manifest is None:
            return cls(resolved, PathSpec.from_lines("gitignore", ()), frozenset(), ())
        return cls(
            resolved,
            PathSpec.from_lines("gitignore", manifest.excluded_paths),
            frozenset(manifest.excluded_rules),
            tuple(_compile_override(item) for item in manifest.exclusion_overrides),
        )

    def allows_path(self, path: str | Path) -> bool:
        relative = self.relative(path)
        if relative == MANIFEST_NAME:
            return True
        if relative.casefold().endswith(_TERRAFORM_TEST_SUFFIXES):
            return True
        return not self.excluded_paths.match_file(relative)

    def allows_rule(self, diagnostic: Diagnostic) -> bool:
        if diagnostic.code == _NON_EXCLUDABLE_CODE:
            return True
        engine = _SOURCE_ENGINES.get(diagnostic.source, diagnostic.source)
        selectors = frozenset(
            {
                f"{engine}:{diagnostic.code}",
                f"{engine}:{diagnostic.rule_id}",
            }
            if diagnostic.rule_id is not None
            else {f"{engine}:{diagnostic.code}"}
        )
        if selectors & self.excluded_rules:
            return False
        relative = diagnostic.location.path
        return not any(
            override.paths.match_file(relative) and selectors & override.rules for override in self.overrides
        )

    def filter_paths(self, paths: Iterable[str]) -> tuple[str, ...]:
        return tuple(path for path in paths if self.allows_path(path))

    def filter_diagnostics(self, diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
        return tuple(item for item in diagnostics if self.allows_path(item.location.path) and self.allows_rule(item))

    def relative(self, path: str | Path) -> str:
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError as exc:
            msg = f"policy path is outside repository root: {path}"
            raise ValueError(msg) from exc


def _compile_override(value: ExclusionOverride) -> _Override:
    return _Override(PathSpec.from_lines("gitignore", value.paths), frozenset(value.rules))


@lru_cache(maxsize=1)
def warning_selectors() -> frozenset[RuleSelector]:
    payload: object = json.loads(  # pyright: ignore[reportAny]
        (CONFIGS_DIR / "rule-warning-levels.v1.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        msg = "invalid bundled warning-rule lifecycle"
        raise TypeError(msg)
    document: dict[str, object] = payload  # pyright: ignore[reportUnknownVariableType]
    if document.get("schemaVersion") != 1:
        msg = "invalid bundled warning-rule lifecycle"
        raise ValueError(msg)
    rules_value = document.get("rules")
    if not isinstance(rules_value, list):
        msg = "invalid bundled warning-rule selectors"
        raise TypeError(msg)
    rules: list[object] = rules_value  # pyright: ignore[reportUnknownVariableType]
    if any(not isinstance(value, str) for value in rules):
        msg = "invalid bundled warning-rule selectors"
        raise TypeError(msg)
    return frozenset(RuleSelector.parse(value) for value in rules if isinstance(value, str))


__all__ = ["Policy"]
