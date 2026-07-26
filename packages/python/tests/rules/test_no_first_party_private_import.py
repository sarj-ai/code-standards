"""SARJ048: private imports fire for first-party modules and never for third-party ones.

Resolution is filesystem-based, so these tests build a real project tree in a
tmp dir: a `.git` marker for the project root, two first-party packages, and a
`site-packages`-style tree standing in for a dependency. Asserting on a real
layout is the point — the whole rule is about what is on disk, and a test that
stubbed the lookup would pass while the rule shipped broken.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_first_party_private_import import NoFirstPartyPrivateImport


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Build a two-package project with a vendored dependency tree.

    Layout mirrors bulbul's: a repo root holding a `python/` workspace whose
    members each carry one package, plus a `.venv` that must never contribute
    first-party names.

    Returns:
        The repo root.

    """
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)

    for member, package in (("svc", "svc"), ("core", "core")):
        pkg = root / "python" / member / package
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").touch()
        (pkg / "helpers.py").touch()
        (pkg / "_internals.py").touch()

    # A namespace subpackage (no __init__.py), as bulbul's agent/lk/* are.
    nested = root / "python" / "svc" / "svc" / "adapters"
    nested.mkdir()
    (nested / "outbound.py").touch()

    tests_dir = root / "python" / "svc" / "tests"
    tests_dir.mkdir()

    # A dependency named `vendorlib`, only ever present inside the venv. Every
    # `vendorlib` case below is therefore also the assertion that a virtualenv
    # never contributes first-party names: the only place that name exists on
    # disk is inside `.venv/`.
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


# --------------------------------------------------------------------------- #
# The exemption: a dependency's privates are not ours to change.               #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# The enforcement: our own privates still fire.                                #
# --------------------------------------------------------------------------- #


def test_flags_first_party_private_symbol(project: Path):
    diags = _check(project, _TEST_FILE, "from core.helpers import _row_to_task")
    assert len(diags) == 1
    assert diags[0].code == "SARJ048"
    assert "_row_to_task" in diags[0].message
    assert "core.helpers" in diags[0].message


def test_flags_every_private_name_in_one_statement(project: Path):
    diags = _check(project, _TEST_FILE, "from core.helpers import public, _one, _two")
    assert [d.message.split("`")[1] for d in diags] == ["_one", "_two"]


def test_flags_first_party_private_submodule(project: Path):
    for source in ("from core._internals import Thing", "import core._internals"):
        assert len(_check(project, _TEST_FILE, source)) == 1


def test_white_box_test_reaching_into_its_own_package_fires(project: Path):
    # `python/svc/tests/` is not INSIDE the `svc` package, so this crosses a
    # package boundary exactly as an import from `core` would.
    assert len(_check(project, _TEST_FILE, "from svc.helpers import _redact")) == 1


def test_diagnostics_are_sorted_by_position(project: Path):
    source = "from core.helpers import _b\nfrom core._internals import X\n"
    diags = _check(project, _TEST_FILE, source)
    assert [d.line for d in diags] == [1, 2]


# --------------------------------------------------------------------------- #
# Same-package and metadata exemptions.                                        #
# --------------------------------------------------------------------------- #


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


def test_syntax_error_yields_no_diagnostics(project: Path):
    assert _check(project, _TEST_FILE, "from core.helpers import (") == []
