from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.corpus import CorpusKind, CorpusSource, snapshot, verify
from sarj_standards.libs.rules import (
    CatalogRule,
    DefaultLevel,
    DocumentedRule,
    EvaluationCase,
    EvaluationEvidence,
    EvaluationThresholds,
    ExampleFile,
    ExpectedOutcome,
    Finding,
    Language,
    PromotionDecision,
    RuleCatalog,
    RuleCatalogDocument,
    RuleCategory,
    RuleEngine,
    RuleExample,
    RuleId,
    RuleOrigin,
    RuleProblem,
    RuleSpec,
    evaluate,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


def _problem() -> RuleProblem:
    return RuleProblem(
        key="no-placeholder-pass",
        summary="Reject placeholder pass statements.",
        harm="A placeholder can silently ship an incomplete branch.",
        languages=frozenset({Language.PYTHON}),
        bad_examples=("def f():\n    pass\n",),
        good_examples=("def f():\n    return None\n",),
        exclusions=("protocol and abstract method bodies",),
    )


def test_problem_requires_positive_and_negative_examples() -> None:
    with pytest.raises(ValueError, match="both bad and good"):
        RuleProblem(
            key="incomplete",
            summary="summary",
            harm="harm",
            languages=frozenset({Language.PYTHON}),
            bad_examples=(),
            good_examples=("ok",),
        )


def test_catalog_filters_existing_rules_without_fuzzy_matching() -> None:
    upstream = CatalogRule(
        "ruff:PIE790",
        "Reject unnecessary pass statements.",
        RuleOrigin.UPSTREAM,
        frozenset({Language.PYTHON}),
        configurable=True,
        documentation="https://docs.astral.sh/ruff/rules/unnecessary-pass/",
    )
    custom = CatalogRule(
        "SARJ001",
        "Example custom rule.",
        RuleOrigin.SARJ,
        frozenset({Language.PYTHON}),
    )
    catalog = RuleCatalog.from_rules((custom, upstream))

    assert catalog.get("ruff:PIE790") is upstream
    assert catalog.get("pie790") is None
    assert catalog.filter(language=Language.PYTHON, origin=RuleOrigin.UPSTREAM) == (upstream,)


def _documented_spec(
    *,
    aliases: tuple[str, ...] = (),
    rule_id: str = "no-placeholder-pass",
    code: str = "TEST001",
    summary: str = "Reject placeholder pass statements.",
    rationale: str = "A placeholder can silently ship an incomplete branch.",
    remediation: str = "Implement the branch or make the abstract contract explicit.",
    examples: tuple[RuleExample, ...] | None = None,
) -> RuleSpec:
    documented_examples = examples or (
        RuleExample(
            "placeholder",
            ExpectedOutcome.MATCH,
            (ExampleFile(PurePosixPath("service.py"), "def f():\n    pass\n"),),
            PurePosixPath("service.py"),
            1,
            "A placeholder implementation is rejected",
            public=True,
        ),
        RuleExample(
            "implemented",
            ExpectedOutcome.NO_MATCH,
            (ExampleFile(PurePosixPath("service.py"), "def f():\n    return None\n"),),
            PurePosixPath("service.py"),
            0,
            "An implemented branch is accepted",
            public=True,
        ),
        RuleExample(
            "private-regression",
            ExpectedOutcome.NO_MATCH,
            (ExampleFile(PurePosixPath("internal.py"), "private_token = 1\n"),),
            PurePosixPath("internal.py"),
            0,
            "A private corpus regression",
        ),
    )
    return RuleSpec(
        engine=RuleEngine.PYTHON,
        rule_id=RuleId(rule_id),
        code=code,
        summary=summary,
        rationale=rationale,
        remediation=remediation,
        category=RuleCategory.CORRECTNESS,
        languages=frozenset({Language.PYTHON}),
        aliases=aliases,
        examples=documented_examples,
    )


def _object_table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)  # pyright: ignore[reportUnknownVariableType]
    return value  # pyright: ignore[reportUnknownVariableType]


def _object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value  # pyright: ignore[reportUnknownVariableType]


def test_documented_catalog_is_deterministic_and_excludes_private_examples() -> None:
    rule = DocumentedRule(
        _documented_spec(aliases=("placeholder-pass",)),
        DefaultLevel.WARNING,
        PurePosixPath("packages/python/src/rules/no_placeholder_pass.py"),
        PurePosixPath("packages/python/tests/rules/test_no_placeholder_pass.py"),
    )

    exported = RuleCatalogDocument((rule,)).as_public_dict()
    rendered = json.dumps(exported)

    assert exported["schemaVersion"] == 1
    assert '"key": "python:no-placeholder-pass"' in rendered
    assert '"scenarioId": "primary"' in rendered
    assert rendered.index('"id": "implemented"') < rendered.index('"id": "placeholder"')
    assert "private_token" not in rendered


