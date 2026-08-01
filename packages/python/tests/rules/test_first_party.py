"""Direct tests for the first-party/third-party resolver shared by the import rules.

Every threshold in `_first_party` is pinned from BOTH sides -- one case that
breaks if the number is raised and one that breaks if it is lowered. A guard
constant nothing measures is a guard that can be deleted or doubled in a
refactor with the whole suite still green, and each of these three bounds is the
difference between "the linter under-flags" and "the linter walks $HOME".
"""

from typing import TYPE_CHECKING

from sarj_python_lint.rules._first_party import (
    distribution_root,
    has_first_party_source,
    is_first_party_module,
    own_top_package,
    same_distribution,
)


if TYPE_CHECKING:
    from pathlib import Path


def _repo(root: Path) -> Path:
    """Make `root` a project boundary the resolver will stop at.

    Returns:
        The same directory, now carrying a `.git` marker.

    """
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root


def _package(parent: Path, name: str) -> Path:
    """Create an importable package directory.

    Returns:
        The package directory.

    """
    package = parent / name
    package.mkdir(parents=True, exist_ok=True)
    _ = (package / "__init__.py").write_text("")
    return package


def _chain(root: Path, depth: int) -> Path:
    """Create `depth` nested plain directories under `root`.

    Returns:
        The innermost directory.

    """
    current = root
    for level in range(depth):
        current /= f"d{level:02d}"
    current.mkdir(parents=True)
    return current


# --- the resolution the import rules actually ask for -----------------------


