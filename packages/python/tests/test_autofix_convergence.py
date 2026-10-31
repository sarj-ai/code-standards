from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import TextEdit

import sarj_python_lint._autofix as autofix
from sarj_python_lint._autofix import (  # sarj-noqa: SARJ048 -- Control divergent builders and inspect accepted groups; public fixed-point results omit those internal states.
    _BUILDERS,  # pyright: ignore[reportPrivateUsage] -- Replace a real builder while preserving rule detection and the fix driver.
    _coherent_edits,  # pyright: ignore[reportPrivateUsage] -- Exercise the actual candidate scheduler without rebuilding it in the test.
    _FixCandidate,  # pyright: ignore[reportPrivateUsage] -- Grouped candidates define the conflict-selection invariant under test.
    fix_source,
)


if TYPE_CHECKING:
    from sarj_python_lint._autofix import _Source  # pyright: ignore[reportPrivateUsage]  # sarj-noqa: SARJ048 -- Preserve the controlled builder's private input signature without widening the public API for a fixture.
    from sarj_python_lint.rule_base import Diagnostic


_SOURCE = "# ========\nvalue = 1\n"
_GROWTH = "# growth\n"
_RULES = ("no-comment-cruft",)


@pytest.fixture
def pass_budget(monkeypatch: pytest.MonkeyPatch) -> int:
    limit = 3
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- A small private budget exercises real termination without running an unbounded predecessor.
        autofix, "_MAX_FIX_PASSES", limit
    )
    return limit


def test_nonrepeating_valid_fixes_stop_with_the_contributing_rule(
    monkeypatch: pytest.MonkeyPatch, pass_budget: int
) -> None:
    observed: list[str] = []

    def append_comment(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert diagnostic.code == "SARJ016"
        observed.append(view.text)
        return [TextEdit(len(view.text), len(view.text), _GROWTH)]

    monkeypatch.setitem(_BUILDERS, "SARJ016", append_comment)
    path = Path("app/growing.py")

    with pytest.raises(ValueError, match="pass budget exhausted") as failure:
        fix_source(path, _SOURCE, rule_ids=_RULES)

    assert str(path) in str(failure.value)
    assert f"passes={pass_budget}" in str(failure.value)
    assert "rules=SARJ016" in str(failure.value)
    assert len(observed) == pass_budget + 1
    assert len(set(observed)) == len(observed)
    for source in observed:
        compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
            source, str(path), "exec", dont_inherit=True
        )


