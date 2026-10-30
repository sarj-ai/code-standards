from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from sarj_rule_contracts import (
    AutofixPolicy,
    ExampleDependency,
    ExampleFile,
    ExpectedOutcome,
    NativeRuleSpec,
    RuleCategory,
    RuleExample,
)
from sarj_rule_contracts.examples import ExampleFinding, verify_examples, verify_native_rule


def _examples() -> tuple[RuleExample, ...]:
    return tuple(
        RuleExample(
            example_id=label,
            title=label,
            outcome=outcome,
            files=(
                ExampleFile(PurePosixPath("case.py"), source),
                ExampleFile(PurePosixPath("support.py"), "value = 1\n"),
            ),
            focus_path=PurePosixPath("case.py"),
            expected_count=count,
            public=True,
        )
        for label, source, outcome, count in (
            ("rejects", "bad = True\n", ExpectedOutcome.MATCH, 1),
            ("accepts", "good = True\n", ExpectedOutcome.NO_MATCH, 0),
        )
    )


class _ExtensionRule:
    __module__ = "sarj_contract_fixture_engine_without_autofix"
    id = "extension-example"

    @classmethod
    def native_spec(cls) -> NativeRuleSpec:
        positive, negative = _examples()
        positive = replace(positive, fixed_files=(ExampleFile(positive.focus_path, "good = True\n"),))
        return NativeRuleSpec(
            engine="extension",
            rule_id=cls.id,
            code="SARJ999",
            summary="Verify an explicitly supplied extension fixer.",
            rationale="Extension engines need not follow a native module layout.",
            remediation="Supply a fixer callback for authored rewrite examples.",
            category=RuleCategory.CORRECTNESS,
            autofix=AutofixPolicy.SAFE,
            examples=(positive, negative),
        )


@pytest.mark.parametrize("supply_fix", [False, True], ids=["legacy-missing-module", "explicit-callback"])
def test_native_extension_can_supply_its_fixer_without_an_autofix_module(*, supply_fix: bool) -> None:
    def analyze(rule_ids: list[str], paths: list[Path]) -> list[ExampleFinding]:
        assert rule_ids == [_ExtensionRule.id]
        [focus] = paths
        return [ExampleFinding(focus, 1, 1, "SARJ999")] if "bad" in focus.read_text(encoding="utf-8") else []

    def fix(_root: Path, _path: Path, source: str) -> str:
        return source.replace("bad", "good")

    if supply_fix:
        assert verify_native_rule(_ExtensionRule, analyze, fix=fix) == 2
    else:
        with pytest.raises(ModuleNotFoundError, match="sarj_contract_fixture_engine_without_autofix"):
            verify_native_rule(_ExtensionRule, analyze)


@pytest.mark.parametrize("behavior", ["unimplemented", "always-clean", "always-report", "correct"])
def test_examples_reject_broken_detectors(behavior: str) -> None:
    roots: list[Path] = []

    def analyze(root: Path, focus: Path) -> list[ExampleFinding]:
        roots.append(root)
        assert (root / "support.py").read_text(encoding="utf-8") == "value = 1\n"
        if behavior == "unimplemented":
            raise NotImplementedError
        report = behavior == "always-report" or (behavior == "correct" and "bad" in focus.read_text(encoding="utf-8"))
        return [ExampleFinding(focus, 1, 1, "SARJ999")] if report else []

    if behavior == "correct":
        assert verify_examples(_examples(), analyze) == 2
        assert len(set(roots)) == 2
    else:
        with pytest.raises((ValueError, NotImplementedError)):
            verify_examples(_examples(), analyze)
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize("source", ["bad = True\n", "bad = True\r\n", "bad = True\r", "bad = '😀é'\r\n"])
def test_analyzer_receives_authored_focus_and_companion_bytes(source: str) -> None:
    positive, negative = _examples()
    positive = replace(
        positive,
        files=(
            ExampleFile(positive.focus_path, source),
            ExampleFile(PurePosixPath("support.py"), source.replace("bad =", "support =")),
        ),
    )

    def analyze(root: Path, focus: Path) -> list[ExampleFinding]:
        matches = b"bad" in focus.read_bytes()
        expected = positive if matches else negative
        for file in expected.files:
            assert (root / file.path).read_bytes() == file.source.encode("utf-8")
        return [ExampleFinding(focus, 1, 1, "SARJ999")] if matches else []

    assert verify_examples((positive, negative), analyze) == 2


def test_duplicate_diagnostics_cannot_satisfy_expected_count() -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, 1, 1, "SARJ999")] * 2

    with pytest.raises(ValueError, match="duplicate diagnostic"):
        verify_examples(_examples(), analyze)


def test_different_messages_do_not_make_duplicate_locations_independent() -> None:
    examples = (replace(_examples()[0], expected_count=2), _examples()[1])

    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        if "bad" not in focus.read_text(encoding="utf-8"):
            return []
        return [ExampleFinding(focus, 1, 1, "SARJ999", message) for message in ("first", "second")]

    with pytest.raises(ValueError, match="duplicate diagnostic"):
        verify_examples(examples, analyze)