def test_a_package_directory_makes_its_top_level_name_first_party(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _ = _package(root, "app")
    assert is_first_party_module("app.stores.widgets", root / "svc.py")


def test_a_directory_without_an_init_is_not_a_package(tmp_path: Path) -> None:
    """The `__init__.py` requirement is load-bearing, not incidental.

    A first-party repo carries a `python/app/livekit/` directory of SIP trunk
    JSON; a name-only match classifies the `livekit` dependency as first-party
    and re-flags the very imports this distinction exists to exempt.
    """
    root = _repo(tmp_path)
    (root / "livekit").mkdir()
    assert not is_first_party_module("livekit", root / "svc.py")


def test_a_file_outside_any_project_resolves_to_nothing(tmp_path: Path) -> None:
    # No `.git` and no `pyproject.toml` anywhere above: there is no project to
    # be first-party to, and guessing "ours" is the failure mode this module
    # is biased against.
    (tmp_path / "loose").mkdir()
    assert not is_first_party_module("app", tmp_path / "loose" / "svc.py")


# --- the stdlib guard -------------------------------------------------------


def test_a_stdlib_top_level_name_is_never_first_party(tmp_path: Path) -> None:
    """A first-party package may shadow a stdlib name; the stdlib still wins here.

    Without the `sys.stdlib_module_names` check, a repo holding its own
    `json/`, `types/` or `logging/` package turns every `from json import ...`
    in the tree into a first-party import, and the private-import rules start
    demanding edits to CPython.
    """
    root = _repo(tmp_path)
    _ = _package(root, "json")
    assert not is_first_party_module("json", root / "svc.py")
    assert not is_first_party_module("json.decoder", root / "svc.py")


def test_a_name_that_merely_looks_stdlib_ish_is_still_ours(tmp_path: Path) -> None:
    # The control for the guard above: it must key on the real stdlib listing,
    # not on a hand-maintained set that would drift.
    root = _repo(tmp_path)
    _ = _package(root, "jsonschema_local")
    assert is_first_party_module("jsonschema_local", root / "svc.py")


# --- _MAX_SCAN_DEPTH, from both sides ---------------------------------------


def test_a_package_at_the_deepest_scanned_level_is_found(tmp_path: Path) -> None:
    """Breaks if `_MAX_SCAN_DEPTH` is lowered.

    `<root>/packages/python/src/<pkg>` is the shape of this very repo, and a
    uv/pnpm monorepo routinely adds one more segment.
    """
    root = _repo(tmp_path)
    _ = _package(_chain(root, 4), "pkg")
    assert is_first_party_module("pkg", root / "svc.py")


def test_a_package_one_level_past_the_scan_depth_is_not_found(tmp_path: Path) -> None:
    # Breaks if `_MAX_SCAN_DEPTH` is raised: the bound is what keeps the scan a
    # few hundred `iterdir()` calls instead of a whole-monorepo walk.
    root = _repo(tmp_path)
    _ = _package(_chain(root, 5), "pkg")
    assert not is_first_party_module("pkg", root / "svc.py")


# --- _MAX_DIRS_SCANNED, from both sides -------------------------------------


def _budget_probe(root: Path, siblings: int) -> bool:
    """Lay out a tree whose package is reachable only within the scan budget.

    The traversal pops the most recently queued directory first, and each
    directory's entries are queued in sorted order, so `a_deep` -- sorted before
    every `d####` sibling -- is queued first and therefore popped LAST. The
    package inside it is found only if the budget survives all `siblings` pops
    plus the root's own.

    Returns:
        Whether the buried package resolved as first-party.

    """
    _ = _repo(root)
    _ = _package(root / "a_deep", "pkg")
    for index in range(siblings):
        (root / f"d{index:04d}").mkdir()
    return is_first_party_module("pkg", root / "svc.py")


def test_the_scan_budget_reaches_the_last_directory_it_promises(tmp_path: Path) -> None:
    # Breaks if `_MAX_DIRS_SCANNED` is lowered: the budget has to be big enough
    # to finish a real monorepo, or first-party packages silently become
    # third-party and the private-import rules stop firing.
    assert _budget_probe(tmp_path, 2998)


def test_the_scan_budget_stops_one_directory_later(tmp_path: Path) -> None:
    # Breaks if `_MAX_DIRS_SCANNED` is raised. The hard stop is what makes a
    # pathological tree degrade to under-flagging rather than hanging the linter.
    assert not _budget_probe(tmp_path, 2999)


# --- _MAX_ANCESTORS, from both sides ----------------------------------------


def test_the_project_root_is_found_at_the_deepest_walked_ancestor(tmp_path: Path) -> None:
    # Breaks if `_MAX_ANCESTORS` is lowered: a file deep in a monorepo would
    # resolve to no project at all, and nothing in it would ever be first-party.
    root = _repo(tmp_path)
    _ = _package(root, "app")
    deep = _chain(root, 23)
    assert is_first_party_module("app", deep / "svc.py")


def test_the_ancestor_walk_gives_up_one_level_further(tmp_path: Path) -> None:
    # Breaks if `_MAX_ANCESTORS` is raised. Walking up forever from a relative
    # path is how a linter ends up scanning `$HOME`.
    root = _repo(tmp_path)
    _ = _package(root, "app")
    deep = _chain(root, 24)
    assert not is_first_party_module("app", deep / "svc.py")


# --- the finer boundaries built on the same walk ----------------------------


def test_own_top_package_reports_the_outermost_importable_ancestor(tmp_path: Path) -> None:
    """PEP 420 namespace subpackages are routine, so the walk must not stop at a gap.

    A first-party repo's `app/app/lk/custom_models/` carries no `__init__.py`
    while `app/app/` does; a break-on-first-gap walk reports the file as
    belonging to no package at all.
    """
    root = _repo(tmp_path)
    outer = _package(root, "app")
    namespace = outer / "lk" / "custom_models"
    namespace.mkdir(parents=True)
    assert own_top_package(namespace / "model.py") == "app"


def test_distribution_root_is_the_nearest_packaging_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dist = root / "packages" / "svc"
    dist.mkdir(parents=True)
    _ = (dist / "pyproject.toml").write_text('[project]\nname = "svc"\n')
    package = _package(dist, "svc")
    assert distribution_root(package / "api.py") == dist


def test_a_distributions_own_test_tree_is_inside_it(tmp_path: Path) -> None:
    """The boundary the same-top-level-package proxy cannot express.

    `<dist>/tests/` is not inside `<dist>/<package>/`, yet it ships under the
    same version number and is written by the same authors.
    """
    root = _repo(tmp_path)
    dist = root / "packages" / "svc"
    dist.mkdir(parents=True)
    _ = (dist / "pyproject.toml").write_text('[project]\nname = "svc"\n')
    _ = _package(dist, "svc")
    tests = dist / "tests"
    tests.mkdir()
    assert same_distribution("svc", tests / "test_api.py")


def test_a_sibling_distribution_is_first_party_but_not_the_same_distribution(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    for name in ("one", "two"):
        dist = root / "packages" / name
        dist.mkdir(parents=True)
        _ = (dist / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
        _ = _package(dist, name)
    caller = root / "packages" / "one" / "one" / "api.py"
    assert is_first_party_module("two", caller)
    assert not same_distribution("two", caller)


def test_a_module_with_no_source_on_disk_is_not_editable(tmp_path: Path) -> None:
    """A compiled extension beside a stub has no "export it publicly" edit available.

    `pydantic_core._pydantic_core` is the standard case: the top-level package
    is first-party-shaped, but nothing in the tree declares the submodule.
    """
    root = _repo(tmp_path)
    package = _package(root, "app")
    _ = (package / "stores.py").write_text("")
    assert has_first_party_source("app.stores", root / "svc.py")
    assert not has_first_party_source("app._compiled", root / "svc.py")