def test_public_examples_must_include_accepted_and_rejected_source() -> None:
    with pytest.raises(ValueError, match="both matching and non-matching"):
        _documented_spec(
            rule_id="incomplete-docs",
            code="TEST002",
            summary="Reject incomplete documentation fixtures.",
            rationale="One-sided examples hide the rule boundary.",
            remediation="Add an accepted example.",
            examples=(
                RuleExample(
                    "rejected",
                    ExpectedOutcome.MATCH,
                    (ExampleFile(PurePosixPath("case.py"), "pass\n"),),
                    PurePosixPath("case.py"),
                    1,
                    "Rejected source",
                    public=True,
                ),
            ),
        )


def test_each_public_example_pair_must_be_complete() -> None:
    accepted = RuleExample(
        "accepted",
        ExpectedOutcome.NO_MATCH,
        (ExampleFile(PurePosixPath("case.py"), "return None\n"),),
        PurePosixPath("case.py"),
        0,
        "Accepted source",
        public=True,
        scenario="alternative",
    )

    with pytest.raises(ValueError, match=r"scenario 'alternative'.*both matching and non-matching"):
        _documented_spec(examples=(*_documented_spec().examples, accepted))


def test_non_fixing_rule_cannot_publish_fixed_source() -> None:
    rejected = RuleExample(
        "rejected",
        ExpectedOutcome.MATCH,
        (ExampleFile(PurePosixPath("case.py"), "pass\n"),),
        PurePosixPath("case.py"),
        1,
        "Rejected source",
        fixed_files=(ExampleFile(PurePosixPath("case.py"), "return None\n"),),
    )

    with pytest.raises(ValueError, match="without autofix"):
        _documented_spec(
            rule_id="no-placeholder",
            code="TEST004",
            summary="Reject placeholders.",
            rationale="Placeholders hide incomplete behavior.",
            remediation="Implement the behavior.",
            examples=(rejected,),
        )


@pytest.mark.parametrize("path", ["C:\\secret.py", "folder\\secret.py"])
def test_example_files_reject_platform_ambiguous_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative"):
        ExampleFile(PurePosixPath(path), "value = 1\n")


def test_catalog_alias_cannot_shadow_a_live_rule() -> None:
    first = DocumentedRule(
        _documented_spec(aliases=("replacement",)),
        DefaultLevel.ERROR,
        PurePosixPath("first.py"),
        PurePosixPath("test_first.py"),
    )
    second_spec = _documented_spec(
        rule_id="replacement",
        code="TEST003",
        summary="Reject replacement examples.",
        rationale="This fixture exercises collision checks.",
        remediation="Choose an unambiguous identifier.",
    )
    second = DocumentedRule(
        second_spec,
        DefaultLevel.ERROR,
        PurePosixPath("second.py"),
        PurePosixPath("test_second.py"),
    )

    with pytest.raises(ValueError, match="must not shadow"):
        RuleCatalogDocument((first, second))


