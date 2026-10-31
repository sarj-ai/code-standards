from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import RuleId

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_RULES = (
    "no-restated-comment",
    "no-trailing-numeric-unit-assignment-comment",
    "excessive-commentary",
)


@pytest.mark.parametrize(
    "body",
    [
        "Retries duplicate the transfer.",
        "A checksum mismatch signals corrupted storage.",
        "A missing record is the normal empty-cache state.",
        "Input from older callers contains this sentinel.",
        "Expected empty cache.",
    ],
)
def test_exception_causal_claims_are_retained_by_comment_fixes(body: str) -> None:
    source = f"try:\n    run()\nexcept Exception:  # {body}\n    recover()\n"
    path = Path("app/service.py")
    assert REGISTRY["no-comment-cruft"]().check(path, source) == []
    fixed = fix_source(path, source, rule_ids=["no-comment-cruft"])
    assert fixed == source
    assert fix_source(path, fixed, rule_ids=["no-comment-cruft"]) == fixed


def _example(rule_id: RuleId) -> RuleExample:
    documentation = REGISTRY[rule_id].documentation
    assert documentation is not None
    return next(example for example in documentation.examples if example.example_id == "safe-autofix-subset")


@pytest.mark.parametrize("rule_id", _RULES)
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
@pytest.mark.parametrize("final_newline", [True, False], ids=("newline", "eof"))
def test_exact_comment_fixes_preserve_code_ranges_and_converge(
    rule_id: RuleId, newline: str, *, final_newline: bool
) -> None:
    example = _example(RuleId(rule_id))
    source = example.focus_file.source
    expected = example.fixed_files[0].source
    if not final_newline:
        source = source.removesuffix("\n")
        expected = expected.removesuffix("\n")
    source = source.replace("\n", newline)
    expected = expected.replace("\n", newline)
    path = Path(example.focus_path)
    assert len(REGISTRY[rule_id]().check(path, source)) == 1
    fixed = fix_source(path, source, rule_ids=[rule_id])
    assert fixed == expected
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert not REGISTRY[rule_id]().check(path, fixed)
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed
    assert fix_source(path, source, rule_ids=[]) == source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# Load profile.\n_load_profile()\n", "\n_load_profile()\n"),
        ("# Get profile by ID\nget_profile_by_id(3)\n", "\nget_profile_by_id(3)\n"),
        ("TIMEOUT_MS = 1000.0  # 1000 ms\n", "TIMEOUT_MS = 1000.0\n"),
        ("BUFFER_BYTES = 0x400\t# 1024 bytes\n", "BUFFER_BYTES = 0x400\n"),
        ("限度_BYTES = 512  # 512 bytes\n", "限度_BYTES = 512\n"),
    ],
    ids=("private-call-period", "complete-identifier-words", "float-value", "hex-value-tab", "unicode-offset"),
)
def test_original_identifier_and_numeric_spellings_are_retained(source: str, expected: str) -> None:
    path = Path("app/service.py")
    assert fix_source(path, source, rule_ids=list(_RULES)) == expected
    assert ast.dump(ast.parse(expected), include_attributes=True) == ast.dump(
        ast.parse(source), include_attributes=True
    )


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        ("no-restated-comment", "# Load profiles\nload_profile()\n"),
        ("no-restated-comment", "# Profile load\nload_profile()\n"),
        ("no-restated-comment", "# Get profile\nget_profile_by_id(3)\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT_SECONDS = 1000  # 1000ms\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT_MS = 1000 * 1  # 1000ms\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT = 1000  # 1000ms\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT_SEC = 5 * 60  # 5 minutes\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT_SECONDS = -5  # 5 seconds\n"),
        ("no-trailing-numeric-unit-assignment-comment", "TIMEOUT_MS = 1000  # timeout: 1000ms\n"),
    ],
    ids=(
        "stem-only",
        "word-order",
        "partial-identifier",
        "different-unit",
        "arithmetic",
        "missing-unit",
        "conversion",
        "negative-value",
        "extra-words",
    ),
)
def test_native_comment_findings_with_unresolved_meaning_remain_manual(rule_id: RuleId, source: str) -> None:
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, source)
    assert fix_source(path, source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("# Collect active", "# Collect fresh active"),
        (
            "# Collect active account profile activation rejection reasons\n    # Collect current endpoint profile activation rejection reasons",
            "# Collect current endpoint profile activation rejection reasons\n    # Collect active account profile activation rejection reasons",
        ),
        (
            "collect_active_account_profile_activation_rejection_reasons()",
            "collect_active_account_profile_activation_rejection_reasons('marker')",
        ),
        ("    return values\n", "    return values\n    extra = 1\n"),
        ("    return values\n", "    return other_values()\n"),
    ],
    ids=("novel-word", "different-order", "argument-bearing-call", "additional-statement", "unrelated-return"),
)
def test_accumulation_paragraph_needs_exact_ordered_ownership(old: str, new: str) -> None:
    rule_id = "excessive-commentary"
    source = _example(RuleId(rule_id)).focus_file.source.replace(old, new)
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, source) == []
    assert fix_source(path, source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize("rule_id", _RULES)
def test_comment_fixes_preserve_suppression_and_other_comments(rule_id: RuleId) -> None:
    example = _example(RuleId(rule_id))
    code = REGISTRY[rule_id].code
    source = example.focus_file.source
    lines = source.splitlines(keepends=True)
    line = next(index for index, value in enumerate(lines) if "#" in value)
    lines[line] = lines[line].removesuffix("\n") + f"  # sarj-noqa: {code} -- existing boundary\n"
    suppressed = "".join(lines)
    assert fix_source(Path(example.focus_path), suppressed, rule_ids=[rule_id]) == suppressed


def test_comment_edits_preserve_adjacent_directive_lines() -> None:
    source = (
        "# Load profile\nload_profile()  # type: ignore[no-untyped-call]\nTIMEOUT_MS = 1000  # 1000ms\n# fmt: skip\n"
    )
    expected = "\nload_profile()  # type: ignore[no-untyped-call]\nTIMEOUT_MS = 1000\n# fmt: skip\n"
    assert fix_source(Path("app/service.py"), source, rule_ids=list(_RULES)) == expected


def test_many_exact_comment_candidates_batch_without_moving_code() -> None:
    rule_id = "no-restated-comment"
    source = "\n".join(f"def render_{index}():\n    # Load profile\n    load_profile()\n" for index in range(100))
    path = Path("app/service.py")
    assert len(REGISTRY[rule_id]().check(path, source)) == 100
    fixed = fix_source(path, source, rule_ids=[rule_id])
    assert fixed == source.replace("    # Load profile\n", "\n")
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert not REGISTRY[rule_id]().check(path, fixed)
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed


@pytest.mark.parametrize("body", ["Helpers", "Imports:", "Type aliases", "NOTE: Type aliases:", "NB: Error handling"])
def test_content_free_section_labels_are_safely_deleted(body: str) -> None:
    source = f"def load():\n    # {body}\n    load_profile()\n"
    expected = "def load():\n\n    load_profile()\n"
    path = Path("app/service.py")
    fixed = fix_source(path, source, rule_ids=["no-comment-cruft"])
    assert fixed == expected
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert fix_source(path, fixed, rule_ids=["no-comment-cruft"]) == fixed


@pytest.mark.parametrize("body", ["NOTE: Return the result", "Helper function to format output", "TODO: add a guard"])
def test_prose_narration_and_untracked_work_require_manual_deletion(body: str) -> None:
    source = f"# {body}\nVALUE = 1\n"
    path = Path("app/service.py")
    assert REGISTRY["no-comment-cruft"]().check(path, source)
    assert fix_source(path, source, rule_ids=["no-comment-cruft"]) == source


@pytest.mark.parametrize("rule_id", _RULES)
def test_comment_fixes_compile_to_identical_code_objects(rule_id: RuleId) -> None:
    source = _example(RuleId(rule_id)).focus_file.source
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[rule_id])
    assert fixed != source
    original_code = compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        source, "app/service.py", "exec", dont_inherit=True
    )
    fixed_code = compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, "app/service.py", "exec", dont_inherit=True
    )
    assert fixed_code == original_code
