from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rules.named_record_at_boundaries import NamedRecordAtBoundaries
from sarj_python_lint.rules.prefer_nominal_mapping_keys import PreferNominalMappingKeys


def test_documented_examples() -> None:
    verify_native_rule(PreferNominalMappingKeys, analyze)


@pytest.mark.parametrize(
    "declaration",
    [
        "def read(counts: dict[str, int]) -> None: ...",
        "def read() -> dict[str, float]: ...",
        "class Report:\n    timings: dict[str, float]",
        "from collections.abc import Mapping as M\nclass Report:\n    values: M[str, str | float]",
        "from typing import Dict as D\nclass Report:\n    values: D[int, str]",
        "from typing import Optional, Annotated\nclass Report:\n    values: Annotated[Optional[dict[str, int]], 'units']",
        "class Report:\n    batches: list[dict[str, int]]",
        "type Counts = dict[str, int]",
        "from typing import TypeAlias\nCounts: TypeAlias = dict[str, int]",
        "from typing import Mapping\nclass Report:\n    values: Mapping[str, list[int]]",
    ],
)
def test_mapping_boundary_requires_a_domain(declaration: str) -> None:
    findings = PreferNominalMappingKeys().check(Path("app/report.py"), declaration + "\n")
    assert len(findings) == 1
    assert "TypedDict" in findings[0].message
    assert "nominal" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "def run():\n    counts: dict[str, int] = {}\n    return len(counts)\n",
        "def _algorithm(counts: dict[str, int]) -> int:\n    return sum(counts.values())\n",
        "from typing import TypedDict\nclass Timings(TypedDict):\n    total: float\n",
        "from typing import NewType\nStageId = NewType('StageId', str)\nclass Report:\n    values: dict[StageId, float]\n",
        "from enum import StrEnum\nclass Stage(StrEnum):\n    AUDIO = 'audio'\nclass Report:\n    values: dict[Stage, float]\n",
        "from typing import ClassVar\nclass Metadata:\n    values: ClassVar[dict[str, int]] = {}\n",
        "dict = custom_mapping\nclass Report:\n    values: dict[str, int]\n",
        "def read[dict](values: dict[str, int]) -> None: ...\n",
        "from typing import Any\nclass Report:\n    values: dict[str, Any]\n",
        "class Report:\n    values: dict[str, object]\n",
        "class _Accumulator:\n    counts: dict[str, int]\n",
        "class _Accumulator:\n    def record(self, counts: dict[str, int]) -> None: ...\n",
        "class Report:\n    values: dict[str, int]  # sarj-noqa: SARJ568 -- External protocol deliberately accepts arbitrary metric names.\n",
        "invalid python !\n",
    ],
)
def test_open_algorithms_nominal_keys_and_existing_owners(source: str) -> None:
    assert PreferNominalMappingKeys().check(Path("app/report.py"), source) == []


@pytest.mark.parametrize("path", ["tests/test_report.py", "app/generated/report.py", "vendor/report.py"])
def test_excluded_sources(path: str) -> None:
    assert PreferNominalMappingKeys().check(Path(path), "class Report:\n    values: dict[str, int]\n") == []


def test_quoted_and_aliased_boundary_annotations() -> None:
    source = "type Counts = dict[str, int]\ndef read(values: 'Counts') -> None: ...\n"
    findings = PreferNominalMappingKeys().check(Path("app/report.py"), source)
    assert len(findings) == 1


def test_annotated_class_metadata_keeps_its_class_contract() -> None:
    source = (
        "from typing import Annotated, ClassVar\n"
        "class Metadata:\n    values: Annotated[ClassVar[dict[str, int]], 'registry'] = {}\n"
    )
    assert PreferNominalMappingKeys().check(Path("app/report.py"), source) == []


def test_fixed_record_return_owns_overlap_but_parameter_advice_remains() -> None:
    source = (
        "def report(\n    values: dict[str, int],\n) -> dict[str, int]:\n    return {'count': sum(values.values())}\n"
    )
    findings = check_source([NamedRecordAtBoundaries(), PreferNominalMappingKeys()], Path("app/report.py"), source)
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ008", 1), ("SARJ568", 2)]
    assert len(PreferNominalMappingKeys().check(Path("app/report.py"), source)) == 2