def test_source_cycles_keep_the_existing_failure_and_attribute_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = '# ========\nvalue = "one"\n'

    def toggle_value(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert diagnostic.code == "SARJ016"
        before, after = ('"one"', '"two"') if '"one"' in view.text else ('"two"', '"one"')
        start = view.text.index(before)
        return [TextEdit(start, start + len(before), after)]

    monkeypatch.setitem(_BUILDERS, "SARJ016", toggle_value)

    with pytest.raises(ValueError, match="source cycle") as failure:
        fix_source(Path("app/cycle.py"), source, rule_ids=_RULES)

    assert "passes=2" in str(failure.value)
    assert "rules=SARJ016" in str(failure.value)


def test_convergence_exactly_at_the_budget_keeps_the_final_fixed_point(
    monkeypatch: pytest.MonkeyPatch, pass_budget: int
) -> None:
    observed: list[str] = []

    def finish_after_growth(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert diagnostic.code == "SARJ016"
        observed.append(view.text)
        if view.text.count(_GROWTH) < pass_budget - 1:
            return [TextEdit(len(view.text), len(view.text), _GROWTH)]
        return [TextEdit(0, len("# ========\n"), "")]

    monkeypatch.setitem(_BUILDERS, "SARJ016", finish_after_growth)
    path = Path("app/boundary.py")

    fixed = fix_source(path, _SOURCE, rule_ids=_RULES)

    assert fixed == "value = 1\n" + _GROWTH * (pass_budget - 1)
    assert len(observed) == pass_budget
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, str(path), "exec", dont_inherit=True
    )
    assert fix_source(path, fixed, rule_ids=_RULES) == fixed
    assert len(observed) == pass_budget


def test_noop_candidates_and_unselected_sources_keep_their_existing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_change(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert view.text == _SOURCE
        assert diagnostic.code == "SARJ016"
        return [TextEdit(0, 0, "")]

    monkeypatch.setitem(_BUILDERS, "SARJ016", no_change)
    path = Path("app/unchanged.py")

    assert fix_source(path, _SOURCE, rule_ids=_RULES) == _SOURCE
    assert fix_source(path, _SOURCE, rule_ids=[]) == _SOURCE


def test_invalid_replacements_still_fail_the_compile_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    def break_syntax(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert diagnostic.code == "SARJ016"
        return [TextEdit(0, len(view.text), "if (\n")]

    monkeypatch.setitem(_BUILDERS, "SARJ016", break_syntax)

    with pytest.raises(SyntaxError):
        fix_source(Path("app/invalid.py"), _SOURCE, rule_ids=_RULES)


def test_conflicting_groups_stay_atomic_and_only_new_accepted_work_is_attributed() -> None:
    first = TextEdit(0, 1, "a")
    second = TextEdit(4, 5, "b")
    last = TextEdit(10, 11, "c")
    candidates = [
        _FixCandidate("SARJ001", (first,)),
        _FixCandidate("SARJ002", (first,)),
        _FixCandidate("SARJ003", (TextEdit(0, 2, "x"), TextEdit(4, 5, "y"))),
        _FixCandidate("SARJ004", (TextEdit(7, 9, "x"), TextEdit(8, 10, "y"))),
        _FixCandidate("SARJ005", (first, second, last)),
    ]

    selected = _coherent_edits(candidates)

    assert selected.edits == (first, second, last)
    assert selected.codes == ("SARJ001", "SARJ005")


@pytest.mark.parametrize(
    "invalid_statement",
    [
        pytest.param("return 1\n", id="module-return"),
        pytest.param("nonlocal missing\n", id="module-nonlocal"),
        pytest.param("break\n", id="break-outside-loop"),
        pytest.param("continue\n", id="continue-outside-loop"),
        pytest.param("await call()\n", id="await-outside-async"),
        pytest.param("def broken(value, value):\n    return value\n", id="duplicate-parameters"),
    ],
)
def test_parseable_but_compile_invalid_inputs_remain_unchanged(invalid_statement: str) -> None:
    source = _SOURCE + invalid_statement
    assert isinstance(ast.parse(source), ast.Module)
    with pytest.raises(SyntaxError):
        compile(  # sarj-noqa: SARJ557 -- Compile an invalid fixture to exercise rejection of invalid scopes without executing input.
            source, "app/invalid.py", "exec", dont_inherit=True
        )
    assert fix_source(Path("app/invalid.py"), source, rule_ids=_RULES) == source


def test_stepdown_does_not_rewrite_a_parseable_module_with_invalid_scope() -> None:
    source = "def _helper(value):\n    return value\n\ndef caller(value):\n    return _helper(value)\n\nreturn 1\n"
    assert fix_source(Path("app/invalid.py"), source, rule_ids=["stepdown"]) == source


def test_template_annotation_proof_does_not_hide_a_misplaced_future_import() -> None:
    source = (
        "marker = 1\nfrom __future__ import annotations\n"
        "def _helper(value: str) -> str:\n    return value\n\n"
        "def caller(value: str) -> str:\n    return _helper(value)\n\n"
        'def template():\n    return t"value"\n'
    )
    assert fix_source(Path("app/invalid.py"), source, rule_ids=["stepdown"]) == source


def test_a_valid_generated_repair_of_invalid_input_keeps_its_existing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _SOURCE + "return 1\n"

    def repair_input(view: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
        assert diagnostic.code == "SARJ016"
        return [TextEdit(0, len(view.text), "value = 1\n")]

    monkeypatch.setitem(_BUILDERS, "SARJ016", repair_input)

    assert fix_source(Path("app/repaired.py"), source, rule_ids=_RULES) == "value = 1\n"
