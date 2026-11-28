from pathlib import Path
from textwrap import dedent

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_enum_literal_comparison import NoEnumLiteralComparison


_PATH = Path("app.py")
_RULE = NoEnumLiteralComparison.id
_ENUMS = """\
from enum import Enum, IntEnum, StrEnum

class Action(StrEnum):
    IDENTITY = "identity"
    BUILD = "build"

class ExitCode(IntEnum):
    RETRY = -1
    SUCCESS = 0

class Endpoint(Enum):
    AUTHORIZE = "authorize"
"""


def test_documented_examples() -> None:
    verify_native_rule(NoEnumLiteralComparison, analyze)


@pytest.mark.parametrize(
    ("annotation", "comparison", "enum"),
    [
        ("Action", 'action == "identity"', "Action"),
        ("Endpoint", 'action != "authorize"', "Endpoint"),
        ("Action", '"build" == action', "Action"),
        ("Action", 'action not in {"build", "identity"}', "Action"),
        ("Action", 'action in ["build"]', "Action"),
        ("Action", 'action in ("build",)', "Action"),
        ("ExitCode", "action == -1", "ExitCode"),
        ('"Action | None"', 'action.value == "build"', "Action"),
        ("ExitCode", "action.value in (-1, 0)", "ExitCode"),
        ("str", "action == Action.BUILD.value", "Action"),
        ("int", "ExitCode.RETRY.value != action", "ExitCode"),
    ],
)
def test_raw_comparison(annotation: str, comparison: str, enum: str) -> None:
    source = f"{_ENUMS}\ndef check(action: {annotation}):\n    return {comparison}\n"
    [finding] = NoEnumLiteralComparison().check(_PATH, source)
    assert finding.code == NoEnumLiteralComparison.code
    assert finding.severity is Severity.WARNING
    assert f"'{enum}'" in finding.message


def test_literals_in_match_arms_and_local_annotation() -> None:
    source = _ENUMS + dedent("""\

        def check(raw: int):
            code: ExitCode = ExitCode(raw)
            match code:
                case (-1 | ExitCode.SUCCESS) as selected:
                    return selected
                case 0:
                    return code
                case ExitCode.RETRY:
                    return code
    """)
    findings = NoEnumLiteralComparison().check(Path("tests/test_command.py"), source)
    assert [finding.line for finding in findings] == [
        line for line, text in enumerate(source.splitlines(), start=1) if "case (" in text or "case 0:" in text
    ]
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_one_finding_per_chained_comparison() -> None:
    source = _ENUMS + '\ndef check(action: Action):\n    return "build" == action == "identity"\n'
    assert len(NoEnumLiteralComparison().check(_PATH, source)) == 1


def test_project_proves_imported_fields_and_member_values(tmp_path: Path) -> None:
    package = tmp_path / "domain"
    package.mkdir()
    (package / "__init__.py").write_text("from .models import TranscriptRole as TranscriptRole\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "domain"\nversion = "0.0.0"\n')
    (package / "models.py").write_text(
        _ENUMS
        + dedent("""\

            class SortColumn(StrEnum):
                CREATED_AT = "created_at"
                PRIORITY = "priority"

            class ListCrawlQueueRequest:
                sort_by: SortColumn

            class OutputStrategy(StrEnum):
                IN_PLACE = "in_place"

            class TransformResult:
                output_strategy: OutputStrategy

            class TranscriptRole(StrEnum):
                USER = "user"
        """)
    )
    path = package / "consumer.py"
    source = dedent("""\
        from . import models
        from .models import ListCrawlQueueRequest as ListRequest
        from domain import TranscriptRole

        def sort(request: ListRequest):
            return request.sort_by in {"created_at", "priority"}

        class Runner:
            def __init__(self, result: models.TransformResult):
                self._result: models.TransformResult = result

            def finished(self):
                return self._result.output_strategy.value == "in_place"

        def has_caller(turns):
            return any(turn.role == TranscriptRole.USER.value for turn in turns)
    """)
    path.write_text(source)
    findings = analyze([_RULE], [path])
    assert [finding.line for finding in findings] == [
        line for line, text in enumerate(source.splitlines(), start=1) if "return " in text
    ]
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_absolute_import_when_the_distribution_is_also_the_package(tmp_path: Path) -> None:
    package = tmp_path / "domain"
    package.mkdir()
    (tmp_path / ".git").mkdir()
    (package / "__init__.py").touch()
    (package / "pyproject.toml").write_text('[project]\nname = "domain"\nversion = "0.0.0"\n')
    (package / "models.py").write_text(_ENUMS)
    path = package / "consumer.py"
    path.write_text('from domain.models import Action\ndef check(action: Action): return action == "build"\n')

    [finding] = analyze([_RULE], [path])
    assert finding.line == 2


@pytest.mark.parametrize(
    "body",
    [
        "def check(action: Action): return action is Action.BUILD",
        "def check(action: Action): return action == Action.BUILD",
        'from typing import Literal\ndef check(action: Literal["build"]): return action == "build"',
        'def check(action: Action | str): return action == "build"',
        'def check(*action: Action): return action == "build"',
        "def check(code: ExitCode): return code == True",
        'def check(action: Action): return action >= "build"',
        'def check(ts, i): return ts[i].value == "و"',
        'def check(x): return Task.result["mode"].astext == Action.BUILD.value',
        "def check(x): return sql.func.lower(x) == Action.BUILD.value",
        "def check(x): return x == Endpoint.AUTHORIZE.value",
        "def check(x): return x == Action.UNKNOWN.value",
        'def check(): return Action.BUILD.value == "build"',
        'def check(action: Action):\n    action = object()\n    return action == "build"',
        'def check(action: Action):\n    return any(action == "build" for action in values)',
        'class Custom(StrEnum):\n    BUILD = "build"\n    def __eq__(self, other): ...\ndef check(a: Custom): return a == "build"',
        'from dependency import External\ndef check(action: External): return action == "build"',
        'from other import StrEnum as FakeStrEnum\nclass Fake(FakeStrEnum): ...\ndef check(a: Fake): return a == "build"',
    ],
)
def test_proven_boundary(body: str) -> None:
    assert NoEnumLiteralComparison().check(_PATH, f"{_ENUMS}\n{body}\n") == []


def test_suppression_generated_and_malformed_input(tmp_path: Path) -> None:
    source = _ENUMS + '\ndef check(action: Action):\n    return action == "build"\n'
    path = tmp_path / "test_enum.py"
    path.write_text(source.rstrip() + f"  # sarj-noqa: {NoEnumLiteralComparison.code} -- wire contract assertion.\n")
    assert analyze([_RULE], [path]) == []
    assert NoEnumLiteralComparison().check(_PATH, "# Code generated. DO NOT EDIT.\n" + source) == []
    assert NoEnumLiteralComparison().check(_PATH, "def (") == []
