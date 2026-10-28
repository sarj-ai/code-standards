import math
from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.nan_hidden_by_builtin_min import NanHiddenByBuiltinMin


_SOURCE = """import math

def validate(single: float, batched: float) -> None:
    lowest = min(single, batched)
    if not math.isfinite(lowest) or lowest < 0.99:
        raise ValueError("Invalid export")
"""
_NUMPY = """import numpy as np

def validate(single, batched):
    first = np.asarray(single, dtype=np.float64)
    second = np.asarray(batched, dtype=np.float64)
    lowest = float(min(first.min(), second.min()))
    if not np.isfinite(lowest):
        raise ValueError("Invalid export")
"""
_CASES = (
    EvaluationCase("typed-floating-values", Language.PYTHON, _SOURCE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "max-has-same-hazard", Language.PYTHON, _SOURCE.replace("min(single", "max(single"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "stable-result-alias",
        Language.PYTHON,
        _SOURCE.replace("    if not", "    checked = lowest\n    if not").replace(
            "isfinite(lowest)", "isfinite(checked)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "float-result-conversion",
        Language.PYTHON,
        _SOURCE.replace("min(single, batched)", "float(min(single, batched))"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "direct-casts",
        Language.PYTHON,
        _SOURCE.replace("single: float, batched: float", "single, batched").replace(
            "min(single, batched)", "min(float(single), float(batched))"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _SOURCE.replace("import math", "import math as numeric").replace("math.isfinite", "numeric.isfinite"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _SOURCE.replace("import math", "from math import isfinite as finite").replace("math.isfinite", "finite"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("numpy-floating-arrays", Language.PYTHON, _NUMPY, ExpectedOutcome.MATCH),
    EvaluationCase(
        "numpy-array-constructor", Language.PYTHON, _NUMPY.replace("np.asarray", "np.array"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "numpy-sum-then-min",
        Language.PYTHON,
        _NUMPY.replace("first.min()", "first.sum(axis=1).min()").replace("second.min()", "second.sum(axis=1).min()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "known-later-nan",
        Language.PYTHON,
        _SOURCE.replace("min(single, batched)", "min(1.0, float('nan'))"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "repeated-unknown-cast",
        Language.PYTHON,
        _SOURCE.replace("single: float, batched: float", "single, batched").replace(
            "min(single, batched)", "min(float(single), float(single))"
        ),
    ),
    EvaluationCase(
        "same-input-numpy-arrays", Language.PYTHON, _NUMPY.replace("np.asarray(batched", "np.asarray(single")
    ),
    EvaluationCase(
        "same-array-repeated-sum",
        Language.PYTHON,
        _NUMPY.replace("first.min()", "first.sum().min()").replace("second.min()", "first.sum(axis=None).min()"),
    ),
    EvaluationCase(
        "numpy-scalar-from-unknown-array",
        Language.PYTHON,
        _SOURCE.replace("import math", "import math\nimport numpy as np")
        .replace("single: float, batched: float", "single, batched")
        .replace("min(single, batched)", "min(np.float64(single), np.float64(batched))"),
    ),
    EvaluationCase(
        "numpy-literal-array-payload",
        Language.PYTHON,
        _NUMPY.replace("np.asarray(single", "np.asarray([1.0]").replace("np.asarray(batched", "np.asarray([2.0]"),
    ),
    EvaluationCase(
        "numpy-integer-source-parameter",
        Language.PYTHON,
        _NUMPY.replace("def validate(single, batched):", "def validate(single: int, batched: int):"),
    ),
    EvaluationCase(
        "numpy-floating-scalars",
        Language.PYTHON,
        _SOURCE.replace("import math", "import math\nimport numpy as np").replace(
            "min(single, batched)", "min(np.float64(single), np.float64(batched))"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unknown-cast-through-alias",
        Language.PYTHON,
        _SOURCE.replace("single: float, batched: float", "single, batched")
        .replace("    lowest =", "    alias = single\n    lowest =")
        .replace("min(single, batched)", "min(float(single), float(alias))"),
    ),
    EvaluationCase(
        "same-scalar-and-array-origin",
        Language.PYTHON,
        _NUMPY.replace("def validate(single, batched):", "def validate(single: float, batched: float):").replace(
            "min(first.min(), second.min())", "min(single, first.min())"
        ),
    ),
    EvaluationCase("integer-only", Language.PYTHON, _SOURCE.replace(": float", ": int")),
    EvaluationCase(
        "integer-parameter-casts",
        Language.PYTHON,
        _SOURCE.replace(": float", ": int").replace("min(single, batched)", "min(float(single), float(batched))"),
    ),
    EvaluationCase(
        "boolean-parameter-casts",
        Language.PYTHON,
        _SOURCE.replace(": float", ": bool").replace("min(single, batched)", "min(float(single), float(batched))"),
    ),
    EvaluationCase(
        "direct-boolean-casts",
        Language.PYTHON,
        _SOURCE.replace("min(single, batched)", "min(float(True), float(False))"),
    ),
    EvaluationCase(
        "string-parameter-casts",
        Language.PYTHON,
        _SOURCE.replace(": float", ": str").replace("min(single, batched)", "min(float(single), float(batched))"),
        ExpectedOutcome.MATCH,
    ),
    *(
        EvaluationCase(
            f"finite-{kind}-alias-casts",
            Language.PYTHON,
            _SOURCE.replace(
                "    lowest =",
                f"    first = {first}\n    second = {second}\n    lowest =",
            ).replace("min(single, batched)", "min(float(first), float(second))"),
        )
        for kind, first, second in (("integer", "1", "2"), ("string", "'1'", "'2'"), ("boolean", "True", "False"))
    ),
    EvaluationCase(
        "finite-chained-alias-casts",
        Language.PYTHON,
        _SOURCE.replace(
            "    lowest =",
            "    first = 1\n    first_alias = first\n    second = 2\n    second_alias = second\n    lowest =",
        ).replace("min(single, batched)", "min(float(first_alias), float(second_alias))"),
    ),
    EvaluationCase(
        "known-nan-through-alias-casts",
        Language.PYTHON,
        _SOURCE.replace("    lowest =", "    first = '1'\n    second = 'nan'\n    lowest =").replace(
            "min(single, batched)", "min(float(first), float(second))"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "untyped-external-values", Language.PYTHON, _SOURCE.replace("single: float, batched: float", "single, batched")
    ),
    EvaluationCase("shadowed-min", Language.PYTHON, _SOURCE + "\nmin = custom_reduce\n"),
    EvaluationCase(
        "custom-key", Language.PYTHON, _SOURCE.replace("min(single, batched)", "min(single, batched, key=normalize)")
    ),
    EvaluationCase(
        "one-floating-origin", Language.PYTHON, _SOURCE.replace("min(single, batched)", "min(single, single)")
    ),
    EvaluationCase(
        "aliased-floating-origin",
        Language.PYTHON,
        _SOURCE.replace("    lowest =", "    alias = single\n    lowest =").replace(
            "min(single, batched)", "min(single, alias)"
        ),
    ),
    EvaluationCase("finite-literals", Language.PYTHON, _SOURCE.replace("min(single, batched)", "min(1.0, 2.0)")),
    EvaluationCase(
        "nan-in-first-position", Language.PYTHON, _SOURCE.replace("min(single, batched)", "min(float('nan'), batched)")
    ),
    EvaluationCase(
        "prior-finiteness-validation",
        Language.PYTHON,
        _SOURCE.replace(
            "    lowest =",
            "    if not math.isfinite(single) or not math.isfinite(batched):\n        raise ValueError('Invalid input')\n    lowest =",
        ),
    ),
    EvaluationCase(
        "prior-vector-validation",
        Language.PYTHON,
        _SOURCE.replace("import math", "import math\nimport numpy as np").replace(
            "    lowest =",
            "    if not np.isfinite([single, batched]).all():\n        raise ValueError('Invalid input')\n    lowest =",
        ),
    ),
    EvaluationCase(
        "nan-propagating-numpy-minimum",
        Language.PYTHON,
        _SOURCE.replace("import math", "import math\nimport numpy as np").replace(
            "min(single, batched)", "np.minimum(single, batched)"
        ),
    ),
    EvaluationCase("unknown-array-dtype", Language.PYTHON, _NUMPY.replace(", dtype=np.float64", "")),
    EvaluationCase("integer-array-dtype", Language.PYTHON, _NUMPY.replace("dtype=np.float64", "dtype=int")),
    EvaluationCase(
        "custom-numpy-like-dispatch",
        Language.PYTHON,
        _NUMPY.replace("dtype=np.float64", "dtype=np.float64, like=custom"),
    ),
    EvaluationCase(
        "array-escapes", Language.PYTHON, _NUMPY.replace("    lowest =", "    transform(first)\n    lowest =")
    ),
    EvaluationCase(
        "numpy-namespace-mutation",
        Language.PYTHON,
        _NUMPY + "\nimport numpy as numeric\nnumeric.float64 = replacement\n",
    ),
    EvaluationCase("namespace-escape", Language.PYTHON, _SOURCE + "\nconfigure(math)\n"),
    EvaluationCase("api-escape", Language.PYTHON, _SOURCE + "\ncheck = math.isfinite\n"),
    EvaluationCase(
        "value-rebound", Language.PYTHON, _SOURCE.replace("    if not", "    lowest = substitute\n    if not")
    ),
    EvaluationCase("always-rejecting-guard", Language.PYTHON, _SOURCE.replace("lowest < 0.99", "1 < 2")),
    EvaluationCase("reflection", Language.PYTHON, _SOURCE + "\nexec(configuration)\n"),
    EvaluationCase("wildcard", Language.PYTHON, "from extension import *\n" + _SOURCE),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _SOURCE),
    EvaluationCase("malformed", Language.PYTHON, "def validate(:"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_floating_reduction_cases(case: EvaluationCase) -> None:
    findings = NanHiddenByBuiltinMin().check(Path("app/export_validation.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_native_floating_behavior_witness() -> None:
    single, batched = 1.0, float("nan")
    assert math.isfinite(min(single, batched))
    assert math.isfinite(max(single, batched))
    assert not all(math.isfinite(value) for value in (single, batched))
    assert not math.isfinite(min(batched, single))


def test_warning_is_at_the_reduction_and_can_be_suppressed() -> None:
    rule = NanHiddenByBuiltinMin()
    findings = rule.check(Path("app/export_validation.py"), _SOURCE)
    assert [(item.code, item.line, item.col, item.severity) for item in findings] == [
        ("SARJ539", 4, 14, Severity.WARNING)
    ]
    suppressed = _SOURCE.replace(
        "lowest = min(single, batched)",
        "lowest = min(single, batched)  # sarj-noqa: SARJ539 -- reviewed NaN policy",
    )
    assert rule.check(Path("app/export_validation.py"), suppressed) == []


def test_runtime_test_files_are_excluded() -> None:
    assert NanHiddenByBuiltinMin().check(Path("tests/test_export.py"), _SOURCE) == []


def test_documented_examples() -> None:
    assert verify_native_rule(NanHiddenByBuiltinMin, analyze) == 2
