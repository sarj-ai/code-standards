from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_native_string_check import PreferNativeStringCheck
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import RequirePydanticForMappingShape


_RULE_ID = "require-pydantic-for-mapping-shape"
_SOURCE = "def category(value: dict[str, object]):\n    return isinstance(value.get('kind'), str)\n"
_EXTERNAL_SOURCE = (
    "import httpx\n"
    "def category():\n"
    "    value: dict[str, object] = httpx.get('https://example.test').json()\n"
    "    return isinstance(value.get('kind'), str)\n"
)
_NESTED_SOURCE = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "@router.post('/events')\n"
    "def category(body: RequestModel):\n"
    "    value: dict[str, object] = body.payload\n"
    "    return isinstance(value.get('kind'), str)\n"
)


@pytest.mark.parametrize(
    ("source", "path", "count"),
    [
        (_SOURCE, "app/events.py", 1),
        (_SOURCE, "tests/test_events.py", 1),
        ("# @generated\n" + _SOURCE, "app/events.py", 0),
        (_SOURCE, "vendor/events.py", 0),
        (_SOURCE, "third_party/events.py", 0),
        ("def category(value:\n", "app/events.py", 0),
        (_SOURCE.replace("str)", "str)  # sarj-noqa: SARJ521 -- legacy wire protocol"), "app/events.py", 0),
        (_SOURCE.replace("str)", "str)  # sarj-noqa: SARJ447 -- unrelated annotation policy"), "app/events.py", 1),
    ],
    ids=(
        "application",
        "authored-test",
        "generated",
        "vendor",
        "third-party",
        "malformed",
        "exact-suppression",
        "other-suppression",
    ),
)
def test_mapping_shape_boundaries(source: str, path: str, count: int) -> None:
    findings = RequirePydanticForMappingShape().check(Path(path), source)

    assert len(findings) == count
    assert all(finding.code == "SARJ521" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    ("source", "specific_rule", "specific_code"),
    [
        (_EXTERNAL_SOURCE, "require-pydantic-for-external-json", "SARJ411"),
        (_NESTED_SOURCE, "require-pydantic-for-structured-payload", "SARJ450"),
    ],
    ids=("external-json", "nested-fastapi"),
)
def test_specific_boundary_diagnostic_supersedes_shape_warning_only_when_present(
    tmp_path: Path, source: str, specific_rule: str, specific_code: str
) -> None:
    target = tmp_path / "events.py"
    target.write_text(source)

    standalone = analyze([_RULE_ID], [target])
    assert [finding.code for finding in standalone] == ["SARJ521"]

    for selected in ([specific_rule, _RULE_ID], [_RULE_ID, specific_rule]):
        combined = analyze(selected, [target])
        assert [finding.code for finding in combined] == [specific_code]

    target.write_text(source.replace("str)", f"str)  # sarj-noqa: {specific_code} -- legacy boundary"))
    assert [finding.code for finding in analyze([specific_rule, _RULE_ID], [target])] == ["SARJ521"]


def test_shape_suppression_preserves_external_json_error(tmp_path: Path) -> None:
    target = tmp_path / "events.py"
    target.write_text(_EXTERNAL_SOURCE.replace("str)", "str)  # sarj-noqa: SARJ521 -- legacy shape"))

    findings = analyze([_RULE_ID, "require-pydantic-for-external-json"], [target])

    assert [(finding.code, finding.severity) for finding in findings] == [("SARJ411", Severity.ERROR)]


def test_repeated_rule_selection_does_not_duplicate_shape_findings(tmp_path: Path) -> None:
    target = tmp_path / "events.py"
    target.write_text(_SOURCE)

    findings = analyze([_RULE_ID, _RULE_ID], [target])

    assert [(finding.code, finding.line) for finding in findings] == [("SARJ521", 2)]


def test_shape_warning_stays_out_of_blocking_cli_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "events.py"
    target.write_text(_SOURCE)
    baseline = tmp_path / "baseline.json"

    assert main(["check", "--rule", _RULE_ID, str(target)]) == 0
    assert "SARJ521 warning:" in capsys.readouterr().out
    assert main(["check", "--rule", _RULE_ID, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {}


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import BaseModel\nclass Event(BaseModel):\n    kind: str\ndef category(raw: object):\n    event = Event.model_validate(raw)\n    return event.kind == 'ready'\n",
        "from pydantic import TypeAdapter\nfrom typing import TypedDict\nclass Event(TypedDict):\n    kind: str\nADAPTER = TypeAdapter(Event)\ndef category(raw: object):\n    event = ADAPTER.validate_python(raw)\n    return event['kind'] == 'ready'\n",
        "def category(value: str):\n    return isinstance(value, str)\n",
        "def category(value: dict[str, str]):\n    return value.get('kind') == 'ready'\n",
    ],
    ids=("model", "typed-dict-adapter", "scalar-check", "homogeneous-registry"),
)
def test_declarative_parsing_and_precise_native_checks_remain_accepted(source: str) -> None:
    assert RequirePydanticForMappingShape().check(Path("app/events.py"), source) == []
    assert PreferNativeStringCheck().check(Path("app/events.py"), source) == []
