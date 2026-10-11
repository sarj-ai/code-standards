from __future__ import annotations

from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.rules.no_conftest_test_module_import import NoConftestTestModuleImport


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "tests/conftest.py"):
    return NoConftestTestModuleImport().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = NoConftestTestModuleImport.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoConftestTestModuleImport().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "from tests.test_api import make_client",
        "from .test_api import make_client",
        "import tests.integration.test_api as api_tests",
        "from tests.api_test import make_client",
        "from tests import test_api",
        "from . import test_api",
        "from app.tests import api_test",
        "def fixture():\n    from tests.test_api import make_client",
    ],
)
def test_reports_imports_from_test_modules(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ426"


@pytest.mark.parametrize(
    "source",
    [
        "from tests.helpers import make_client",
        "from .support import make_client",
        "import test.support",
        "from app.testing import fake_client",
        "from app.testing import test_client",
        "from tests.helpers import test_client",
        "from pytest import test_api",
    ],
)
def test_allows_dedicated_support_modules(source: str) -> None:
    assert _check(source) == []


def test_ignores_imports_outside_conftest() -> None:
    assert _check("from tests.test_api import make_client", "tests/test_other.py") == []


@pytest.mark.parametrize(
    "source",
    [
        'pytest_plugins = "tests.test_api"',
        'pytest_plugins = ("tests.fixtures", "tests.integration.api_test")',
        'pytest_plugins: tuple[str, ...] = [".test_database"]',
    ],
)
def test_reports_test_modules_registered_as_pytest_plugins(source: str) -> None:
    [finding] = _check(source)
    assert finding.code == "SARJ426"
    assert "pytest plugin" in finding.message


def test_allows_dedicated_support_modules_registered_as_pytest_plugins() -> None:
    assert _check('pytest_plugins = ("tests.fixtures.database", "tests.support.api")') == []


_PLUGIN_PROBLEM = RuleProblem(
    key="literal-pytest-plugin-assignment-targets",
    summary="Chained literal pytest_plugins assignments still register individual test modules.",
    harm="Test-module plugin imports create the same collection cycles and ordering coupling as direct imports.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=('pytest_plugins = shared = ("tests.test_api",)\n',),
    good_examples=('pytest_plugins = shared = ("tests.support.api",)\n',),
    exclusions=("Dynamic values and targets that do not directly bind pytest_plugins remain excluded.",),
)
_PLUGIN_CASES = tuple(
    EvaluationCase(label, Language.PYTHON, source, expected, PurePosixPath("tests/conftest.py"))
    for label, source, expected in (
        ("plugin-first", 'pytest_plugins = shared = ("tests.test_api",)\n', ExpectedOutcome.MATCH),
        ("plugin-last", 'shared = pytest_plugins = ["tests.test_api"]\n', ExpectedOutcome.MATCH),
        ("repeated-target", 'pytest_plugins = pytest_plugins = "tests.test_api"\n', ExpectedOutcome.MATCH),
        ("support-module", 'shared = pytest_plugins = ("tests.support.api",)\n', ExpectedOutcome.NO_MATCH),
        ("dynamic-value", "pytest_plugins = shared = plugin_names\n", ExpectedOutcome.NO_MATCH),
        ("attribute-target", 'config.pytest_plugins = shared = "tests.test_api"\n', ExpectedOutcome.NO_MATCH),
        ("destructuring-target", '(pytest_plugins, other) = ("tests.test_api", None)\n', ExpectedOutcome.NO_MATCH),
        (
            "function-local",
            'def configure():\n    pytest_plugins = shared = "tests.test_api"\n',
            ExpectedOutcome.NO_MATCH,
        ),
    )
)


@pytest.mark.parametrize("case", _PLUGIN_CASES, ids=tuple(case.case_id for case in _PLUGIN_CASES))
def test_labeled_plugin_assignment_cases(case: EvaluationCase) -> None:
    assert case.language in _PLUGIN_PROBLEM.languages
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.code == "SARJ426" for finding in findings)
