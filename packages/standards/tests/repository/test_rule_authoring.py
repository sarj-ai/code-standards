from __future__ import annotations

import importlib
from pathlib import PurePosixPath
import sys
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_dunder_all import NoDunderAll
from sarj_rule_contracts import ExampleFile, ExpectedOutcome, RuleExample
from sarj_rule_contracts.examples import ExampleFinding, verify_examples, verify_native_rule

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.text_rule_base import Rule
from sarj_standards.libs.repository import rule_authoring, rule_catalog_artifact, rule_registration
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
    assert len(plan.edits) == 2
    assert "this plan includes registration and warning metadata" in plan.render(tmp_path)
    assert "maintain rules evaluate --rule python:prefer-explicit-clock --scope corpus" in plan.render(tmp_path)
    compile(plan.files[0][1], str(plan.files[0][0]), "exec")


def test_apply_creates_authored_files_and_registers_atomically(tmp_path: Path) -> None:
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
    assert all(edit.path.is_file() for edit in plan.edits)
    assert "RequireExplicitTimeout.id: RequireExplicitTimeout" in plan.edits[0].path.read_text()
    with pytest.raises(FileExistsError, match="already exists"):
        rule_authoring.plan_new(
            tmp_path,
            RuleSelector.parse("sql:require-explicit-timeout"),
            category="correctness",
            summary="Queries should declare a timeout.",
        )


def test_eslint_scaffold_uses_screaming_snake_case_documentation_constant(tmp_path: Path) -> None:
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("eslint:prefer-explicit-clock"),
        category="testing",
        summary="Tests should receive an explicit clock.",
    )

    implementation = plan.files[0][1]
    test = plan.files[1][1]
    assert "export const PREFER_EXPLICIT_CLOCK_DOCUMENTATION =" in implementation
    assert "description: PREFER_EXPLICIT_CLOCK_DOCUMENTATION.summary" in implementation
    assert "documentation: PREFER_EXPLICIT_CLOCK_DOCUMENTATION" in implementation
    assert "verifyRuleExamples(rule)" in test
    assert 'defaultLevel: "warning"' in implementation
    assert "preferExplicitClockDocumentation" not in implementation + test


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

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- transaction and artifact failure interception is the behavior under test.
        transaction, "atomic_write_text", fail_second_write
    )

    with pytest.raises(OSError, match="injected failure"):
        rule_authoring.apply(plan, tmp_path)

    assert not any(path.exists() for path, _ in plan.files)


def test_allocator_never_fills_a_historical_hole(tmp_path: Path) -> None:
    ledger = tmp_path / rule_registration.LEDGER
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"codes": {"python": ["SARJ401", "SARJ403"]}}', encoding="utf-8")

    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse("python:new-rule"),
        category="style",
        summary="A new rule.",
    )

    assert plan.code == "SARJ404"


@pytest.mark.parametrize("target_kind", ["unrelated", "unwritten", "written"])
def test_scaffold_rollback_preserves_concurrent_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_kind: str
) -> None:
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:concurrent-rule"), category="correctness", summary="Concurrency fixture."
    )
    target = {
        "unrelated": tmp_path / "package.json",
        "unwritten": plan.edits[0].path,
        "written": plan.files[0][0],
    }[target_kind]
    if target_kind == "unrelated":
        target.write_text("original package\n", encoding="utf-8")
    original = transaction.atomic_write_text
    calls = 0

    def fail_after_concurrent_change(root: Path, path: Path, contents: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "injected scaffold failure"
            raise OSError(msg)
        original(root, path, contents)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("concurrent owner\n", encoding="utf-8")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- concurrent source writes are the behavior under test.
        transaction, "atomic_write_text", fail_after_concurrent_change
    )
    error = RuntimeError if target_kind == "written" else OSError
    with pytest.raises(error):
        rule_authoring.apply(plan, tmp_path)

    assert target.read_text(encoding="utf-8") == "concurrent owner\n"
    assert not plan.files[1][0].exists()


