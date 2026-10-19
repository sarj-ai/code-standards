from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_RECORDS = (
    "from dataclasses import dataclass\nfrom typing import ClassVar, Literal, Union\n"
    "@dataclass\nclass Alpha:\n    value: str\n"
    "@dataclass\nclass Beta:\n    value: str\n"
)
_ALIAS = "type Result = Alpha | Beta\n"
_GLOBAL_REBIND = "def adapt() -> None:\n    global dataclass\n    dataclass = lambda cls: cls\nadapt()\n"


def _case(case_id: str, source: str, *, match: bool = False) -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if match else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/results.py"),
    )


_CASES = (
    _case(
        "scope-unrelated-decorator-parameter",
        _RECORDS + _ALIAS + "def helper(dataclass: object) -> object:\n    return dataclass\n",
        match=True,
    ),
    _case(
        "scope-unrelated-union-parameter",
        _RECORDS
        + _ALIAS.replace("Alpha | Beta", "Union[Alpha, Beta]")
        + "def helper(Union: object) -> object:\n    return Union\n",
        match=True,
    ),
    _case(
        "scope-real-global-decorator-rebinding",
        _RECORDS.replace("@dataclass\nclass Alpha:", _GLOBAL_REBIND + "@dataclass\nclass Alpha:") + _ALIAS,
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_union_import_scope(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)
    assert all(finding.code == "SARJ510" for finding in findings)


@pytest.mark.parametrize(
    "annotation",
    ["Literal['same']", "\"Literal['same']\"", "Union[\"Literal['same']\", None]"],
    ids=("direct", "forward-annotation", "nested-forward-annotation"),
)
def test_class_namespace_does_not_borrow_imported_literal(annotation: str) -> None:
    source = (
        _RECORDS.replace(
            "    value: str", f"    Literal: ClassVar[object] = tuple\n    kind: {annotation}\n    value: str"
        )
        + _ALIAS
    )
    assert not PreferDiscriminatedModelUnion().check(Path("app/results.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        _RECORDS.replace("    value: str", "    type: str\n    value: str") + _ALIAS,
        _RECORDS.replace("    value: str", "    kind: Literal['kind']\n    value: str") + _ALIAS,
    ],
    ids=("field-name-without-reference", "literal-value-is-not-a-reference"),
)
def test_class_shadow_guard_keeps_proven_module_annotations(source: str) -> None:
    assert len(PreferDiscriminatedModelUnion().check(Path("app/results.py"), source)) == 1


@pytest.mark.parametrize(
    "declaration",
    ["Alpha", "Scope"],
    ids=("variant", "tag-alias"),
)
def test_global_rebinding_prevents_static_variant_or_tag_proof(declaration: str) -> None:
    source = (
        "type Scope = str\n"
        + _RECORDS.replace("    value: str", "    scope: Scope\n    value: str")
        + f"def adapt() -> None:\n    global {declaration}\n    {declaration} = object\n"
        + "adapt()\n"
        + _ALIAS
    )
    assert not PreferDiscriminatedModelUnion().check(Path("app/results.py"), source)
