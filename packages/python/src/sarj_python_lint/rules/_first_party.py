# Ownership resolution is conservative because a missed finding is safer than advising an impossible dependency edit.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from pathlib import Path


# `.git` is a file, not a directory, inside a linked worktree — test existence,
# never `is_dir()`.
_GIT_MARKER = ".git"
_PROJECT_MARKER = "pyproject.toml"

# A distribution is what one packaging manifest builds and versions.
_DISTRIBUTION_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg")

# Never descend into these: a virtualenv or vendored tree holds *third-party*
# packages, and collecting their names would classify every dependency as ours.
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
    }
)

# Deep enough for a uv/pnpm-style monorepo (`<root>/packages/python/src/<pkg>`),
# shallow enough that the scan stays a few hundred `iterdir()` calls.
_MAX_SCAN_DEPTH = 5

# Hard stop so a pathological tree (a huge monorepo, a symlink loop) degrades to
# "nothing is first-party" — under-flagging — rather than hanging the linter.
_MAX_DIRS_SCANNED = 3000

# Walking up forever from a relative path is how a linter ends up scanning $HOME.
_MAX_ANCESTORS = 24


@final
class FirstPartyFacts:
    def __init__(self) -> None:
        self._project_roots: dict[Path, Path | None] = {}
        self._roots: dict[Path, frozenset[str]] = {}
        self._packages: dict[Path, tuple[tuple[str, Path], ...]] = {}

    def project_root(self, path: Path) -> Path | None:
        if path in self._project_roots:
            return self._project_roots[path]
        resolved = _resolved(path)
        if resolved is None:
            self._project_roots[path] = None
            return None
        ancestors = list(resolved.parents)[:_MAX_ANCESTORS]
        for ancestor in ancestors:
            if (ancestor / _GIT_MARKER).exists():
                self._project_roots[path] = ancestor
                return ancestor
        # No VCS boundary: take the OUTERMOST directory of the unbroken run of
        # pyproject.toml ancestors, which is the workspace root in a uv workspace.
        outermost: Path | None = None
        for ancestor in ancestors:
            if not (ancestor / _PROJECT_MARKER).exists():
                if outermost is not None:
                    break
                continue
            outermost = ancestor
        self._project_roots[path] = outermost
        return outermost

    def first_party_roots(self, root: Path) -> frozenset[str]:
        cached = self._roots.get(root)
        if cached is not None:
            return cached
        roots = frozenset(name for name, _ in self.first_party_packages(root))
        self._roots[root] = roots
        return roots

    def first_party_packages(self, root: Path) -> tuple[tuple[str, Path], ...]:
        cached = self._packages.get(root)
        if cached is not None:
            return cached
        packages = _scan_first_party_packages(root)
        self._packages[root] = packages
        return packages


def _fresh_facts(facts: FirstPartyFacts | None) -> FirstPartyFacts:
    # Compatibility helper calls are independent requests. The CLI supplies one
    # explicit instance so scans are still shared within a full analysis.
    return facts if facts is not None else FirstPartyFacts()


def is_first_party_module(module: str, path: Path, *, facts: FirstPartyFacts | None = None) -> bool:
    facts = _fresh_facts(facts)
    top = module.partition(".")[0]
    if not top or top in sys.stdlib_module_names:
        return False
    root = facts.project_root(path)
    if root is None:
        # Unresolved ownership biases to third-party to avoid unfixable findings.
        return False
    return top in facts.first_party_roots(root)


def own_top_package(path: Path, *, facts: FirstPartyFacts | None = None) -> str | None:
    facts = _fresh_facts(facts)
    resolved = _resolved(path)
    if resolved is None:
        return None
    root = facts.project_root(resolved)
    top: str | None = None
    for ancestor in list(resolved.parents)[:_MAX_ANCESTORS]:
        if (ancestor / "__init__.py").exists():
            top = ancestor.name
        if ancestor == root:
            break
    if top is None and root is not None:
        roots = facts.first_party_roots(root)
        if len(roots) == 1:
            return next(iter(roots))
    return top


def same_distribution(module: str, path: Path, *, facts: FirstPartyFacts | None = None) -> bool:
    facts = _fresh_facts(facts)
    ours = distribution_root(path, facts=facts)
    if ours is None:
        return False
    root = facts.project_root(path)
    if root is None:
        return False
    top = module.partition(".")[0]
    return any(
        name == top and distribution_root(package_dir, facts=facts) == ours
        for name, package_dir in facts.first_party_packages(root)
    )


def distribution_root(path: Path, *, facts: FirstPartyFacts | None = None) -> Path | None:
    facts = _fresh_facts(facts)
    resolved = _resolved(path)
    if resolved is None:
        return None
    root = facts.project_root(resolved)
    for ancestor in list(resolved.parents)[:_MAX_ANCESTORS]:
        if any((ancestor / marker).exists() for marker in _DISTRIBUTION_MARKERS):
            return ancestor
        if ancestor == root:
            break
    return None


def has_first_party_source(module: str, path: Path, *, facts: FirstPartyFacts | None = None) -> bool:
    facts = _fresh_facts(facts)
    top, _, rest = module.partition(".")
    root = facts.project_root(path)
    if root is None:
        return False
    segments = rest.split(".") if rest else []
    return any(
        name == top and _declares_module(package_dir, segments)
        for name, package_dir in facts.first_party_packages(root)
    )


def project_root(path: Path, *, facts: FirstPartyFacts | None = None) -> Path | None:
    return _fresh_facts(facts).project_root(path)


def _declares_module(package_dir: Path, segments: list[str]) -> bool:
    target = package_dir.joinpath(*segments)
    try:
        return target.is_dir() or (target.parent / f"{target.name}.py").exists()
    except OSError:
        return False


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _scan_first_party_packages(root: Path) -> tuple[tuple[str, Path], ...]:
    found: list[tuple[str, Path]] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    scanned = 0
    while queue:
        directory, depth = queue.pop()
        scanned += 1
        if scanned > _MAX_DIRS_SCANNED:
            break
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or entry.name in _SKIP_DIR_NAMES:
                continue
            try:
                if not entry.is_dir():
                    continue
                is_package = (entry / "__init__.py").exists()
            except OSError:
                continue
            if is_package:
                found.append((entry.name, entry))
            elif depth + 1 < _MAX_SCAN_DEPTH:
                queue.append((entry, depth + 1))
    return tuple(found)
