"""SARJ048 flags private imports only when the target is first-party and fixable."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_first_party_private_import import NoFirstPartyPrivateImport


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Build two workspace distributions plus an ignored virtualenv dependency."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)

    # One packaging manifest per workspace member: `svc` and `core` are separate
    # distributions, and each member's `tests/` tree is inside its own.
    for member, package in (("svc", "svc"), ("core", "core")):
        pkg = root / "python" / member / package
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").touch()
        (pkg / "helpers.py").touch()
        (pkg / "_internals.py").touch()
        (root / "python" / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n', encoding="utf-8")

    # A namespace subpackage (no __init__.py), as first-party nested trees are.
    nested = root / "python" / "svc" / "svc" / "adapters"
    nested.mkdir()
    (nested / "outbound.py").touch()

    tests_dir = root / "python" / "svc" / "tests"
    tests_dir.mkdir()

    # A dependency named `vendorlib`, only ever present inside the venv.
    dep = root / "python" / ".venv" / "lib" / "python3.14" / "site-packages" / "vendorlib"
    dep.mkdir(parents=True)
    (dep / "__init__.py").touch()

    return root


def _check(project_root: Path, relative: str, source: str) -> list[Diagnostic]:
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return NoFirstPartyPrivateImport().check(path, source)


_TEST_FILE = "python/svc/tests/test_thing.py"
_SVC_MODULE = "python/svc/svc/adapters/outbound.py"


@pytest.mark.parametrize(
    "source",
    [
        "from vendorlib.runner import _InferenceRunner",
        "from vendorlib._internal import Runner",
        "import vendorlib._internal",
        "import vendorlib._internal as vi",
        "from vendorlib.a.b import _x, _y",
    ],
)
def test_never_flags_third_party_privates(project: Path, source: str):
    assert _check(project, _TEST_FILE, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from os import _exit",
        "from concurrent.futures import _base",
        "import xml.dom._minidom",
    ],
)
def test_never_flags_stdlib_privates(project: Path, source: str):
    assert _check(project, _TEST_FILE, source) == []


def test_unresolvable_project_yields_nothing(tmp_path: Path):
    loose = tmp_path / "loose.py"
    source = "from whatever.thing import _x"
    loose.write_text(source, encoding="utf-8")
    assert NoFirstPartyPrivateImport().check(loose, source) == []


def test_flags_first_party_private_symbol(project: Path):
    diags = _check(project, _TEST_FILE, "from core.helpers import _row_to_order")
    assert len(diags) == 1
    assert diags[0].code == "SARJ048"
    assert "_row_to_order" in diags[0].message
    assert "core.helpers" in diags[0].message


def test_flags_every_private_name_in_one_statement(project: Path):
    diags = _check(project, _TEST_FILE, "from core.helpers import public, _one, _two")
    assert [d.message.split("`")[1] for d in diags] == ["_one", "_two"]


@pytest.mark.parametrize("source", ["from core._internals import Thing", "import core._internals"])
def test_flags_first_party_private_submodule(project: Path, source: str):
    assert len(_check(project, _TEST_FILE, source)) == 1


def test_white_box_test_reaching_into_its_own_package_fires(project: Path):
    # `python/svc/tests/` is not INSIDE the `svc` package, so this crosses a
    # package boundary exactly as an import from `core` would.
    assert len(_check(project, _TEST_FILE, "from svc.helpers import _redact")) == 1


def test_diagnostics_are_sorted_by_position(project: Path):
    source = "from core.helpers import _b\nfrom core._internals import X\n"
    diags = _check(project, _TEST_FILE, source)
    assert [d.line for d in diags] == [1, 2]


@pytest.mark.parametrize(
    "source",
    [
        "from . import _helper",
        "from .helpers import _redact",
        "from ..core import _thing",
    ],
)
def test_never_flags_relative_imports(project: Path, source: str):
    assert _check(project, _SVC_MODULE, source) == []


def test_absolute_import_within_own_package_is_exempt(project: Path):
    # Resolved through a namespace subpackage: `adapters/` has no __init__.py,
    # so a break-on-first-gap package walk would mis-report the owning package.
    assert _check(project, _SVC_MODULE, "from svc.helpers import _redact") == []


def test_cross_package_import_from_inside_a_package_fires(project: Path):
    assert len(_check(project, _SVC_MODULE, "from core.helpers import _redact")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from core.helpers import __version__",
        "from core.helpers import public_thing",
        "import core.helpers",
        "import json as _json",
    ],
)
def test_public_and_dunder_imports_are_clean(project: Path, source: str):
    assert _check(project, _TEST_FILE, source) == []


def test_private_top_level_package_name_is_exempt(project: Path):
    infra = project / "python" / "svc" / "tests" / "_infra"
    infra.mkdir(parents=True)
    (infra / "__init__.py").touch()
    (infra / "fakes.py").touch()
    assert _check(project, _TEST_FILE, "from _infra.fakes import FakeStt") == []


def test_private_submodule_below_a_private_top_level_package_still_fires(project: Path):
    infra = project / "python" / "core" / "_infra"
    infra.mkdir(parents=True)
    (infra / "__init__.py").touch()
    (infra / "_fakes.py").touch()
    assert len(_check(project, _TEST_FILE, "from _infra._fakes import FakeStt")) == 1


def test_syntax_error_yields_no_diagnostics(project: Path):
    assert _check(project, _TEST_FILE, "from core.helpers import (") == []


@pytest.mark.parametrize(
    "source",
    [
        "from svc._internals import Thing",
        "from svc._internals import Thing, Other",
        "import svc._internals",
        "import svc._internals as internals",
    ],
)
def test_private_segment_of_our_own_distribution_is_exempt(project: Path, source: str):
    assert _check(project, _TEST_FILE, source) == []


def test_private_name_from_our_own_distribution_still_fires(project: Path):
    # The upper bound on the guard: only the SEGMENT is exempt.
    assert len(_check(project, _TEST_FILE, "from svc._internals import _redact")) == 1


def test_mixed_public_and_private_names_from_our_own_segment_still_fires(project: Path):
    assert len(_check(project, _TEST_FILE, "from svc._internals import Thing, _redact")) == 1


def test_private_segment_of_another_distribution_still_fires(project: Path):
    assert len(_check(project, _TEST_FILE, "from core._internals import Thing")) == 1


def test_file_outside_any_distribution_is_not_exempted(project: Path):
    # A repo-level script belongs to no manifest, so nothing is "its own"
    # distribution and the reach still reports.
    assert len(_check(project, "scripts/backfill.py", "from svc._internals import Thing")) == 1


@pytest.fixture
def extension_package(project: Path) -> Path:
    """Add a distribution with private compiled and Python submodules."""
    pkg = project / "python" / "ext" / "ext"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").touch()
    (pkg / "_ext.pyi").touch()
    (pkg / "_pure.py").touch()
    (project / "python" / "ext" / "pyproject.toml").write_text('[project]\nname = "ext"\n', encoding="utf-8")
    return project


def test_compiled_extension_submodule_is_exempt(extension_package: Path):
    assert _check(extension_package, _TEST_FILE, "from ext._ext import ArgsKwargs") == []


@pytest.mark.parametrize(
    "source",
    [
        "from ext._generated import Version",
        "import ext._generated",
    ],
)
def test_private_submodule_without_python_source_is_exempt(extension_package: Path, source: str):
    assert _check(extension_package, _TEST_FILE, source) == []


def test_compiled_extension_exemption_does_not_cover_a_sibling_with_source(extension_package: Path):
    assert len(_check(extension_package, _TEST_FILE, "from ext._pure import Thing")) == 1
