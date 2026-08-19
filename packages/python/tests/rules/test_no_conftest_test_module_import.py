from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

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
        "from tests import test_api",
        "from . import test_api",
    ],
)
def test_allows_dedicated_support_modules(source: str) -> None:
    assert _check(source) == []


def test_ignores_imports_outside_conftest() -> None:
    assert _check("from tests.test_api import make_client", "tests/test_other.py") == []
