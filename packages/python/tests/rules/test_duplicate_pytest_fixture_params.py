from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.duplicate_pytest_fixture_params import DuplicatePytestFixtureParams


_BASE = 'import pytest\n\n@pytest.fixture(params=("empty", "empty"))\ndef payload(request):\n    return request.param\n'
CASES = (
    EvaluationCase("duplicate", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("distinct", Language.PYTHON, _BASE.replace('"empty", "empty"', '"empty", "filled"')),
    EvaluationCase(
        "default-ids", Language.PYTHON, _BASE.replace("params=", "ids=None, params="), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("import pytest", "import pytest as pt").replace("@pytest", "@pt"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "direct-alias",
        Language.PYTHON,
        _BASE.replace("import pytest", "from pytest import fixture as fx").replace("pytest.fixture", "fx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-provider",
        Language.PYTHON,
        _BASE.replace("pytest", "pytest_asyncio").replace("def payload", "async def payload"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "named-fixture", Language.PYTHON, _BASE.replace("params=", 'name="data", params='), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "class-fixture",
        Language.PYTHON,
        "import pytest\nclass TestPayload:\n" + "\n".join("    " + line for line in _BASE.splitlines()[2:]),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("explicit-ids", Language.PYTHON, _BASE.replace("params=", 'ids=("first", "retry"), params=')),
    EvaluationCase("id-function", Language.PYTHON, _BASE.replace("params=", "ids=str, params=")),
    EvaluationCase(
        "identity-index",
        Language.PYTHON,
        _BASE.replace("return request.param", "return request.param, request.param_index"),
    ),
    EvaluationCase("identity-node", Language.PYTHON, _BASE.replace("return request.param", "return request.node")),
    EvaluationCase("escaped-request", Language.PYTHON, _BASE.replace("return request.param", "return build(request)")),
    EvaluationCase(
        "written-request",
        Language.PYTHON,
        _BASE.replace("return request.param", "request.param = transform(request.param)\n    return request.param"),
    ),
    EvaluationCase("decorator-unpacking", Language.PYTHON, _BASE.replace("params=", "**options, params=")),
    EvaluationCase("decorator-args", Language.PYTHON, _BASE.replace("params=", "factory, params=")),
    EvaluationCase("wrapper", Language.PYTHON, _BASE.replace("def payload", "@adapt\ndef payload")),
    EvaluationCase("unknown-provider", Language.PYTHON, _BASE.replace("import pytest", "import custom as pytest")),
    EvaluationCase("rebound-provider", Language.PYTHON, _BASE.replace("@pytest", "pytest = custom\n@pytest")),
    EvaluationCase("mutated-provider", Language.PYTHON, _BASE.replace("@pytest", "pytest.fixture = custom\n@pytest")),
    EvaluationCase(
        "class-shadow",
        Language.PYTHON,
        "import pytest\nclass TestPayload:\n    pytest = custom\n"
        + "\n".join("    " + line for line in _BASE.splitlines()[2:]),
    ),
    EvaluationCase(
        "parametrize-owner",
        Language.PYTHON,
        _BASE.replace("pytest.fixture(params=", 'pytest.mark.parametrize("payload", ').replace(
            "def payload(request)", "def test_payload(payload)"
        ),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase("malformed", Language.PYTHON, "@pytest.fixture(params=("),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace('"empty"))', '"empty"))  # sarj-noqa: SARJ524 -- repeated-run contract'),
    ),
    EvaluationCase(
        "other-suppression",
        Language.PYTHON,
        _BASE.replace('"empty"))', '"empty"))  # sarj-noqa: SARJ525 -- unrelated'),
        ExpectedOutcome.MATCH,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = DuplicatePytestFixtureParams().check(Path("tests/conftest.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ("1, +1", 1),
        ("-2, -2", 1),
        ("1.0, +1.0", 1),
        ("-0.0, -0.0", 1),
        ("True, True", 1),
        ("None, None", 1),
        ("b'raw', b'raw'", 1),
        ("('a', (1, None)), ('a', (1, None))", 1),
        ("True, 1, 1.0", 0),
        ("0.0, -0.0", 0),
        ("('a', 1), ('a', True)", 0),
        ("[1], [1]", 0),
        ("{'a': 1}, {'a': 1}", 0),
        ("({1},), ({1},)", 0),
        ("VALUE, VALUE", 0),
        ("factory(), factory()", 0),
        ("pytest.param(1, id='first'), pytest.param(1, id='retry')", 0),
        ("*VALUES, *VALUES", 0),
    ],
)
def test_only_proven_immutable_literals_are_compared(values: str, expected: int) -> None:
    source = _BASE.replace('"empty", "empty"', values)
    assert len(DuplicatePytestFixtureParams().check(Path("tests/conftest.py"), source)) == expected


def test_each_later_duplicate_points_to_the_original_parameter() -> None:
    source = _BASE.replace('("empty", "empty")', '[\n    "empty",\n    "empty",\n    "empty",\n]')
    findings = DuplicatePytestFixtureParams().check(Path("tests/conftest.py"), source)
    assert [(finding.line, finding.col, finding.severity) for finding in findings] == [
        (5, 5, Severity.WARNING),
        (6, 5, Severity.WARNING),
    ]
    assert all("line 4" in finding.message for finding in findings)


def test_non_test_code_is_outside_scope() -> None:
    assert DuplicatePytestFixtureParams().check(Path("app/fixtures.py"), _BASE) == []


def test_deeply_nested_literal_parameters_keep_a_bounded_key() -> None:
    nested = "(" * 40 + "('value',)" + ",)" * 40
    source = _BASE.replace('"empty", "empty"', f"{nested}, {nested}")
    findings = DuplicatePytestFixtureParams().check(Path("tests/conftest.py"), source)
    assert len(findings) == 1


def test_documented_examples() -> None:
    verify_native_rule(DuplicatePytestFixtureParams, analyze)
