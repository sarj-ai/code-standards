from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


def _case(case_id: str, source: str) -> EvaluationCase:
    return EvaluationCase(case_id, Language.PYTHON, source, ExpectedOutcome.MATCH, path=PurePosixPath("app/results.py"))


_CASES = (
    _case(
        "round2-scope-01-module-base-local-attribute-write",
        "from types import SimpleNamespace\nimport pydantic as p\n"
        "class Alpha(p.BaseModel):\n    value: str\n"
        "class Beta(p.BaseModel):\n    value: str\n"
        "def touch(p: SimpleNamespace) -> None:\n    p.label = 'ignored'\n"
        "touch(SimpleNamespace())\ntype Result = Alpha | Beta\n",
    ),
    _case(
        "round2-scope-02-literal-module-local-attribute-write",
        "from types import SimpleNamespace\nfrom dataclasses import dataclass\nimport typing as t\n"
        "@dataclass\nclass Alpha:\n    kind: t.Literal['same']\n"
        "@dataclass\nclass Beta:\n    kind: t.Literal['same']\n"
        "def touch(t: SimpleNamespace) -> None:\n    t.label = 'ignored'\n"
        "touch(SimpleNamespace())\ntype Result = Alpha | Beta\n",
    ),
    _case(
        "round2-scope-03-metadata-name-local-attribute-write",
        "from dataclasses import dataclass\nfrom typing import Annotated\n"
        "from pydantic import Field\nfrom pydantic.fields import FieldInfo\n"
        "@dataclass\nclass Alpha:\n    value: str\n"
        "@dataclass\nclass Beta:\n    value: str\n"
        "field = Field(discriminator='kind')\n"
        "def touch(field: FieldInfo) -> None:\n    field.title = 'ignored'\n"
        "touch(Field())\ntype Result = Annotated[Alpha | Beta, field]\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_local_attribute_writes_follow_binding_identity(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ510"
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        _CASES[0].source.replace("touch(SimpleNamespace())", "touch(p)"),
        _CASES[0]
        .source.replace("def touch(p: SimpleNamespace)", "def touch(p: SimpleNamespace = p)")
        .replace("touch(SimpleNamespace())", "touch()"),
        _CASES[0].source.replace("type Result =", "p.BaseModel = replacement\ntype Result ="),
        _CASES[0].source.replace(
            "type Result =", "def replace() -> None:\n    p.BaseModel = replacement\nreplace()\ntype Result ="
        ),
        _CASES[0].source.replace(
            "type Result =", "def replace() -> None:\n    global p\n    p = replacement\nreplace()\ntype Result ="
        ),
        _CASES[0].source.replace("type Result =", "alias = p\ntype Result ="),
        _CASES[0].source.replace("type Result =", "(alias := p)\ntype Result ="),
        _CASES[0].source.replace("type Result =", "with p:\n    pass\ntype Result ="),
        _CASES[2].source.replace("touch(Field())", "touch(field)"),
        _CASES[2]
        .source.replace("def touch(field: FieldInfo)", "def touch(field: FieldInfo = field)")
        .replace("touch(Field())", "touch()"),
        _CASES[2].source.replace("type Result =", "field.discriminator = choose\ntype Result ="),
        _CASES[2].source.replace(
            "type Result =", "def replace() -> None:\n    field.discriminator = choose\nreplace()\ntype Result ="
        ),
    ],
    ids=(
        "module-object-passed-to-helper",
        "module-default-alias",
        "module-attribute-write",
        "module-write-inside-function",
        "module-global-rebinding",
        "module-assignment-alias",
        "module-assignment-expression-alias",
        "module-context-manager-protocol",
        "metadata-object-passed-to-helper",
        "metadata-default-alias",
        "metadata-attribute-write",
        "metadata-write-inside-function",
    ),
)
def test_actual_global_writes_and_object_escapes_still_abstain(source: str) -> None:
    assert PreferDiscriminatedModelUnion().check(Path("app/results.py"), source) == []


def test_scoped_attribute_write_budget_abstains_conservatively() -> None:
    writes = "".join(f"    p.item{index} = 'ignored'\n" for index in range(130))
    source = _CASES[0].source.replace("    p.label = 'ignored'\n", writes)
    assert PreferDiscriminatedModelUnion().check(Path("app/results.py"), source) == []
