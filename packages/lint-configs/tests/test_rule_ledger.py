"""Keep the shipped rule ledger equal to the registries, so removals cannot be silent.

A deleted rule is not a lint-level change downstream: a flat config naming a rule
the plugin no longer defines makes ESLint exit 2 before it reads a file, and a
pre-commit hook id that no longer exists fails the same way. The ledger is what
`doctor` reads to name those references BEFORE the upgrade that breaks them, so a
ledger that has fallen behind the registries is worse than none -- it reports a
clean repo.

These tests are the thing that makes the mechanism durable rather than a list of
four names someone wrote down once. Removing a rule fails
`test_every_live_<x>_is_in_the_ledger` until the ledger is regenerated, and
`make sync-rule-ledger` retires rather than deletes, so the removal ends up
recorded whether or not the author thought about consumers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest
from sarj_iac_lint.rules import REGISTRY as IAC_REGISTRY
from sarj_python_lint.rules import REGISTRY as PYTHON_REGISTRY
from sarj_sql_lint.rules import REGISTRY as SQL_REGISTRY

from sarj_lint_configs import ledger
from sarj_lint_configs.doctor import Level, check_retired_rules


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class _Coded(Protocol):
    """The one attribute this file needs from a rule, across four packages."""

    code: str


_REGISTRIES: Mapping[str, Mapping[str, type[_Coded]]] = {
    "python": PYTHON_REGISTRY,
    "sql": SQL_REGISTRY,
    "iac": IAC_REGISTRY,
}


@pytest.fixture(name="shipped", scope="module")
def _shipped() -> ledger.Ledger:
    return ledger.load()


@pytest.mark.parametrize("family", sorted(_REGISTRIES))
def test_every_live_rule_is_in_the_ledger(shipped: ledger.Ledger, family: str) -> None:
    live = set(_REGISTRIES[family])
    assert set(shipped.rules[family]) == live, (
        f"the ledger's {family} rules disagree with the registry. Run"
        " `make sync-rule-ledger`; it retires what left rather than dropping it."
    )


@pytest.mark.parametrize("family", sorted(_REGISTRIES))
def test_every_live_code_is_in_the_ledger(shipped: ledger.Ledger, family: str) -> None:
    live = {rule.code for rule in _REGISTRIES[family].values()}
    assert set(shipped.codes[family]) == live, (
        f"the ledger's {family} codes disagree with the registry. Run `make sync-rule-ledger`."
    )


def test_no_retired_identifier_is_live_again(shipped: ledger.Ledger) -> None:
    live = shipped.active_ids()
    resurrected = sorted(retired for entry in shipped.retired if (retired := entry.id) in live)
    assert not resurrected, (
        f"{resurrected} are recorded as retired but exist again. Recycling an identifier"
        " makes `doctor` tell consumers to delete a reference that is now correct;"
        " allocate a fresh one, or drop the ledger entry deliberately."
    )


def test_every_rename_points_somewhere_live(shipped: ledger.Ledger) -> None:
    live = shipped.active_ids()
    renames = [entry for entry in shipped.retired if entry.status is ledger.Status.RENAMED]
    assert renames, "SARJ055 -> SARJ083 happened; a ledger with no rename has lost it"
    broken = [
        entry.id for entry in renames if entry.replacement is None or entry.replacement not in live
    ]
    assert not broken, (
        f"{broken} say they were renamed to something that does not exist, so `doctor`"
        " would send a consumer to a rule they cannot enable."
    )


def test_every_retired_entry_carries_advice(shipped: ledger.Ledger) -> None:
    assert shipped.retired, "four rules and a code have been retired; the ledger records them"
    unhelpful = [
        entry.id for entry in shipped.retired if "TODO" in entry.note or len(entry.note) <= 20
    ]
    assert not unhelpful, (
        f"{unhelpful} still carry the placeholder note `make sync-rule-ledger` writes."
        " A consumer reading `doctor` output needs to know what to do instead."
    )


def test_doctor_names_a_removed_eslint_rule_in_a_config(tmp_path: Path) -> None:
    _ = (tmp_path / "eslint.config.mjs").write_text(
        'export default [{ rules: { "@sarj/prefer-setup-file-mocks": "error" } }];\n',
        encoding="utf-8",
    )
    findings = list(check_retired_rules(tmp_path))
    assert [finding.level for finding in findings] == [Level.DRIFT]
    assert "@sarj/prefer-setup-file-mocks x1" in findings[0].where
    assert "no longer exists" in findings[0].detail


def test_doctor_names_a_stale_disable_directive(tmp_path: Path) -> None:
    _ = (tmp_path / "widget.tsx").write_text(
        "// eslint-disable-next-line @sarj/no-implicit-attribute-access\nexport const a = 1;\n",
        encoding="utf-8",
    )
    findings = list(check_retired_rules(tmp_path))
    assert len(findings) == 1, (
        "a stale disable directive is its own error under the shipped strict config's"
        " reportUnusedDisableDirectives, so doctor has to see source, not just configs"
    )


def test_doctor_names_a_removed_precommit_hook(tmp_path: Path) -> None:
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: sarj-no-patching-system-under-test\n",
        encoding="utf-8",
    )
    findings = list(check_retired_rules(tmp_path))
    assert len(findings) == 1
    assert "no-patching-system-under-test" in findings[0].where


def test_doctor_points_a_renamed_code_at_its_replacement(tmp_path: Path) -> None:
    _ = (tmp_path / "service.py").write_text(
        "value = data['k']  # sarj-noqa: SARJ055\n", encoding="utf-8"
    )
    findings = list(check_retired_rules(tmp_path))
    assert len(findings) == 1
    assert "renamed to SARJ083" in findings[0].detail


def test_doctor_leaves_a_live_rule_alone(tmp_path: Path) -> None:
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - hooks:\n      - id: sarj-no-implicit-attribute-access\n", encoding="utf-8"
    )
    assert not list(check_retired_rules(tmp_path)), (
        "the Python rule of that name still exists; only the ESLint rule was removed,"
        " and conflating the two namespaces would send consumers to delete a live hook"
    )


def test_doctor_does_not_flag_prose_that_merely_contains_a_rule_name(tmp_path: Path) -> None:
    _ = (tmp_path / "notes.py").write_text(
        "# we used to rely on no-patching-system-under-test for sarj checks\n", encoding="utf-8"
    )
    assert not list(check_retired_rules(tmp_path))


def test_doctor_counts_repeats_in_one_file(tmp_path: Path) -> None:
    _ = (tmp_path / "eslint-suppressions.json").write_text(
        '{"a": {"@sarj/prefer-setup-file-mocks": 1}, "b": {"@sarj/prefer-setup-file-mocks": 2}}\n',
        encoding="utf-8",
    )
    findings = list(check_retired_rules(tmp_path))
    assert len(findings) == 1, "one line per file per rule, not one per occurrence"
    assert "x2" in findings[0].where
