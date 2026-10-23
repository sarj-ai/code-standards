from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.pytest_fixture_returns_closed_resource import PytestFixtureReturnsClosedResource


_BASE = 'from io import StringIO\nimport pytest\n\n@pytest.fixture\ndef stream():\n    with StringIO("payload") as handle:\n        return handle\n'
CASES = (
    EvaluationCase("closed-stream", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("yield", Language.PYTHON, _BASE.replace("return handle", "yield handle")),
    EvaluationCase("snapshot", Language.PYTHON, _BASE.replace("return handle", "return handle.getvalue()")),
    EvaluationCase("closed-state", Language.PYTHON, _BASE.replace("return handle", "return handle.closed")),
    EvaluationCase("container", Language.PYTHON, _BASE.replace("return handle", "return [handle]")),
    EvaluationCase("other-value", Language.PYTHON, _BASE.replace("return handle", "return StringIO('other')")),
    EvaluationCase("after-with", Language.PYTHON, _BASE.replace("        return handle", "    return handle")),
    EvaluationCase("alias", Language.PYTHON, _BASE.replace("return handle", "other = handle\n        return other")),
    EvaluationCase(
        "escaped", Language.PYTHON, _BASE.replace("return handle", "configure(handle)\n        return handle")
    ),
    EvaluationCase(
        "rebound-resource", Language.PYTHON, _BASE.replace("return handle", "handle = other\n        return handle")
    ),
    EvaluationCase(
        "mutated-resource",
        Language.PYTHON,
        _BASE.replace("return handle", "handle.close = custom\n        return handle"),
    ),
    EvaluationCase("rebound-provider", Language.PYTHON, _BASE.replace("@pytest", "StringIO = custom\n@pytest")),
    EvaluationCase("shadowed-provider", Language.PYTHON, _BASE.replace("def stream():", "def stream(StringIO):")),
    EvaluationCase(
        "unknown-context", Language.PYTHON, _BASE.replace("from io import StringIO", "from custom import StringIO")
    ),
    EvaluationCase(
        "nullcontext",
        Language.PYTHON,
        _BASE.replace("from io import StringIO", "from contextlib import nullcontext as StringIO"),
    ),
    EvaluationCase(
        "test-client",
        Language.PYTHON,
        _BASE.replace("from io import StringIO", "from starlette.testclient import TestClient as StringIO"),
    ),
    EvaluationCase(
        "temporary-path",
        Language.PYTHON,
        _BASE.replace("from io import StringIO", "from tempfile import TemporaryDirectory as StringIO"),
    ),
    EvaluationCase("unknown-fixture", Language.PYTHON, _BASE.replace("import pytest", "import custom as pytest")),
    EvaluationCase("wrapped-fixture", Language.PYTHON, _BASE.replace("def stream", "@adapt\ndef stream")),
    EvaluationCase(
        "unpacked-decorator", Language.PYTHON, _BASE.replace("@pytest.fixture", "@pytest.fixture(**options)")
    ),
    EvaluationCase(
        "nested-helper",
        Language.PYTHON,
        _BASE.replace("    with StringIO", "    def build():\n        with StringIO").replace(
            "        return handle", "            return handle\n    return build()"
        ),
    ),
    EvaluationCase(
        "nested-generator",
        Language.PYTHON,
        _BASE.replace("    with StringIO", "    def helper():\n        yield 'unrelated'\n    with StringIO"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "own-generator",
        Language.PYTHON,
        _BASE.replace("    with StringIO", "    if enabled:\n        yield 'other'\n    with StringIO"),
    ),
    EvaluationCase(
        "fixture-alias",
        Language.PYTHON,
        _BASE.replace("import pytest", "from pytest import fixture as fx").replace("pytest.fixture", "fx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "named-fixture",
        Language.PYTHON,
        _BASE.replace("@pytest.fixture", '@pytest.fixture(name="data")'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-fixture",
        Language.PYTHON,
        "from io import StringIO\nimport pytest\nclass TestStream:\n"
        + "\n".join("    " + line for line in _BASE.splitlines()[3:]),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "provider-module-alias",
        Language.PYTHON,
        _BASE.replace("from io import StringIO", "import io as streams").replace("StringIO(", "streams.StringIO("),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "mutated-module",
        Language.PYTHON,
        _BASE.replace("from io import StringIO", "import io\nio.StringIO = custom").replace(
            "StringIO(", "io.StringIO("
        ),
    ),
    EvaluationCase(
        "mutated-import-sibling",
        Language.PYTHON,
        _BASE.replace(
            "from io import StringIO", "from io import StringIO\nimport io as streams\nstreams.StringIO = custom"
        ),
    ),
    EvaluationCase(
        "escaped-constructor", Language.PYTHON, _BASE.replace("@pytest.fixture", "configure(StringIO)\n@pytest.fixture")
    ),
    EvaluationCase(
        "method-use",
        Language.PYTHON,
        _BASE.replace("return handle", "handle.seek(0)\n        return handle"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("wildcard", Language.PYTHON, "from custom import *\n" + _BASE),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase("malformed", Language.PYTHON, "with:"),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace("return handle", "return handle  # sarj-noqa: SARJ525 -- deliberately closed fixture"),
    ),
    EvaluationCase(
        "other-suppression",
        Language.PYTHON,
        _BASE.replace("return handle", "return handle  # sarj-noqa: SARJ524 -- unrelated"),
        ExpectedOutcome.MATCH,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = PytestFixtureReturnsClosedResource().check(Path("tests/conftest.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


@pytest.mark.parametrize(
    ("provider", "constructor"),
    [
        ("from io import BytesIO", "BytesIO()"),
        ("from io import open as stream_file", "stream_file('payload')"),
        ("import builtins", "builtins.open('payload')"),
        ("", "open('payload')"),
        ("from tempfile import TemporaryFile", "TemporaryFile()"),
        ("from tempfile import NamedTemporaryFile", "NamedTemporaryFile(delete=False)"),
        ("import httpx", "httpx.Client()"),
    ],
)
def test_known_synchronous_resource_contracts(provider: str, constructor: str) -> None:
    source = _BASE.replace("from io import StringIO", provider).replace('StringIO("payload")', constructor)
    findings = PytestFixtureReturnsClosedResource().check(Path("tests/conftest.py"), source)
    assert [(finding.line, finding.col, finding.severity) for finding in findings] == [(7, 9, Severity.WARNING)]


@pytest.mark.parametrize("uses_yield", [False, True], ids=("return", "yield"))
def test_async_client_lifetime(uses_yield: bool) -> None:
    source = (
        _BASE.replace("from io import StringIO", "import httpx")
        .replace("import pytest", "import pytest_asyncio as pytest")
        .replace("def stream", "async def stream")
        .replace('with StringIO("payload")', "async with httpx.AsyncClient()")
    )
    if uses_yield:
        source = source.replace("return handle", "yield handle")
    assert len(PytestFixtureReturnsClosedResource().check(Path("tests/conftest.py"), source)) == (
        0 if uses_yield else 1
    )


@pytest.mark.parametrize("binding", ["open = custom", "from custom import open\nfrom other import open"])
def test_shadowed_builtin_open_is_excluded(binding: str) -> None:
    source = _BASE.replace("from io import StringIO", binding).replace('StringIO("payload")', "open('payload')")
    assert PytestFixtureReturnsClosedResource().check(Path("tests/conftest.py"), source) == []


def test_non_test_code_is_outside_scope() -> None:
    assert PytestFixtureReturnsClosedResource().check(Path("app/fixtures.py"), _BASE) == []


def test_documented_examples() -> None:
    verify_native_rule(PytestFixtureReturnsClosedResource, analyze)
