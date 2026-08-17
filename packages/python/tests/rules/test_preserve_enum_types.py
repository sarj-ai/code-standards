from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.preserve_enum_types import PreserveEnumTypes


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/__init__.py"):
    return PreserveEnumTypes().check(Path(path), source)


def test_flags_local_matched_enum_erasure() -> None:
    source = """
from enum import StrEnum
class CallStatus(StrEnum):
    QUEUED = "queued"
class NotPending:
    status: CallStatus | None
def render(result):
    match result:
        case NotPending():
            return str(result.status) if result.status else None
"""
    assert len(_check(source)) == 1


def test_cross_module_index_reproduces_imported_result_shape(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "status.py").write_text(
        'from enum import StrEnum\nclass CallStatus(StrEnum):\n    QUEUED = "queued"\n', encoding="utf-8"
    )
    namespace = package / "services"
    namespace.mkdir()
    (namespace / "results.py").write_text(
        "from app.status import CallStatus\nclass ScheduledCallNotPending:\n    status: CallStatus | None\n",
        encoding="utf-8",
    )
    router = package / "router.py"
    router.write_text(
        "from app.services.results import ScheduledCallNotPending\ndef render(result):\n    match result:\n        case ScheduledCallNotPending():\n            return str(result.status) if result.status else None\n",
        encoding="utf-8",
    )
    findings = analyze(["preserve-enum-types"], [router])
    assert len(findings) == 1


def test_ignores_plain_string_and_preserved_enum() -> None:
    source = """
class Result:
    status: str | None
def render(result):
    match result:
        case Result():
            return str(result.status)
"""
    assert _check(source) == []


@pytest.mark.parametrize("example", PreserveEnumTypes.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