def test_shipped_catalog_schema_covers_every_serialized_rule_field() -> None:
    root = Path(__file__).parents[3]
    schema_path = root / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.schema.json"
    schema_value: object = json.loads(schema_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    definitions = _object_table(_object_table(schema_value)["$defs"])
    rule_schema = _object_table(definitions["rule"])
    required = _object_list(rule_schema["required"])
    documented = DocumentedRule(
        _documented_spec(),
        DefaultLevel.ERROR,
        PurePosixPath("source.py"),
        PurePosixPath("test_source.py"),
    )
    exported = RuleCatalogDocument((documented,)).as_public_dict()
    first_rule = _object_table(_object_list(exported["rules"])[0])

    assert set(required) == set(first_rule)


def test_evaluation_reports_metrics_and_warning_first_decision() -> None:
    cases = (
        EvaluationCase(
            "bad",
            Language.PYTHON,
            "def f():\n    pass\n",
            ExpectedOutcome.MATCH,
            PurePosixPath("bad.py"),
        ),
        EvaluationCase(
            "good",
            Language.PYTHON,
            "def f():\n    return None\n",
            ExpectedOutcome.NO_MATCH,
            PurePosixPath("good.py"),
        ),
    )

    def checker(case: EvaluationCase) -> Sequence[Finding]:
        return (Finding("TEST001", 2, 5, "placeholder"),) if "pass" in case.source else ()

    report = evaluate(_problem(), "TEST001", cases, checker)

    assert report.true_positives == 1
    assert report.true_negatives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.decision is PromotionDecision.WARN


def test_false_positive_or_duplicate_location_rejects_promotion() -> None:
    case = EvaluationCase("good", Language.PYTHON, "return None", ExpectedOutcome.NO_MATCH)

    def checker(_case: EvaluationCase) -> Sequence[Finding]:
        return (
            Finding("TEST001", 1, 1, "first"),
            Finding("TEST001", 1, 1, "duplicate"),
        )

    report = evaluate(
        _problem(),
        "TEST001",
        (case,),
        checker,
        thresholds=EvaluationThresholds(minimum_cases_for_error=1),
    )

    assert report.false_positives == 1
    assert report.duplicate_locations == (("good", 1, 1),)
    assert report.decision is PromotionDecision.REJECT


def test_clean_one_sided_cases_cannot_promote_to_error() -> None:
    cases = tuple(EvaluationCase(f"negative-{index}", Language.PYTHON, "return None") for index in range(20))

    report = evaluate(_problem(), "TEST001", cases, lambda _case: ())

    assert report.decision is PromotionDecision.WARN


def test_candidate_cannot_claim_another_rules_findings() -> None:
    case = EvaluationCase("bad", Language.PYTHON, "pass", ExpectedOutcome.MATCH)

    with pytest.raises(ValueError, match="returned findings for: OTHER001"):
        evaluate(_problem(), "TEST001", (case,), lambda _case: (Finding("OTHER001", 1, 1, "overlap"),))


def test_private_case_source_and_layout_do_not_enter_report() -> None:
    secret = "private-customer-token"
    case = EvaluationCase(
        "private-case",
        Language.PYTHON,
        secret,
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("customer/internal.py"),
        private=True,
    )

    report = evaluate(
        _problem(),
        "TEST001",
        (case,),
        lambda _case: (Finding("TEST001", 1, 1, f"matched {secret}"),),
    )

    assert secret not in repr(case)
    assert secret not in repr(report)
    assert report.cases[0].path == "<private>"
    assert report.cases[0].case_id.startswith("<private:")
    assert "private-case" not in repr(report)
    assert report.cases[0].findings[0].message == "<private-finding>"


def test_private_case_ids_are_report_local_ordinals() -> None:
    cases = (
        EvaluationCase("guessable-customer-name", Language.PYTHON, "pass", private=True),
        EvaluationCase("another-customer-name", Language.PYTHON, "pass", private=True),
    )

    report = evaluate(_problem(), "TEST001", cases, lambda _case: ())

    assert tuple(case.case_id for case in report.cases) == ("<private:1>", "<private:2>")


def test_error_promotion_requires_verified_evidence_zero_errors_and_performance_budget(tmp_path: Path) -> None:
    source_file = tmp_path / "case.py"
    source_file.write_text("pass\n", encoding="utf-8")
    unverified = snapshot(CorpusSource("sample", tmp_path, CorpusKind.LOCAL, "sha256:" + "0" * 64, ("*.py",)))
    with pytest.raises(ValueError, match="verified corpora"):
        EvaluationEvidence((unverified,), "all cases", timedelta(seconds=1), timedelta(seconds=1))
    verified = verify(CorpusSource("sample", tmp_path, CorpusKind.LOCAL, unverified.digest, ("*.py",)))
    slow = EvaluationEvidence(
        (verified,),
        "all cases",
        timedelta(seconds=2),
        timedelta(seconds=1),
        maximum_slowdown=1.25,
    )
    cases = tuple(
        EvaluationCase(
            f"case-{index}",
            Language.PYTHON,
            "pass" if index == 0 else "return None",
            ExpectedOutcome.MATCH if index == 0 else ExpectedOutcome.NO_MATCH,
        )
        for index in range(20)
    )

    report = evaluate(
        _problem(),
        "TEST001",
        cases,
        lambda case: (Finding("TEST001", 1, 1, "hit"),) if case.expected is ExpectedOutcome.MATCH else (),
        evidence=slow,
    )
    assert report.decision is PromotionDecision.WARN

    permissive = EvaluationThresholds(max_false_positives=1, minimum_cases_for_error=1)
    false_positive = evaluate(
        _problem(),
        "TEST001",
        (EvaluationCase("good", Language.PYTHON, "return None"),),
        lambda _case: (Finding("TEST001", 1, 1, "hit"),),
        thresholds=permissive,
        evidence=slow,
    )
    assert false_positive.decision is PromotionDecision.WARN
