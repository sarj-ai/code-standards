from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.duplicate_adjacent_exception_handler import DuplicateAdjacentExceptionHandler


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_BASE = "try:\n    action()\nexcept ValueError as error:\n    raise RuntimeError('invalid') from error\nexcept TypeError as error:\n    raise RuntimeError('invalid') from error\n"
_CASES = (
    EvaluationCase("identical-adjacent-handlers", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("duplicate-type-upstream-owner", Language.PYTHON, _BASE.replace("TypeError", "ValueError")),
    EvaluationCase(
        "overlapping-tuple-upstream-owner",
        Language.PYTHON,
        _BASE.replace("except ValueError", "except (ValueError, TypeError)"),
    ),
    EvaluationCase(
        "no-bound-name",
        Language.PYTHON,
        _BASE.replace(" as error", "").replace(" from error", ""),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "tuple-handler",
        Language.PYTHON,
        _BASE.replace("except ValueError", "except (ValueError, LookupError)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "different-error",
        Language.PYTHON,
        _BASE.replace(
            "except TypeError as error:\n    raise RuntimeError('invalid')",
            "except TypeError as error:\n    raise RuntimeError('unavailable')",
        ),
    ),
    EvaluationCase(
        "different-binding",
        Language.PYTHON,
        _BASE.replace("except TypeError as error:", "except TypeError as other:").replace(
            "RuntimeError('invalid') from error\n", "RuntimeError('invalid') from other\n", 1
        ),
    ),
    EvaluationCase(
        "bare-reraise-upstream", Language.PYTHON, _BASE.replace("raise RuntimeError('invalid') from error", "raise")
    ),
    EvaluationCase(
        "already-combined",
        Language.PYTHON,
        "try:\n    action()\nexcept (ValueError, TypeError) as error:\n    raise RuntimeError('invalid') from error\n",
    ),
    EvaluationCase(
        "unknown-external-error",
        Language.PYTHON,
        "from vendor import ProviderError\n" + _BASE.replace("TypeError", "ProviderError"),
    ),
    EvaluationCase(
        "conditional-error-binding", Language.PYTHON, "if configured:\n    from vendor import ValueError\n" + _BASE
    ),
    EvaluationCase("builtin-shadow", Language.PYTHON, "ValueError = provider_error\n" + _BASE),
    EvaluationCase("dynamic-error", Language.PYTHON, _BASE.replace("TypeError as", "errors.TypeError as")),
    EvaluationCase("exception-group", Language.PYTHON, _BASE.replace("except ", "except* ")),
    EvaluationCase(
        "different-comments",
        Language.PYTHON,
        _BASE.replace(
            "except TypeError as error:",
            "except TypeError as error:\n    # Provider failures require a separate rollout decision.",
        ),
    ),
    EvaluationCase("reflection", Language.PYTHON, "ValueError = globals()['failure']\n" + _BASE),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace(
            "except TypeError as error:",
            "except TypeError as error:  # sarj-noqa: SARJ488 -- independent translation seam",
        ),
    ),
    EvaluationCase("malformed", Language.PYTHON, "try:\nexcept (:"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = DuplicateAdjacentExceptionHandler().check(Path("app/service.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize(
    "example",
    DuplicateAdjacentExceptionHandler.public_examples(),
    ids=tuple(example.example_id for example in DuplicateAdjacentExceptionHandler.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert (
        len(DuplicateAdjacentExceptionHandler().check(Path(example.focus_path), example.focus_file.source))
        == example.expected_count
    )


def test_three_handlers_emit_one_stable_group() -> None:
    source = _BASE + "except LookupError as error:\n    raise RuntimeError('invalid') from error\n"
    rule = DuplicateAdjacentExceptionHandler()
    findings = rule.check(Path("app/service.py"), source)
    assert findings == rule.check(Path("app/service.py"), source)
    assert [(item.line, item.col) for item in findings] == [(5, 1)]


@pytest.mark.parametrize("mutation", ["", "First = external\n", "if enabled:\n    class First(Exception): pass\n"])
def test_resolved_first_party_exceptions(tmp_path: Path, mutation: str) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    errors = package / "errors.py"
    path = package / "service.py"
    errors.write_text(
        "class Failure(Exception): pass\nclass First(Failure): pass\nclass Second(Failure): pass\n" + mutation
    )
    source = "from app.errors import First, Second\n" + _BASE.replace("ValueError", "First").replace(
        "TypeError", "Second"
    )
    path.write_text(source)
    sources = {errors: errors.read_text(), path: source}
    rule = DuplicateAdjacentExceptionHandler()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert bool(rule.check(path, source)) is (not mutation)
