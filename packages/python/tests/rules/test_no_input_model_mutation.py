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
_CONTAINED_MODELS = (
    "from pydantic import BaseModel\n\n\n"
    "class Attachment(BaseModel):\n    values: list[str]\n\n\n"
    "class Record(BaseModel):\n    attachment: Attachment\n\n\n"
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


@pytest.mark.parametrize("view", ["parent", "element", "direct"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_owned_child_replacement_updates_contained_aliases(view: str, *, borrowed: bool) -> None:
    copy = "record.attachment.model_copy(update={'values': []})" if borrowed else "record.attachment.model_copy()"
    replacement = "record.attachment.values" if borrowed else "[]"
    container = "parents = [child]" if view == "element" else "parent = record.model_copy(update={'attachment': child})"
    receiver = {"parent": "parent.attachment", "element": "parents[0]", "direct": "child"}[view]
    returned = "record.model_copy(update={'attachment': parents[0]})" if view == "element" else "parent"
    source = (
        _CONTAINED_MODELS
        + "def transform(record: Record) -> Record:\n"
        + f"    child = {copy}\n    {container}\n    child.values = {replacement}\n"
        + f"    {receiver}.values.append('changed')\n    return {returned}\n"
    )

    findings = _check(source)

    assert [(finding.code, finding.line, finding.col, finding.severity.value) for finding in findings] == (
        [("SARJ481", 16, 5, "error")] if borrowed else []
    )


@pytest.mark.parametrize(
    ("body", "expected_line"),
    [
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    parent = record.model_copy(update={'attachment': second})\n"
            "    first.values = record.attachment.values\n"
            "    parent.attachment.values.append('safe')\n    return parent\n",
            None,
            id="distinct-equal-copies",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    parents = [first, second]\n    first.values = record.attachment.values\n"
            "    parents[1].values.append('safe')\n"
            "    return record.model_copy(update={'attachment': parents[1]})\n",
            None,
            id="distinct-equal-elements",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    child = record.attachment.model_copy(update={'values': []})\n"
            "    parents = [child, child]\n    child.values = record.attachment.values\n"
            "    parents[1].values.append('unsafe')\n"
            "    return record.model_copy(update={'attachment': parents[1]})\n",
            16,
            id="repeated-exact-alias",
        ),
        pytest.param(
            "def transform(record: Record, flag: bool) -> Record:\n"
            "    child = record.attachment.model_copy(update={'values': []})\n"
            "    parent = record.model_copy(update={'attachment': child})\n"
            "    if flag:\n        child.values = record.attachment.values\n"
            "    parent.attachment.values.append('conditional')\n    return parent\n",
            None,
            id="branch-local-facts",
        ),
        pytest.param(
            "def transform(record: Record, other: Record) -> Record:\n"
            "    parents = [record, other]\n"
            "    local = record.attachment.model_copy(update={'values': []})\n    local.values = []\n"
            "    parents[1].attachment.values.append('unsafe')\n    return record\n",
            16,
            id="unaffected-borrowed-summary",
        ),
        pytest.param(
            "def transform(record: Record, flag: bool) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    holder = {'nested': first}\n"
            "    if flag:\n        child = first\n    else:\n        child = second\n"
            "    child.values = record.attachment.values\n"
            "    holder['nested'].values.append('conditional')\n    return record\n",
            None,
            id="equal-branch-values-are-not-first-branch-aliases",
        ),
        pytest.param(
            "def transform(record: Record, flag: bool) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    holder = {'nested': first}\n"
            "    if flag:\n        child = first\n    else:\n        child = second\n"
            "    child.values = record.attachment.values\n"
            "    child.values.append('unsafe')\n"
            "    holder['nested'].values.append('conditional')\n    return record\n",
            21,
            id="joined-owner-keeps-explicit-new-borrowed-field",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.model_copy()\n    second = record.model_copy()\n"
            "    parents = [first, second]\n"
            "    parents[0].attachment.values.append('unsafe')\n    return record\n",
            16,
            id="owned-summary-shares-descendants",
        ),
        pytest.param(
            "def transform(record: Record, flag: bool) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    if flag:\n        child = first\n        alias = first\n"
            "    else:\n        child = second\n        alias = second\n"
            "    child.values = record.attachment.values\n"
            "    alias.values.append('unsafe')\n    return record\n",
            22,
            id="joined-stable-aliases-share-exact-reference-alternatives",
        ),
        pytest.param(
            "def transform(record: Record, flag: bool) -> Record:\n"
            "    child = record.attachment.model_copy(update={'values': []})\n"
            "    parent = record.model_copy(update={'attachment': child})\n"
            "    if flag:\n        alias = child\n    else:\n        alias = child\n"
            "    alias.values = record.attachment.values\n"
            "    parent.attachment.values.append('unsafe')\n    return parent\n",
            20,
            id="same-reference-branches-stay-exact",
        ),
        pytest.param(
            "def transform(record: Record, other: Record, flag: bool) -> Record:\n"
            "    if flag:\n        chosen = record\n    else:\n        chosen = other\n"
            "    chosen.attachment.values.append('unsafe')\n    return record\n",
            17,
            id="known-borrowed-branch-alternatives",
        ),
        pytest.param(
            "def transform(record: Record, other: Record, flag: bool) -> Record:\n"
            "    if flag:\n        parents = [record, other]\n"
            "    else:\n        parents = [record, other]\n"
            "    parents[0].attachment.values.append('unsafe')\n    return record\n",
            17,
            id="equivalent-borrowed-summaries-survive-join",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    parents = [first, second]\n    chosen = parents[0]\n    other = parents[1]\n"
            "    chosen.values = record.attachment.values\n"
            "    other.values.append('safe')\n    return record\n",
            None,
            id="separate-abstract-lookups",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    parents = [first, second]\n    chosen = parents[0]\n    alias = chosen\n"
            "    chosen.values = record.attachment.values\n"
            "    alias.values.append('unsafe')\n    return record\n",
            19,
            id="stable-alias-from-one-abstract-lookup",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    first = record.attachment.model_copy(update={'values': []})\n"
            "    second = record.attachment.model_copy(update={'values': []})\n"
            "    parents = [first, second]\n    copied = parents[0].model_copy()\n"
            "    copied.values = record.attachment.values\n"
            "    parents[1].values.append('safe')\n    return record\n",
            None,
            id="abstract-member-copy-has-fresh-owner",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    child = record.attachment.model_copy(update={'values': []})\n"
            "    parent = record.model_copy(update={'attachment': child})\n"
            "    child = record.attachment.model_copy(update={'values': []})\n"
            "    child.values = record.attachment.values\n"
            "    parent.attachment.values.append('safe')\n    return parent\n",
            None,
            id="rebound-child-does-not-change-old-parent",
        ),
        pytest.param(
            "def transform(record: Record) -> Record:\n"
            "    child = record.attachment.model_copy(deep=True)\n    parents = [child]\n"
            "    child.values = record.attachment.values\n"
            "    parents[0].values.append('unknown')\n    return record\n",
            None,
            id="deep-copy-provenance-remains-unknown",
        ),
    ],
)
def test_containment_repair_preserves_identity_summary_and_scope_boundaries(
    body: str, expected_line: int | None
) -> None:
    findings = _check(_CONTAINED_MODELS + body)

    assert [(finding.code, finding.line, finding.col) for finding in findings] == (
        [] if expected_line is None else [("SARJ481", expected_line, 5)]
    )


@pytest.mark.parametrize("conditional", [False, True])
def test_owned_parent_replacement_and_join_are_iterative_on_a_bounded_long_chain(*, conditional: bool) -> None:
    levels = 1_100
    replacement = "    child.values = record.attachment.values\n"
    if conditional:
        replacement = "    if flag:\n    " + replacement
    body = [
        "def transform(record: Record, flag: bool) -> Record:\n",
        "    child = record.attachment.model_copy(update={'values': []})\n",
        "    holder_0 = {'next': child}\n",
        *(f"    holder_{index} = {{'next': holder_{index - 1}}}\n" for index in range(1, levels)),
        replacement,
        f"    cursor = holder_{levels - 1}\n",
        *("    cursor = cursor['next']\n" for _ in range(levels)),
        "    cursor.values.append('unsafe')\n",
        "    return record\n",
    ]
    source = _CONTAINED_MODELS + "".join(body)
    assert len(source) < 128_000

    findings = _check(source)

    assert [(finding.code, finding.line, finding.col) for finding in findings] == (
        [] if conditional else [("SARJ481", 2 * levels + 16, 5)]
    )


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
