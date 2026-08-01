"""Shared first-party / third-party module resolution.

Every "don't reach into privates" rule needs one thing no purely syntactic
checker has: whether the module that *declares* the private name is ours or
somebody else's. Reaching into our own module's underscore names is a design
problem we can fix by exporting a public surface. Reaching into a dependency's
underscore names is often the only option available — when a library moves an
API private in a minor release, the "just use the public API" advice names an
API that no longer exists, and the lint finding becomes an instruction to
perform an impossible edit.

Resolution is filesystem-based and deliberately conservative:

* a module is FIRST-PARTY when its top-level name is a package directory (one
  containing `__init__.py`) found inside the enclosing project;
* everything else — stdlib, site-packages, anything unresolvable — is treated
  as THIRD-PARTY, because the failure mode of guessing "third-party" is a
  missed finding, while the failure mode of guessing "first-party" is exactly
  the impossible-edit demand these rules exist to avoid.

The `__init__.py` requirement is load-bearing, not incidental: one first-party
repo carries a `python/app/livekit/` directory of SIP trunk JSON, and a
name-only match would have classified the `livekit` dependency as first-party
and re-flagged the very imports this distinction exists to exempt. Requiring an
importable package makes a top-level name collide only when a real first-party
package shadows the distribution — at which point flagging it is correct.

The project root is the nearest ancestor holding `.git`, falling back to the
topmost contiguous run of ancestors holding `pyproject.toml` (worktrees,
sdist checkouts, and vendored trees all resolve). Scanning stops at the first
package directory on each branch, so only *top-level* package names are
collected — `app.lk.custom_models` contributes `app`, never `lk`.

A second, finer boundary lives here too: the DISTRIBUTION, the nearest ancestor
holding a packaging manifest (`pyproject.toml` / `setup.py` / `setup.cfg`).
First-party-ness answers "may we edit this at all"; the distribution answers
"does this ship as one unit with us" — which is the boundary a package's own
test tree sits inside and its `__init__.py`-bearing package directory does not.
Rules that exempt "our own internals" need the distribution, because the
directory proxy for it (same top-level package name) silently excludes
`<dist>/tests/`, where the same import line is written by the same authors under
the same version number.
"""

from __future__ import annotations

from functools import lru_cache
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


# `.git` is a file, not a directory, inside a linked worktree — test existence,
# never `is_dir()`.
_GIT_MARKER = ".git"
_PROJECT_MARKER = "pyproject.toml"

# A distribution is what one packaging manifest builds and versions. `setup.py` /
# `setup.cfg` are here so pre-PEP-621 trees (django, celery) resolve too.
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


def is_first_party_module(module: str, path: Path) -> bool:
    """Report whether dotted `module` is declared inside `path`'s own project."""
    top = module.partition(".")[0]
    if not top or top in sys.stdlib_module_names:
        return False
    root = _project_root(path)
    if root is None:
        return False
    return top in _first_party_roots(root)


def own_top_package(path: Path) -> str | None:
    """Return the name of the top-level package `path` itself belongs to.

    The OUTERMOST importable ancestor wins rather than the outermost of an
    unbroken `__init__.py` run, because PEP 420 namespace subpackages are
    routine — a first-party repo's `app/app/lk/custom_models/` carries no
    `__init__.py` while `app/app/` does, and a break-on-first-gap walk would
    report the file as belonging to no package at all.

    """
    resolved = _resolved(path)
    if resolved is None:
        return None
    root = _project_root(resolved)
    top: str | None = None
    for ancestor in list(resolved.parents)[:_MAX_ANCESTORS]:
        if (ancestor / "__init__.py").exists():
            top = ancestor.name
        if ancestor == root:
            break
    if top is None and root is not None:
        roots = _first_party_roots(root)
        if len(roots) == 1:
            return next(iter(roots))
    return top


def same_distribution(module: str, path: Path) -> bool:
    """Report whether `module` ships in the same distribution as `path`.

    Both sides resolve to the nearest ancestor holding a packaging manifest:
    `path`'s own, and that of the directory declaring `module`'s top-level
    package. A distribution's test tree therefore counts as inside it, which the
    same-top-level-package proxy cannot express — `<dist>/tests/` is not inside
    `<dist>/<package>/`.

    A top-level name declared by more than one package directory counts as ours
    when ANY of them shares our manifest: the exempting direction is the safe one
    here, matching this module's under-flagging bias.

    Returns:
        True when both sides resolve to the same distribution root.

    """
    ours = distribution_root(path)
    if ours is None:
        return False
    root = _project_root(path)
    if root is None:
        return False
    top = module.partition(".")[0]
    return any(
        name == top and distribution_root(package_dir) == ours for name, package_dir in _first_party_packages(root)
    )


def distribution_root(path: Path) -> Path | None:
    """Locate the packaging manifest that owns `path`.

    The search stops at the project root, so a file outside any distribution
    (a repo-level script, a loose notebook) resolves to None rather than to some
    unrelated ancestor's manifest.

    Returns:
        The nearest ancestor directory holding a packaging manifest, or None.

    """
    resolved = _resolved(path)
    if resolved is None:
        return None
    root = _project_root(resolved)
    for ancestor in list(resolved.parents)[:_MAX_ANCESTORS]:
        if any((ancestor / marker).exists() for marker in _DISTRIBUTION_MARKERS):
            return ancestor
        if ancestor == root:
            break
    return None


def has_first_party_source(module: str, path: Path) -> bool:
    """Report whether dotted `module` resolves to editable source in `path`'s project.

    A first-party top-level package can still hold submodules that no `.py` in
    the tree declares — a compiled extension shipped beside a `.pyi` stub is the
    standard case (`pydantic_core._pydantic_core`, the Rust binary behind
    pydantic's wrapper). "Export it under a public name" is not an edit that
    exists for such a module, so a caller that needs to know whether a finding is
    actionable asks here.

    Returns:
        True when some first-party package directory holds the module as a
        `.py` file or a directory; False when nothing on disk declares it.

    """
    top, _, rest = module.partition(".")
    root = _project_root(path)
    if root is None:
        return False
    segments = rest.split(".") if rest else []
    return any(
        name == top and _declares_module(package_dir, segments) for name, package_dir in _first_party_packages(root)
    )


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


@lru_cache(maxsize=256)
def _project_root(path: Path) -> Path | None:
    """Locate the project boundary above `path`, memoized per file path."""
    resolved = _resolved(path)
    if resolved is None:
        return None
    ancestors = list(resolved.parents)[:_MAX_ANCESTORS]
    for ancestor in ancestors:
        if (ancestor / _GIT_MARKER).exists():
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
    return outermost


@lru_cache(maxsize=32)
def _first_party_roots(root: Path) -> frozenset[str]:
    """Collect the top-level package names declared anywhere under `root`.

    Returns:
        Every directory name under `root` that is an importable package.

    """
    return frozenset(name for name, _ in _first_party_packages(root))


@lru_cache(maxsize=32)
def _first_party_packages(root: Path) -> tuple[tuple[str, Path], ...]:
    """Locate every top-level package directory under `root`.

    A name can appear more than once — a src-layout package and its sdist copy,
    or two workspace members shipping the same namespace — so this is a sequence
    of pairs, not a mapping.

    Returns:
        `(package name, directory)` for every importable package found.

    """
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
