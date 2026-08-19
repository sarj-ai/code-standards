from __future__ import annotations

from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.repository import rule_authoring, rule_catalog_artifact
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from pathlib import Path


def test_new_rule_is_deterministic_and_dry_by_default(tmp_path: Path) -> None:
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("python:prefer-explicit-clock"),
        category="testing",
        summary="Tests should receive an explicit clock.",
    )

    assert plan.code == "SARJ400"
    assert not any(path.exists() for path, _ in plan.files)
    assert plan.render(tmp_path) == plan.render(tmp_path)
    assert "register the rule in packages/python/src/sarj_python_lint/rules/_registry.py" in plan.render(tmp_path)
    assert "maintain rules evaluate --rule python:prefer-explicit-clock --scope corpus" in plan.render(tmp_path)
    compile(plan.files[0][1], str(plan.files[0][0]), "exec")


def test_apply_creates_only_authored_implementation_and_test(tmp_path: Path) -> None:
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("sql:require-explicit-timeout"),
        category="correctness",
        summary="Queries should declare a timeout.",
    )

    rule_authoring.apply(plan, tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path, _ in plan.files] == [
        "packages/sql/src/sarj_sql_lint/rules/require_explicit_timeout.py",
        "packages/sql/tests/rules/test_require_explicit_timeout.py",
    ]
    assert all(path.is_file() for path, _ in plan.files)
    with pytest.raises(FileExistsError, match="already exists"):
        rule_authoring.plan_new(
            tmp_path,
            RuleSelector.parse("sql:require-explicit-timeout"),
            category="correctness",
            summary="Queries should declare a timeout.",
        )


def test_apply_refuses_a_concurrently_created_target(tmp_path: Path) -> None:
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("python:prefer-explicit-clock"),
        category="testing",
        summary="Tests should receive an explicit clock.",
    )
    first = plan.files[0][0]
    first.parent.mkdir(parents=True)
    first.write_text("concurrent owner\n", encoding="utf-8")

    with pytest.raises(OSError, match="changed concurrently"):
        rule_authoring.apply(plan, tmp_path)

    assert first.read_text(encoding="utf-8") == "concurrent owner\n"
    assert not plan.files[1][0].exists()


def test_apply_rolls_back_if_a_later_atomic_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("python:prefer-explicit-clock"),
        category="testing",
        summary="Tests should receive an explicit clock.",
    )
    original = transaction.atomic_write_text
    calls = 0

    def fail_second_write(root: Path, path: Path, contents: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            detail = "injected failure"
            raise OSError(detail)
        original(root, path, contents)

    monkeypatch.setattr(transaction, "atomic_write_text", fail_second_write)

    with pytest.raises(OSError, match="injected failure"):
        rule_authoring.apply(plan, tmp_path)

    assert not any(path.exists() for path, _ in plan.files)


def test_allocator_never_fills_a_historical_hole(tmp_path: Path) -> None:
    ledger = tmp_path / "packages/standards/tests/code_ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('["SARJ401", "SARJ403"]', encoding="utf-8")

    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("python:new-rule"),
        category="style",
        summary="A new rule.",
    )

    assert plan.code == "SARJ404"


def test_verify_requires_registered_authored_files_without_todos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "rule.py"
    test = tmp_path / "test_rule.py"
    source.write_text("implemented = True\n", encoding="utf-8")
    test.write_text("tested = True\n", encoding="utf-8")
    documented = SimpleNamespace(
        spec=SimpleNamespace(
            key="python:new-rule",
            examples=(
                SimpleNamespace(public=True, outcome=SimpleNamespace(value="match")),
                SimpleNamespace(public=True, outcome=SimpleNamespace(value="no-match")),
            ),
        ),
        source=PurePosixPath("rule.py"),
        test=PurePosixPath("test_rule.py"),
    )

    def fake_build(_root: Path) -> SimpleNamespace:
        return SimpleNamespace(rules=(documented,))

    monkeypatch.setattr(rule_catalog_artifact, "build", fake_build)

    result = rule_authoring.verify(tmp_path, RuleSelector.parse("python:new-rule"))

    assert result.status == 0
    source.write_text("# TODO finish\n", encoding="utf-8")
    assert rule_authoring.verify(tmp_path, RuleSelector.parse("python:new-rule")).status == 1
