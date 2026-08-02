"""Keep the shipped rule ledger equal to the registries, so removals cannot be silent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pytest
from sarj_iac_lint.rules import REGISTRY as IAC_REGISTRY
from sarj_python_lint.rules import REGISTRY as PYTHON_REGISTRY
from sarj_sql_lint.rules import REGISTRY as SQL_REGISTRY

from sarj_lint_configs import ledger
from sarj_lint_configs.doctor import Level, check_retired_rules
from sarj_lint_configs.textlint import REGISTRY as TEXT_REGISTRY


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@runtime_checkable
class _Coded(Protocol):
    """The one attribute this file needs from a rule, across four packages."""

    @property
    def code(self) -> str: ...


_REGISTRIES: Mapping[str, Mapping[str, object]] = {
    "python": PYTHON_REGISTRY,
    "sql": SQL_REGISTRY,
    "iac": IAC_REGISTRY,
    "text": TEXT_REGISTRY,
}


def _code(rule: object) -> str:
    assert isinstance(rule, _Coded)
    return rule.code


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
    live = {_code(rule) for rule in _REGISTRIES[family].values()}
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
    assert renames, "four ESLint rules have been renamed; a ledger with no rename has lost them"
    broken = [entry.id for entry in renames if entry.replacement is None or entry.replacement not in live]
    assert not broken, (
        f"{broken} say they were renamed to something that does not exist, so `doctor`"
        " would send a consumer to a rule they cannot enable."
    )


def test_every_deleted_alias_is_recorded(shipped: ledger.Ledger) -> None:
    recorded = {entry.id: entry.replacement for entry in shipped.retired if entry.status is ledger.Status.RENAMED}
    missing = {old: new for old, new in _ALIASES_DELETED_IN_9_0_0.items() if recorded.get(old) != new}
    assert not missing, (
        f"{sorted(missing)} were registered aliases in 7.0.0 and resolve nowhere in"
        " 9.0.0. Dropping the ledger row leaves a consumer holding the old name with"
        " `Could not find <rule> in plugin` and nothing naming the replacement."
    )


def test_every_retired_entry_carries_advice(shipped: ledger.Ledger) -> None:
    assert shipped.retired, "four rules and a code have been retired; the ledger records them"
    unhelpful = [entry.id for entry in shipped.retired if "TODO" in entry.note or len(entry.note) <= 20]
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


def test_doctor_removes_loose_type_guard_references_without_replacement(tmp_path: Path) -> None:
    rule = "@sarj/ban-loose-type-guards-in-tests"
    _ = (tmp_path / "eslint.config.mjs").write_text(
        f'export default [{{ rules: {{ "{rule}": "error" }} }}];\n', encoding="utf-8"
    )
    _ = (tmp_path / "widget.test.ts").write_text(
        f"// eslint-disable-next-line {rule}\nexpect(typeof value).toBe('string');\n",
        encoding="utf-8",
    )
    _ = (tmp_path / "eslint-suppressions.json").write_text(
        f'{{"widget.test.ts": {{"{rule}": {{"count": 1}}}}}}\n', encoding="utf-8"
    )

    findings = sorted(check_retired_rules(tmp_path), key=lambda finding: finding.where)
    assert [finding.where for finding in findings] == [
        f"eslint-suppressions.json: {rule} x1",
        f"eslint.config.mjs: {rule} x1",
        f"widget.test.ts: {rule} x1",
    ]
    assert all("no longer exists" in finding.detail for finding in findings)
    assert all("there is no replacement" in finding.detail for finding in findings)


#: The aliases `@sarj/eslint-plugin` 7.0.0 registered and 9.0.0 deleted. Frozen: a
#: consumer that adopted 7.0.0 may hold any of these, and each is now `ESLint: exit
#: 2` rather than a deprecation warning, so the ledger is the only thing that can
#: name the replacement.
_ALIASES_DELETED_IN_9_0_0 = {
    "@sarj/jsdoc-restates-signature": "@sarj/no-restated-jsdoc",
    "@sarj/no-async-callback-in-waitfor": "@sarj/no-async-callback-in-wait-for",
    "@sarj/strict-test-assertions": "@sarj/prefer-whole-object-assertion",
    "@sarj/trailing-value-narration": "@sarj/no-trailing-value-narration",
}


@pytest.mark.parametrize(("old", "new"), sorted(_ALIASES_DELETED_IN_9_0_0.items()))
def test_doctor_points_a_deleted_alias_at_its_replacement(tmp_path: Path, old: str, new: str) -> None:
    _ = (tmp_path / "eslint.config.mjs").write_text(
        f'export default [{{ rules: {{ "{old}": "error" }} }}];\n', encoding="utf-8"
    )
    findings = list(check_retired_rules(tmp_path))
    assert [finding.level for finding in findings] == [Level.DRIFT], (
        f"{old} stopped resolving in 9.0.0; a consumer who adopted 7.0.0's alias gets"
        " a whole unlintable repo, and doctor is what tells them before the upgrade"
    )
    assert f"{old} x1" in findings[0].where
    assert f"renamed to {new}" in findings[0].detail
    assert "no longer resolves" in findings[0].detail


def test_doctor_finds_a_deleted_alias_in_source_and_suppressions(tmp_path: Path) -> None:
    old = "@sarj/jsdoc-restates-signature"
    new = "@sarj/no-restated-jsdoc"
    _ = (tmp_path / "widget.ts").write_text(
        f"// eslint-disable-next-line {old}\nexport const widget = 1;\n",
        encoding="utf-8",
    )
    _ = (tmp_path / "eslint-suppressions.json").write_text(
        f'{{"widget.ts": {{"{old}": {{"count": 1}}}}}}\n',
        encoding="utf-8",
    )

    findings = sorted(check_retired_rules(tmp_path), key=lambda finding: finding.where)
    assert [finding.where for finding in findings] == [
        f"eslint-suppressions.json: {old} x1",
        f"widget.ts: {old} x1",
    ]
    assert all(f"renamed to {new}" in finding.detail for finding in findings)


def test_doctor_leaves_the_python_twin_of_a_deleted_eslint_alias_alone(tmp_path: Path) -> None:
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - hooks:\n      - id: sarj-trailing-value-narration\n", encoding="utf-8"
    )
    assert not list(check_retired_rules(tmp_path)), (
        "`trailing-value-narration` is a LIVE sarj-python-lint rule and its hook id;"
        " only the ESLint rule of that name was renamed, and flagging the hook would"
        " tell a consumer to delete a check that still exists"
    )


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


def test_doctor_names_every_sarj061_consumer_reference(tmp_path: Path) -> None:
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: sarj-no-patching-system-under-test\n",
        encoding="utf-8",
    )
    _ = (tmp_path / "service.py").write_text("value = load()  # sarj-noqa: SARJ061\n", encoding="utf-8")
    _ = (tmp_path / ".sarj-python-baseline.json").write_text('{"service.py": {"SARJ061": 2}}\n', encoding="utf-8")

    findings = sorted(check_retired_rules(tmp_path), key=lambda finding: finding.where)
    assert [finding.where for finding in findings] == [
        ".pre-commit-config.yaml: no-patching-system-under-test x1",
        ".sarj-python-baseline.json: SARJ061 x1",
        "service.py: SARJ061 x1",
    ]
    assert all("no longer exists" in finding.detail for finding in findings)
    assert all("there is no replacement" in finding.detail for finding in findings[1:])


def test_doctor_tells_a_chained_retirement_to_delete_rather_than_renumber(
    tmp_path: Path,
) -> None:
    """SARJ055 was renumbered to SARJ083, and then SARJ083 was removed outright."""
    _ = (tmp_path / "service.py").write_text("value = data['k']  # sarj-noqa: SARJ055\n", encoding="utf-8")
    findings = list(check_retired_rules(tmp_path))
    assert len(findings) == 1
    assert "no longer exists" in findings[0].detail
    assert "SARJ083" not in findings[0].detail.split("--")[0]


def test_doctor_names_a_removed_python_hook_and_its_code(tmp_path: Path) -> None:
    _ = (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - hooks:\n      - id: sarj-no-implicit-attribute-access\n", encoding="utf-8"
    )
    _ = (tmp_path / "service.py").write_text("value = payload['id']  # sarj-noqa: SARJ083\n", encoding="utf-8")
    _ = (tmp_path / ".sarj-python-baseline.json").write_text('{"src/api.py": {"SARJ083": 4}}\n', encoding="utf-8")
    findings = sorted(check_retired_rules(tmp_path), key=lambda finding: finding.where)
    assert [finding.where for finding in findings] == [
        ".pre-commit-config.yaml: no-implicit-attribute-access x1",
        ".sarj-python-baseline.json: SARJ083 x1",
        "service.py: SARJ083 x1",
    ]
    assert all("no longer exists" in finding.detail for finding in findings)
    assert all("there is no replacement" in finding.detail for finding in findings)


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
