from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_hasattr import NoHasattr


def _lines(source: str, path: str = "service/agent.py") -> list[int]:
    return [finding.line for finding in NoHasattr().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoHasattr, analyze)


def test_reports_each_hasattr_call() -> None:
    source = "def ready(buffer):\n    return hasattr(buffer, 'rate') and hasattr(buffer, 'samples')\n"
    assert _lines(source) == [2, 2]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import os\n\nPG = hasattr(os, 'killpg')\n", id="stdlib-module-probe"),
        pytest.param(
            "import logging\n\nif not hasattr(logging.Logger, 'trace'):\n    pass\n", id="module-attribute-chain"
        ),
        pytest.param(
            "import torch.nn.functional as F\n\nOK = hasattr(F, 'scaled_dot_product_attention')\n", id="aliased-module"
        ),
        pytest.param("def is_dc(cls):\n    return hasattr(cls, '__dataclass_fields__')\n", id="dunder-protocol-probe"),
    ],
)
def test_allows_runtime_feature_detection(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def hasattr(value, name):\n    return True\n\nhasattr(object(), 'x')\n", id="shadowed-builtin"),
        pytest.param("from compat import hasattr\n\nhasattr(object(), 'x')\n", id="imported-name"),
        pytest.param("value = getattr(settings, 'model', None)\n", id="getattr"),
        pytest.param("checker.hasattr(value, 'x')\n", id="method-named-hasattr"),
        pytest.param("hasattr(\n", id="syntax-error"),
    ],
)
def test_allows_non_builtin_or_other_calls(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("tests/test_agent.py", id="test-module"),
        pytest.param("service/conftest.py", id="conftest"),
        pytest.param("tests/fakes/fake_agent.py", id="test-support"),
    ],
)
def test_skips_test_code(path: str) -> None:
    assert _lines("hasattr(value, 'x')\n", path=path) == []