def test_verify_executes_selected_engine_without_building_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_build(_root: Path) -> None:
        msg = "selected verify must not build the full catalog"
        raise AssertionError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept live engine registries and catalog dispatch under test.
        rule_catalog_artifact, "build", forbidden_build
    )
    result = rule_authoring.verify(tmp_path, RuleSelector.parse("sql:prefer-text-over-varchar"))
    assert result.status == 0
    assert "2 executable examples" in result.message


@pytest.mark.parametrize(("engine", "suffix"), [("python", "py"), ("sql", "sql"), ("iac", "tf"), ("text", "yml")])
def test_scaffolds_have_real_suffixes_warning_defaults_and_executable_tests(
    tmp_path: Path, engine: str, suffix: str
) -> None:
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse(f"{engine}:dummy-rule"), category="correctness", summary="Dummy example detector."
    )
    source, test = (content for _, content in plan.files)
    assert f"case.{suffix}" in source
    assert ".WARNING" in source
    assert "verify_" in test
    assert "NotImplementedError" in source
    compile(source, str(plan.files[0][0]), "exec")


def test_reservation_prevents_duplicate_codes_between_unprepared_rules(tmp_path: Path) -> None:
    first = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:first-rule"), category="correctness", summary="First rule."
    )
    rule_authoring.apply(first, tmp_path)
    second = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:second-rule"), category="correctness", summary="Second rule."
    )
    assert (first.code, second.code) == ("SARJ400", "SARJ401")


def test_stale_registration_rolls_back_new_files(tmp_path: Path) -> None:
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:dummy-rule"), category="correctness", summary="Dummy example detector."
    )
    registry = plan.edits[0].path
    registry.parent.mkdir(parents=True)
    registry.write_text("concurrent owner\n")
    with pytest.raises(OSError, match="changed concurrently"):
        rule_authoring.apply(plan, tmp_path)
    assert registry.read_text() == "concurrent owner\n"
    assert all(not path.exists() for path, _ in plan.files)


@pytest.mark.parametrize("engine", ["python", "sql", "iac", "text"])
@pytest.mark.parametrize("behavior", ["unimplemented", "always-clean", "always-report", "correct"])
def test_dummy_rule_from_scaffold_through_owning_analyzer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str, behavior: str
) -> None:
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse(f"{engine}:dummy-rule"), category="correctness", summary="Dummy example detector."
    )
    rule_authoring.apply(plan, tmp_path)
    path = plan.files[0][0]
    source = _dummy_source(path.read_text(), plan.code, engine, behavior)
    path.write_text(source)
    package = "sarj_standards.libs.linting.text_rules" if engine == "text" else f"sarj_{engine}_lint.rules"
    name = f"{package}.dummy_rule"
    module = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    namespace: dict[str, object] = {"__name__": name}
    exec(compile(source, str(path), "exec"), namespace)  # ruff: ignore[exec-builtin] -- execute the generated scaffold under test.
    module.__dict__.update(namespace)
    registry_namespace: dict[str, object] = {}
    exec(compile(plan.edits[0].path.read_text(), str(plan.edits[0].path), "exec"), registry_namespace)  # ruff: ignore[exec-builtin] -- exercise the actual generated registry.
    registry: object = registry_namespace["REGISTRY"]
    if engine == "text":
        candidate = namespace["DummyRule"]
        assert isinstance(candidate, type)
        assert issubclass(candidate, Rule)
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept live engine registries and catalog dispatch under test.
            textlint, "AUTHORED_RULES", registry
        )
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept live engine registries and catalog dispatch under test.
            textlint, "REGISTRY", {"dummy-rule": candidate.documentation}
        )
    else:
        rules_module = importlib.import_module(package)
        analyzer_module = importlib.import_module(f"sarj_{engine}_lint.__main__")
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept live engine registries and catalog dispatch under test.
            rules_module, "REGISTRY", registry
        )
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept live engine registries and catalog dispatch under test.
            analyzer_module, "REGISTRY", registry
        )
    verified = rule_authoring.verify(tmp_path, plan.selector)
    assert verified.status == (0 if behavior == "correct" else 1), verified.message


