from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


type ConfigDestination = Literal["root", "python", "typescript", "swift", "kotlin"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigSpec:
    source_name: str
    destination_name: str
    destination_kind: ConfigDestination


CONFIG_SPECS: Final[Mapping[str, ConfigSpec]] = MappingProxyType(
    {
        "ruff": ConfigSpec(
            source_name="ruff.strict.toml",
            destination_name=".ruff-strict.toml",
            destination_kind="python",
        ),
        "pyright": ConfigSpec(
            source_name="pyright.strict.json",
            destination_name=".pyright-strict.json",
            destination_kind="python",
        ),
        "eslint": ConfigSpec(
            source_name="eslint.strict.ts",
            destination_name="eslint.strict.ts",
            destination_kind="typescript",
        ),
        "swiftformat": ConfigSpec(
            source_name="swiftformat.strict",
            destination_name=".swiftformat",
            destination_kind="swift",
        ),
        "swiftlint": ConfigSpec(
            source_name="swiftlint.strict.yml",
            destination_name=".swiftlint.yml",
            destination_kind="swift",
        ),
        "ktlint": ConfigSpec(
            source_name="ktlint.strict.editorconfig",
            destination_name=".editorconfig",
            destination_kind="kotlin",
        ),
        "detekt": ConfigSpec(
            source_name="detekt.strict.yml",
            destination_name="config/detekt/detekt.yml",
            destination_kind="kotlin",
        ),
        "mobile-security": ConfigSpec(
            source_name="mobsf.strict.yml",
            destination_name=".mobsf",
            destination_kind="root",
        ),
        "markdownlint": ConfigSpec(
            source_name="markdownlint.strict.yaml",
            destination_name=".markdownlint.yaml",
            destination_kind="root",
        ),
        "taplo": ConfigSpec(
            source_name="taplo.strict.toml",
            destination_name=".taplo.toml",
            destination_kind="root",
        ),
        "yamllint": ConfigSpec(
            source_name="yamllint.strict.yaml",
            destination_name=".yamllint.yaml",
            destination_kind="root",
        ),
        "shellcheck": ConfigSpec(
            source_name="shellcheck.strict.rc",
            destination_name=".shellcheckrc",
            destination_kind="root",
        ),
        "zizmor": ConfigSpec(
            source_name="zizmor.strict.yml",
            destination_name="zizmor.yml",
            destination_kind="root",
        ),
        "checkov": ConfigSpec(
            source_name="checkov.strict.yml",
            destination_name=".checkov.yml",
            destination_kind="root",
        ),
    }
)

CONFIG_NAMES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {name: (spec.source_name, spec.destination_name) for name, spec in CONFIG_SPECS.items()}
)

# ESLint consumers also receive React Doctor's data-only companion config.
TYPESCRIPT_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "react-doctor": ("doctor.config.json", "doctor.config.json"),
    }
)
PYTHON_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        # BasedPyright's source and synchronized forms use the same relative
        # parent name, keeping both inheritance graphs independently valid.
        "pyright-base": ("pyright.strict.json", "pyright.strict.json"),
        # Keep the upstream-Pyright policy warning-free while shipping the
        # stricter active BasedPyright layer beside it.
        "basedpyright": ("basedpyright.strict.json", ".basedpyright-strict.json"),
    }
)
MOBILE_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "mobile-mintfile": ("Mintfile.mobile.strict", "Mintfile.mobile.strict"),
        "mobile-tool-versions": ("mobile-tools.versions.json", "mobile-tools.versions.json"),
    }
)
APPLICATION_CONFIG_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ruff": "ruff.strict.toml",
        "eslint": "eslint.strict.mjs",
    }
)
PYTHON_CONFIGS: Final = frozenset({"ruff", "pyright"})
SWIFT_CONFIGS: Final = frozenset({"swiftformat", "swiftlint"})
KOTLIN_CONFIGS: Final = frozenset({"detekt", "ktlint"})
MOBILE_CONFIGS: Final = frozenset({"mobile-security"})


#: Directories a detection walk must not descend into: an installed dependency
#: carries thousands of `package.json` files and a vendored tree carries the
#: pyproject of something this repo did not write.
CONFIG_SKIP_DIRECTORIES: Final = frozenset(
    {
        ".git",
        ".gradle",
        ".agents",
        ".build",
        ".cache",
        ".claude",
        ".next",
        ".open-next",
        ".turbo",
        ".uv-cache",
        ".wrangler",
        ".yarn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "coverage",
        ".tox",
        ".venv",
        "Carthage",
        "DerivedData",
        "DerivedDataAPI",
        "DerivedDataDist",
        "Pods",
        "SourcePackages",
        "dist",
        "fastlane",
        "generated",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)

ESLINT_CONFIG_NAMES: Final = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
)
ESLINT_PRESET_NAMES: Final = frozenset({"eslint.strict.ts", "eslint.strict.mjs"})
_LOCAL_MODULE = re.compile(
    r"(?m)^\s*(?:import\b[^;\n]*?\bfrom\s+|import\s*|export\b[^;\n]*?\bfrom\s+)"
    r"[\"'](?P<path>\.[^\"']+)[\"']"
)


def eslint_preset_name(destination: Path) -> str:
    typed = "eslint.strict.ts"
    legacy = "eslint.strict.mjs"
    for preset in (typed, legacy):
        if any(
            eslint_wiring_reaches_strict(destination / name, destination, planned_strict=destination / preset)
            for name in ESLINT_CONFIG_NAMES
        ):
            return preset
    if (destination / typed).exists():
        return typed
    if (destination / legacy).exists():
        return legacy
    entrypoints = tuple(
        owner / name
        for owner in configuration_roots(destination, ESLINT_CONFIG_NAMES)
        for name in ESLINT_CONFIG_NAMES
        if (owner / name).is_file()
    )
    for preset in (typed, legacy):
        if any(
            eslint_wiring_reaches_strict(path, destination, planned_strict=destination / preset) for path in entrypoints
        ):
            return preset
    return typed


def eslint_wiring_reaches_strict(
    path: Path,
    root: Path,
    seen: set[Path] | None = None,
    *,
    planned_strict: Path | None = None,
) -> bool:
    visited: set[Path] = set() if seen is None else seen
    resolved = path.resolve()
    if resolved in visited or not resolved.is_file() or not resolved.is_relative_to(root.resolve()):
        return False
    visited.add(resolved)
    for match in _LOCAL_MODULE.finditer(resolved.read_text(encoding="utf-8", errors="replace")):
        target = (resolved.parent / match.group("path")).resolve()
        if target.name in ESLINT_PRESET_NAMES and (
            target.is_file() if planned_strict is None else target == planned_strict.resolve()
        ):
            return True
        candidates = (
            target,
            *(target.with_suffix(suffix) for suffix in (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")),
        )
        if any(
            eslint_wiring_reaches_strict(candidate, root, visited, planned_strict=planned_strict)
            for candidate in candidates
        ):
            return True
    return False


def configuration_roots(root: Path, names: Sequence[str]) -> list[Path]:
    wanted = frozenset(names)
    found: list[Path] = []
    for parent, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in CONFIG_SKIP_DIRECTORIES)
        if not wanted.isdisjoint(filenames):
            found.append(Path(parent))
    return found