@pytest.mark.parametrize(("line", "col", "code"), [(0, 1, "SARJ999"), (1, 0, "SARJ999"), (1, 1, " ")])
def test_invalid_diagnostic_locations_and_codes_cannot_verify_an_example(line: int, col: int, code: str) -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, line, col, code)] if "bad" in focus.read_text(encoding="utf-8") else []

    with pytest.raises(ValueError, match="invalid diagnostic"):
        verify_examples(_examples(), analyze)


def _examples_with_focus_source(source: str) -> tuple[RuleExample, ...]:
    positive, negative = _examples()
    return replace(positive, files=(ExampleFile(positive.focus_path, source),)), negative


@pytest.mark.parametrize(
    ("source", "line", "col"),
    [
        ("bad = True\n", 999, 1),
        ("bad = True\n", 1, 999),
        ("bad = True\n", 3, 1),
        ("bad = True\n", 2, 2),
        ("bad = True", 1, 12),
        ("😀é", 1, 8),
        ("bad\r\ndata\r\n", 4, 1),
        ("bad\fdata", 2, 1),
    ],
)
def test_locations_outside_the_authored_focus_source_cannot_verify_an_example(source: str, line: int, col: int) -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, line, col, "SARJ999")] if "good" not in focus.read_text(encoding="utf-8") else []

    with pytest.raises(ValueError, match="invalid diagnostic"):
        verify_examples(_examples_with_focus_source(source), analyze)


@pytest.mark.parametrize(
    ("source", "line", "col"),
    [
        ("\n", 1, 1),
        ("\n", 2, 1),
        ("bad", 1, 4),
        ("bad\n", 2, 1),
        ("bad\r\ndata\r\n", 3, 1),
        ("bad\rdata\r", 3, 1),
        ("😀é", 1, 3),
        ("😀é", 1, 4),
        ("😀é", 1, 7),
        ("bad\fdata", 1, 9),
    ],
)
def test_physical_empty_lines_eof_and_native_unicode_columns_remain_valid(source: str, line: int, col: int) -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, line, col, "SARJ999")] if "good" not in focus.read_text(encoding="utf-8") else []

    assert verify_examples(_examples_with_focus_source(source), analyze) == 2


@pytest.mark.parametrize("setup", ["options", "dependencies", "fixes"])
def test_analyzer_cannot_silently_ignore_authored_execution_context(setup: str) -> None:
    positive, negative = _examples()
    match setup:
        case "options":
            positive = replace(positive, rule_options_json="[]")
        case "dependencies":
            positive = replace(positive, installed_dependencies=(ExampleDependency("zod", "4.6.5"),))
        case _:
            positive = replace(positive, fixed_files=negative.files)

    def analyze(_root: Path, _focus: Path) -> list[ExampleFinding]:
        pytest.fail("an analyzer without a setup adapter must not verify this fixture")

    with pytest.raises(ValueError, match=r"no .* adapter"):
        verify_examples((positive, negative), analyze)


@pytest.mark.parametrize("behavior", ["correct", "unexpected", "oscillating", "still-reports"])
def test_fix_examples_require_exact_output_clean_findings_and_convergence(behavior: str) -> None:
    positive, negative = _examples()
    positive = replace(positive, fixed_files=(ExampleFile(positive.focus_path, "good = True\n"),))

    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        source = focus.read_text(encoding="utf-8")
        return [ExampleFinding(focus, 1, 1, "SARJ999")] if "bad" in source or behavior == "still-reports" else []

    def fix(_root: Path, path: Path, source: str) -> str:
        if path.name != "case.py":
            return source
        if behavior == "unexpected":
            return "other = True\n"
        if behavior == "oscillating" and source.startswith("good"):
            return "bad = True\n"
        return source.replace("bad", "good")

    if behavior == "correct":
        assert verify_examples((positive, negative), analyze, fix=fix) == 2
    else:
        with pytest.raises(ValueError, match=r"unexpected fixed|does not converge|still reports"):
            verify_examples((positive, negative), analyze, fix=fix)


def test_selected_rule_identity_is_checked_independently_of_count() -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, 1, 1, "SARJ998")] if "bad" in focus.read_text(encoding="utf-8") else []

    with pytest.raises(ValueError, match="unexpected diagnostic code"):
        verify_examples(_examples(), analyze, expected_code="SARJ999")


def test_distinct_columns_remain_independent_diagnostic_locations() -> None:
    examples = (replace(_examples()[0], expected_count=2), _examples()[1])

    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return (
            [ExampleFinding(focus, 1, col, "SARJ999") for col in (1, 7)]
            if "bad" in focus.read_text(encoding="utf-8")
            else []
        )

    assert verify_examples(examples, analyze, expected_code="SARJ999") == 2
