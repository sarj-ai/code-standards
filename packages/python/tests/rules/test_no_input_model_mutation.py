from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.no_input_model_mutation import NoInputModelMutation


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic

_MODELS = (
    "from pydantic import BaseModel\n"
    "from collections.abc import Sequence\n"
    "class Attachment(BaseModel):\n    url: str\n"
    "class Record(BaseModel):\n    name: str\n    attachment: Attachment\n    tags: list[str]\n"
)
_BAD = {
    "direct-field": "def update(record: Record):\n    record.name = 'new'\n",
    "stable-alias": "def update(record: Record):\n    alias = record\n    alias.name = 'new'\n",
    "loop-element": "def update(records: Sequence[Record]):\n    for record in records:\n        record.name = 'new'\n",
    "indexed-element": "def update(records: list[Record]):\n    records[0].name = 'new'\n",
    "copied-list-elements": "def update(records: list[Record]):\n    copied = list(records)\n    for record in copied:\n        record.name = 'new'\n",
    "sliced-list-elements": "def update(records: list[Record]):\n    copied = records[:]\n    copied[0].name = 'new'\n",
    "shallow-model-child": "def update(record: Record):\n    copied = record.model_copy()\n    copied.attachment.url = 'new'\n",
    "borrowed-list-mutator": "def update(record: Record):\n    record.tags.append('new')\n",
    "augmented-field": "def update(record: Record):\n    record.name += 'new'\n",
    "nested-alias": "def update(record: Record):\n    attachment = record.attachment\n    attachment.url = 'new'\n",
}
_BAD.update(
    {
        "shallow-child-augmented": "def update(record: Record):\n    copied = record.model_copy()\n    copied.tags += ['new']\n",
        "inherited-fields": "class Child(Record): pass\ndef update(record: Child):\n    record.name = 'new'\n",
        "quoted-annotation": "def update(record: 'Record'):\n    record.name = 'new'\n",
        "model-collection-type-alias": "type Records = Sequence[Record]\ndef update(records: Records):\n    for record in records:\n        record.name = 'new'\n",
        "literal-borrowed-model": "def update(record: Record):\n    records = [record]\n    records[0].name = 'new'\n",
        "literal-owned-model-shared-child": "def update(record: Record):\n    records = [record.model_copy()]\n    records[0].attachment.url = 'new'\n",
    }
)
_GOOD = {
    "returned-replacement": "def update(record: Record):\n    return record.model_copy(update={'name': 'new'})\n",
    "fresh-model": "def update(record: Record):\n    record = Record(name='new', attachment=Attachment(url='new'), tags=[])\n    record.name = 'updated'\n",
    "copied-outer-field": "def update(record: Record):\n    copied = record.model_copy()\n    copied.name = 'new'\n",
    "copied-child-replacement": "def update(record: Record):\n    attachment = record.attachment.model_copy()\n    copied = record.model_copy(update={'attachment': attachment})\n    copied.attachment.url = 'new'\n",
    "copied-list-container": "def update(records: list[Record]):\n    copied = list(records)\n    copied.clear()\n",
    "unknown-receiver": "def update(record):\n    record.name = 'new'\n",
    "branch-rebinding": "def update(record: Record, flag: bool):\n    if flag:\n        record = unknown()\n    record.name = 'new'\n",
    "fresh-branch": "def update(record: Record, flag: bool):\n    if flag:\n        record = Record(name='new', attachment=Attachment(url='new'), tags=[])\n        record.name = 'updated'\n",
    "closure-shadowing": "def update(record: Record):\n    def inner(record):\n        record.name = 'new'\n",
    "custom-model-copy": "class Custom(Record):\n    def model_copy(self):\n        return unknown()\ndef update(record: Custom):\n    copied = record.model_copy()\n    copied.name = 'new'\n",
    "shadowed-model-name": "def update(record: Record, Record):\n    record.name = 'new'\n",
}
_GOOD.update(
    {
        "fresh-child-assignment": "def update(record: Record):\n    copied = record.model_copy()\n    copied.attachment = Attachment(url='new')\n    copied.attachment.url = 'updated'\n",
        "fresh-child-through-owned-alias": "def update(record: Record):\n    copied = record.model_copy()\n    alias = copied\n    alias.attachment = Attachment(url='new')\n    copied.attachment.url = 'updated'\n",
        "different-shallow-copies": "def update(record: Record):\n    first = record.model_copy()\n    second = record.model_copy()\n    first.attachment = Attachment(url='new')\n    first.attachment.url = 'updated'\n",
        "fresh-list-field": "def update(record: Record):\n    copied = record.model_copy()\n    copied.tags = []\n    copied.tags.append('new')\n",
        "unknown-model-method": "def update(record: Record):\n    record.attachment.set('url', 'new')\n",
        "closure-capture": "def update(record: Record):\n    def inner():\n        record.name = 'new'\n",
        "readonly-interface-custom-method": "def update(records: Sequence[Record]):\n    records.append(unknown())\n",
        "matched-rebinding": "def update(record: Record, value):\n    match value:\n        case {'record': record}:\n            record.tags.append('new')\n",
    }
)
_GOOD.update(
    {
        "shadowed-pydantic-base": "BaseModel = object\nclass Other(BaseModel):\n    name: str\ndef update(record: Other):\n    record.name = 'new'\n",
        "heterogeneous-tuple": "def update(records: tuple[Record, object]):\n    records[1].name = 'new'\n",
        "literal-owned-model-root": "def update(record: Record):\n    records = [record.model_copy()]\n    records[0].name = 'new'\n",
        "literal-mixed-ownership": "def update(record: Record):\n    records = [Attachment(url='new'), record.attachment]\n    records[0].url = 'new'\n",
    }
)
_CASES = (
    *(EvaluationCase(key, Language.PYTHON, _MODELS + source, ExpectedOutcome.MATCH) for key, source in _BAD.items()),
    *(EvaluationCase(key, Language.PYTHON, _MODELS + source) for key, source in _GOOD.items()),
    EvaluationCase(
        "not-a-pydantic-model",
        Language.PYTHON,
        "class BaseModel: pass\nclass Record(BaseModel):\n    name: str\ndef update(record: Record):\n    record.name = 'new'\n",
    ),
    EvaluationCase(
        "class-variable",
        Language.PYTHON,
        "from pydantic import BaseModel\nfrom typing import ClassVar\nclass Record(BaseModel):\n    cache: ClassVar[list[str]] = []\ndef update(record: Record):\n    record.cache.append('new')\n",
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "def update(:\n"),
    EvaluationCase(
        "recursive-container-alias",
        Language.PYTHON,
        "type Tree = list['Tree']\ndef update(tree: Tree):\n    tree.clear()\n",
    ),
)


