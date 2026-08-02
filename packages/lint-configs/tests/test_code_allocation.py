"""`SARJ###` is one namespace across three packages, and only this package can see it."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from sarj_iac_lint.rules import REGISTRY as IAC_REGISTRY
from sarj_python_lint.rules import REGISTRY as PYTHON_REGISTRY
from sarj_sql_lint.rules import REGISTRY as SQL_REGISTRY

from sarj_lint_configs.manifest import SIBLING_PACKAGES
from sarj_lint_configs.textlint import REGISTRY as TEXT_REGISTRY


if TYPE_CHECKING:
    from collections.abc import Mapping


class _Coded(Protocol):
    """The one thing the three packages' unrelated `Rule` base classes share."""

    @property
    def code(self) -> str: ...


_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_PATH = _REPO_ROOT / ".pre-commit-hooks.yaml"

#: Distribution name to (registry, the hundreds digit its codes must use).
_BANDS: Final[Mapping[str, tuple[Mapping[str, _Coded | type[_Coded]], int]]] = {
    "sarj-python-lint": (PYTHON_REGISTRY, 0),
    "sarj-sql-lint": (SQL_REGISTRY, 1),
    "sarj-iac-lint": (IAC_REGISTRY, 2),
    "sarj-lint-configs:text": (TEXT_REGISTRY, 3),
}

_CODE_RE = re.compile(r"^SARJ(\d)(\d{2})$")

#: `additional_dependencies: ['sarj-sql-lint==0.5.0']` — the pinned spelling only.
_PIN_RE = re.compile(r"'(sarj-[a-z-]+)==([0-9][^']*)'")


@pytest.mark.parametrize("distribution", sorted(_BANDS))
def test_every_code_sits_in_its_packages_band(distribution: str) -> None:
    registry, band = _BANDS[distribution]
    wrong = sorted(
        f"{rule_id} = {cls.code}"
        for rule_id, cls in registry.items()
        if (match := _CODE_RE.match(cls.code)) is None or int(match.group(1)) != band
    )
    assert not wrong, (
        f"{distribution} codes must be SARJ{band}xx, but these are not: {wrong}. "
        "The bands are what keep a bare `# sarj-noqa: SARJ###` unambiguous across linters."
    )


def test_no_two_packages_allocate_the_same_code() -> None:
    owners: dict[str, list[str]] = {}
    for distribution, (registry, _band) in sorted(_BANDS.items()):
        for rule_id, cls in sorted(registry.items()):
            owners.setdefault(cls.code, []).append(f"{distribution}:{rule_id}")
    collisions = sorted(f"{code} -> {names}" for code, names in owners.items() if len(names) > 1)
    assert not collisions, (
        f"one SARJ code allocated by two packages: {collisions}. A consumer's "
        "`# sarj-noqa: <code>` cannot say which linter it meant, so it silences both."
    )


def _pins(text: str) -> list[tuple[str, str]]:
    """Read every `'<dist>==<version>'` pin out of the hooks file."""
    return [(match.group(1), match.group(2)) for match in _PIN_RE.finditer(text)]


def test_no_pre_commit_hook_pins_a_stale_sibling_version() -> None:
    """A pin that outlives its release ships an old linter under a fresh `rev:`."""
    stale = sorted(
        f"{name}=={pinned} (installed {installed})"
        for name, pinned in _pins(_HOOKS_PATH.read_text(encoding="utf-8"))
        if name in SIBLING_PACKAGES and pinned != (installed := version(name))
    )
    assert not stale, (
        f"{_HOOKS_PATH.name} pins a version that is no longer current: {stale}. "
        "Bump the pin with the release, or drop it and let the hook track the package."
    )
