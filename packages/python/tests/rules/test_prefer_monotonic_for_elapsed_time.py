from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_monotonic_for_elapsed_time import PreferMonotonicForElapsedTime


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_BASE = "import time\ndef measure():\n    start = time.time()\n    work()\n    return time.time() - start\n"
_CASES = (
    EvaluationCase("local-elapsed", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "async-elapsed",
        Language.PYTHON,
        _BASE.replace("def measure", "async def measure").replace("    work()", "    await work()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("import time", "import time as clock").replace("time.time", "clock.time"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _BASE.replace("import time", "from time import time as now").replace("time.time", "now"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-start", Language.PYTHON, _BASE.replace("start =", "start: float ="), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "equivalent-clock-aliases",
        Language.PYTHON,
        _BASE.replace("import time", "import time\nfrom time import time as now").replace(
            "return time.time()", "return now()"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "clock-alias-reassigned",
        Language.PYTHON,
        _BASE.replace("import time", "import time as clock")
        .replace("time.time", "clock.time")
        .replace("    work()", "    clock = replacement"),
    ),
    EvaluationCase("monotonic", Language.PYTHON, _BASE.replace("time.time", "time.monotonic")),
    EvaluationCase("mixed-clocks", Language.PYTHON, _BASE.replace("return time.time", "return time.monotonic")),
    EvaluationCase("epoch-return", Language.PYTHON, _BASE.replace("time.time() - start", "start")),
    EvaluationCase("epoch-escape", Language.PYTHON, _BASE.replace("    work()", "    persist(start)")),
    EvaluationCase("epoch-format", Language.PYTHON, _BASE.replace("    work()", "    label = time.ctime(start)")),
    EvaluationCase("reassigned-start", Language.PYTHON, _BASE.replace("    work()", "    start = time.time()")),
    EvaluationCase(
        "conditional-start", Language.PYTHON, _BASE.replace("    start =", "    if enabled:\n        start =")
    ),
    EvaluationCase("aliased-start", Language.PYTHON, _BASE.replace("    work()", "    other = start")),
    EvaluationCase("object-field", Language.PYTHON, _BASE.replace("start", "self.start")),
    EvaluationCase("parameter-shadow", Language.PYTHON, _BASE.replace("measure()", "measure(time)")),
    EvaluationCase("clock-reassigned", Language.PYTHON, _BASE.replace("    work()", "    time = replacement")),
    EvaluationCase(
        "local-clock-import",
        Language.PYTHON,
        _BASE.replace("import time\n", "").replace("    start =", "    import time\n    start ="),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "wildcard-shadow", Language.PYTHON, _BASE.replace("import time", "import time\nfrom other import *")
    ),
    EvaluationCase("relative-shadow", Language.PYTHON, _BASE.replace("import time", "import time\nfrom . import time")),
    EvaluationCase(
        "comprehension-read",
        Language.PYTHON,
        _BASE.replace("return time.time() - start", "return [time.time() - start for item in items]"),
    ),
    EvaluationCase("unused-start", Language.PYTHON, _BASE.replace("return time.time() - start", "return None")),
    EvaluationCase("malformed", Language.PYTHON, "def measure(:"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_elapsed_time_cases(case: EvaluationCase) -> None:
    findings = PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_one_warning_at_start_for_multiple_measurements() -> None:
    source = _BASE.replace("    work()", "    first_elapsed = time.time() - start")
    findings = PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source)
    assert [(item.code, item.line, item.col, item.severity) for item in findings] == [
        ("SARJ461", 3, 13, Severity.WARNING)
    ]


@pytest.mark.parametrize(
    "invalidation",
    [
        "start += 1",
        "del start",
        "for start in timestamps: pass",
        "import other as start",
        "def start(): pass",
        "class start: pass",
        "def later(): return start",
        "def later(): return time.time() - start",
        "with manager() as start: pass",
        "try: work()\n    except Exception as start: pass",
        "match value:\n        case {'created': start}: pass",
        "time.time = replacement",
        "from other import clock as time",
        "try: work()\n    except Exception as time: pass",
        "match value:\n        case {'clock': time}: pass",
        "setattr(time, 'time', replacement)",
        "locals()",
        "builtins.locals()",
        "lambda: time.time() - start",
    ],
)
def test_ambiguous_or_mutated_bindings_are_excluded(invalidation: str) -> None:
    source = _BASE.replace("    work()", "    " + invalidation)
    assert PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source) == []


def test_nested_function_has_its_own_measurement() -> None:
    source = "import time\ndef outer():\n" + "\n".join("    " + line for line in _BASE.splitlines()[1:])
    assert len(PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source)) == 1


@pytest.mark.parametrize("extra", ["global start", "nonlocal start"])
def test_nonlocal_storage_is_excluded(extra: str) -> None:
    source = _BASE.replace("    start =", f"    {extra}\n    start =")
    assert PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source) == []


def test_previous_read_is_not_an_elapsed_measurement() -> None:
    source = _BASE.replace("    start =", "    before = time.time() - start\n    start =")
    assert PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source) == []


def test_reasoned_exact_suppression() -> None:
    source = _BASE.replace(
        "start = time.time()", "start = time.time()  # sarj-noqa: SARJ461 -- wall-clock correction contract"
    )
    assert PreferMonotonicForElapsedTime().check(Path("app/metrics.py"), source) == []


@pytest.mark.parametrize("example", PreferMonotonicForElapsedTime.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferMonotonicForElapsedTime().check(Path(str(focus.path)), focus.source)) == example.expected_count
