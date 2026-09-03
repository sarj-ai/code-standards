from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.fakes_in_shared_location import FakesInSharedLocation


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "tests/test_checkout.py"):
    return FakesInSharedLocation().check(Path(path), dedent(source))


@pytest.mark.parametrize("example", FakesInSharedLocation.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "name", ["FakeClock", "StubGateway", "MockMailer", "InMemoryStore", "RecordingClient", "ScriptedClient"]
)
def test_reports_explicit_top_level_doubles(name: str) -> None:
    findings = _check(f"class {name}:\n    pass\n")
    assert len(findings) == 1
    assert findings[0].code == "SARJ428"
    assert findings[0].severity is Severity.WARNING
    assert "may need shared ownership" in findings[0].message


@pytest.mark.parametrize(
    "path",
    [
        "tests/fakes/clock.py",
        "tests/testing/clock.py",
        "tests/helpers.py",
        "tests/support/clock.py",
        "tests/test_utils.py",
        "tests/conftest.py",
    ],
)
def test_allows_shared_support_locations(path: str) -> None:
    assert _check("class FakeClock:\n    pass\n", path) == []


def test_ignores_production_classes_nested_doubles_and_descriptive_names() -> None:
    assert _check("class FakeClock:\n    pass\n", "app/clock.py") == []
    assert _check("def test_clock():\n    class FakeClock:\n        pass\n") == []
    assert _check("class PaymentGatewayFakeFactory:\n    pass\n") == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/analytics_data.py",
        "examples/test_checkout.py",
        "benchmarks/test_checkout.py",
        "vendor/tests/test_checkout.py",
    ],
)
def test_non_collected_support_and_non_infrastructure_roots_are_exempt(path: str) -> None:
    assert _check("class FakeClock:\n    pass\n", path) == []


def test_support_ancestor_outside_test_root_does_not_hide_a_collected_test_module() -> None:
    assert len(_check("class FakeClock:\n    pass\n", "support/tests/test_checkout.py")) == 1