def _check(source: str, path: Path = Path("app/records.py")) -> list[Diagnostic]:
    rule = NoInputModelMutation()
    rule.prepare(ProjectIndexSet.single(path, source))
    return rule.check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_ownership_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert all(finding.code == "SARJ481" for finding in findings)


def test_documented_examples() -> None:
    verify_native_rule(NoInputModelMutation, analyze)


@pytest.mark.parametrize("path", [Path("app/records.py"), Path("tests/test_records.py")], ids=["production", "tests"])
def test_reports_precise_locations_in_maintained_sources(path: Path) -> None:
    source = _MODELS + _BAD["direct-field"]
    [finding] = _check(source, path)
    assert (finding.line, finding.col) == (len(source.splitlines()), 5)


def test_generated_code_is_excluded() -> None:
    assert _check(_MODELS + _BAD["direct-field"], Path("generated/records.py")) == []


def test_exact_suppression() -> None:
    source = (
        _MODELS
        + "def update(record: Record):\n    record.name = 'new'  # sarj-noqa: SARJ481 — explicitly in-place API\n"
    )
    assert _check(source) == []


def test_resolves_imported_model_without_executing_application_code(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.1.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    models = package / "models.py"
    models.write_text("raise RuntimeError('must not import')\n" + _MODELS)
    target = package / "service.py"
    source = "from app.models import Record as Item\ndef update(item: Item):\n    item.name = 'new'\n"
    target.write_text(source)
    rule = NoInputModelMutation()
    rule.prepare(ProjectIndexSet.build([target, models], {target: source, models: models.read_text()}))
    [finding] = rule.check(target, source)
    assert (finding.code, finding.line) == ("SARJ481", 3)