def test_multifile_examples_refresh_generated_classification_between_cases() -> None:
    focus = PurePosixPath("client/models/app.py")
    source = ExampleFile(focus, "__all__ = ['value']\nvalue = 1\n")
    examples = tuple(
        RuleExample(
            example_id=label,
            title=label,
            outcome=ExpectedOutcome.MATCH if count else ExpectedOutcome.NO_MATCH,
            files=files,
            focus_path=focus,
            expected_count=count,
            public=public,
        )
        for label, files, count, public in (
            ("first-source", (source,), 1, True),
            (
                "generated-source",
                (source, ExampleFile(PurePosixPath("client/codegen.yml"), "generator: fixture\n")),
                0,
                True,
            ),
            ("fresh-source", (source,), 1, False),
        )
    )

    def run(_root: Path, path: Path) -> list[ExampleFinding]:
        return [ExampleFinding(d.path, d.line, d.col, d.code) for d in analyze(["no-dunder-all"], [path])]

    assert verify_examples(examples, run) == 3


def _dummy_source(source: str, code: str | None, engine: str, behavior: str) -> str:
    source = source.replace("TODO invalid example", "# reject").replace("TODO valid example", "# accept")
    path_expression = "context.path" if engine == "python" else "path"
    source_expression = "context.source" if engine == "python" else "source"
    result = (
        f'Finding(path, 1, "{code}", "dummy marker")'
        if engine == "text"
        else f'Diagnostic({path_expression}, 1, 1, "{code}", "dummy marker")'
    )
    if behavior != "unimplemented":
        expression = {
            "always-clean": "[]",
            "always-report": f"[{result}]",
            "correct": f'[{result}] if "# reject" in {source_expression} else []',
        }[behavior]
        source = source.replace(
            'raise NotImplementedError("TODO: implement conservative detection")', f"return {expression}"
        )
    return source


def test_generated_native_test_helper_uses_the_public_analyzer() -> None:
    assert verify_native_rule(NoDunderAll, analyze) == 2


@pytest.mark.parametrize("engine", ["python", "eslint"])
def test_registration_rejects_colliding_generated_identifiers(tmp_path: Path, engine: str) -> None:
    first = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse(f"{engine}:foo1"), category="correctness", summary="First detector."
    )
    rule_authoring.apply(first, tmp_path)
    with pytest.raises(ValueError, match="already in use"):
        rule_authoring.plan_new(
            tmp_path, RuleSelector.parse(f"{engine}:foo-1"), category="correctness", summary="Second detector."
        )


def test_allocator_preserves_live_codes_when_ledger_is_stale(tmp_path: Path) -> None:
    first = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:first-rule"), category="correctness", summary="First detector."
    )
    rule_authoring.apply(first, tmp_path)
    path = first.files[0][0]
    path.write_text(path.read_text().replace('code = "SARJ400"', 'code = "SARJ450"'))
    second = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:second-rule"), category="correctness", summary="Second detector."
    )
    assert second.code == "SARJ451"


def test_allocator_refuses_unresolved_live_rule_source(tmp_path: Path) -> None:
    first = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:first-rule"), category="correctness", summary="First detector."
    )
    rule_authoring.apply(first, tmp_path)
    first.files[0][0].unlink()
    with pytest.raises(FileNotFoundError):
        rule_authoring.plan_new(
            tmp_path, RuleSelector.parse("python:second-rule"), category="correctness", summary="Second detector."
        )


def test_verify_refuses_to_check_another_checkout_with_installed_rules(tmp_path: Path) -> None:
    marker = tmp_path / "packages/standards/src/sarj_standards/libs/repository/rule_authoring.py"
    marker.parent.mkdir(parents=True)
    marker.write_text("# other checkout\n")
    with pytest.raises(RuntimeError, match="uv run --frozen --project"):
        rule_authoring.verify(tmp_path, RuleSelector.parse("python:no-dunder-all"))
