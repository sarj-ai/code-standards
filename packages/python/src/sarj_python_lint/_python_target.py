from __future__ import annotations

import csv
from importlib import metadata
from pathlib import Path
import tomllib
from typing import TypeGuard, final

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


_MAX_ANCESTORS = 24
_PROJECT_BOUNDARIES = ("pyproject.toml", "setup.py", "setup.cfg")
_INSTALLED_ROOTS = frozenset({"site-packages", "dist-packages"})
_PYTHON_MAJORS = frozenset({2, 3})


@final
class PythonTargetFacts:
    def __init__(self) -> None:
        self._declarations: dict[Path, str | None] = {}
        self._projects: dict[Path, str | None] = {}
        self._installed: dict[Path, dict[Path, str | None]] = {}
        self._witnesses: dict[tuple[str, tuple[int, int]], bool] = {}

    def has_declared_support_before(self, path: Path, minimum: tuple[int, int]) -> bool:
        try:
            absolute = path.absolute()
            resolved = path.resolve()
        except OSError, RuntimeError:
            return False
        if absolute not in self._declarations:
            try:
                self._declarations[absolute] = self._declaration(absolute, resolved)
            except OSError, RuntimeError:
                self._declarations[absolute] = None
        declaration = self._declarations[absolute]
        if not declaration:
            return False
        key = declaration, minimum
        if key not in self._witnesses:
            self._witnesses[key] = _has_legacy_witness(declaration, minimum)
        return self._witnesses[key]

    def _declaration(self, absolute: Path, resolved: Path) -> str | None:
        ancestors = [*list(absolute.parents)[:_MAX_ANCESTORS], *list(resolved.parents)[:_MAX_ANCESTORS]]
        for ancestor in ancestors:
            if ancestor.name in _INSTALLED_ROOTS:
                root = ancestor.resolve()
                if not resolved.is_relative_to(root):
                    return None
                if root not in self._installed:
                    self._installed[root] = _installed_declarations(root)
                return self._installed[root].get(resolved)
        for ancestor in list(resolved.parents)[:_MAX_ANCESTORS]:
            try:
                if any((ancestor / marker).exists() for marker in _PROJECT_BOUNDARIES):
                    if ancestor not in self._projects:
                        self._projects[ancestor] = _project_declaration(ancestor / "pyproject.toml")
                    return self._projects[ancestor]
                if (ancestor / ".git").exists():
                    return None
            except OSError:
                return None
        return None


def _project_declaration(path: Path) -> str | None:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, tomllib.TOMLDecodeError:
        return None
    project = document.get("project")
    if not _is_toml_table(project):
        return None
    dynamic = project.get("dynamic", [])
    if not _is_toml_array(dynamic) or any(not isinstance(field, str) for field in dynamic):
        return None
    if "requires-python" in dynamic:
        return None
    declaration = project.get("requires-python")
    return declaration if isinstance(declaration, str) else None


def _is_toml_table(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_toml_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _installed_declarations(root: Path) -> dict[Path, str | None]:
    try:
        return _collect_installed_declarations(root)
    except OSError, UnicodeError, ValueError, RuntimeError, TypeError, csv.Error:
        return {}


def _collect_installed_declarations(root: Path) -> dict[Path, str | None]:
    owners: dict[Path, str | None] = {}
    for distribution in metadata.distributions(path=[str(root)]):
        declarations = distribution.metadata.get_all("Requires-Python") or []
        declaration = declarations[0] if len(declarations) == 1 else None
        seen: set[Path] = set()
        for file in distribution.files or ():
            located = Path(str(distribution.locate_file(file))).resolve()
            if not located.is_relative_to(root) or located in seen:
                continue
            seen.add(located)
            owners[located] = None if located in owners else declaration
    return owners


def _has_legacy_witness(declaration: str, minimum: tuple[int, int]) -> bool:
    try:
        specifiers = SpecifierSet(declaration)
    except InvalidSpecifier:
        return False
    if not specifiers or any(specifier.operator == "===" for specifier in specifiers):
        return False
    threshold = Version(".".join(map(str, minimum)))
    candidates = {Version(f"3.{minor}.{patch}") for minor in range(minimum[1]) for patch in (0, 1)}
    candidates.add(Version("2.7"))
    for specifier in specifiers:
        try:
            boundary = Version(specifier.version.removesuffix(".*"))
        except InvalidVersion:
            continue
        if boundary.epoch:
            continue
        release = (*boundary.release, 0, 0)[:3]
        candidates.add(Version(".".join(map(str, release))))
        candidates.add(Version(f"{release[0]}.{release[1]}.{release[2] + 1}"))
    return any(
        candidate.major in _PYTHON_MAJORS
        and candidate < threshold
        and specifiers.contains(candidate, prereleases=False)
        for candidate in candidates
    )
