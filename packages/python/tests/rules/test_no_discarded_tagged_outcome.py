from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_discarded_tagged_outcome import NoDiscardedTaggedOutcome


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


P = Path("app/outcomes.py")
_BASE = """from typing import Literal
from pydantic import BaseModel
class Accepted(BaseModel):
    kind: Literal['accepted']
    value: str
class Rejected(BaseModel):
    kind: Literal['rejected']
    reason: str
type Outcome = Accepted | Rejected
def check(value: str) -> Outcome:
    return Accepted(kind='accepted', value=value)
"""


def _check(source: str) -> list[Diagnostic]:
    return NoDiscardedTaggedOutcome().check(P, source)


def test_documented_examples() -> None:
    verify_native_rule(NoDiscardedTaggedOutcome, analyze)


@pytest.mark.parametrize(
    "call",
    [
        "check('value')",
        "_ = check('value')",
        "_: Outcome = check('value')",
        "def save():\n    check('value')",
        "if ready:\n    check('value')",
    ],
)
def test_discarded_closed_outcome(call: str) -> None:
    findings = _check(_BASE + call + "\n")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].code == "SARJ548"


@pytest.mark.parametrize(
    "call",
    [
        "result = check('value')",
        "result = _ = check('value')",
        "def save():\n    return check('value')",
        "consume(check('value'))",
        "if check('value'):\n    use()",
        "for result in check('value'):\n    consume(result)",
        "assert check('value')",
        "def save(check):\n    check('value')",
        "class Namespace:\n    check('value')",
        "def save(receiver):\n    receiver.check('value')",
    ],
)
def test_consumed_or_unproven_call_is_preserved(call: str) -> None:
    assert _check(_BASE + call + "\n") == []


def test_awaited_async_outcome() -> None:
    source = _BASE.replace("def check(value", "async def check(value")
    assert len(_check(source + "async def save():\n    await check('value')\n")) == 1
    assert _check(source + "async def save():\n    check('value')\n") == []
    assert _check(source + "async def save():\n    result = await check('value')\n") == []
    assert len(_check(source + "async def save():\n    _ = await check('value')\n")) == 1
    assert len(_check(source + "async def save():\n    _: Outcome = await check('value')\n")) == 1


@pytest.mark.parametrize(
    "annotation",
    [
        "'Outcome'",
        "Accepted | Rejected",
        "Union[Accepted, Rejected]",
        "Annotated[Outcome, 'outcome']",
    ],
)
def test_supported_return_annotations(annotation: str) -> None:
    source = "from typing import Annotated, Union\n" + _BASE.replace("-> Outcome", f"-> {annotation}")
    assert len(_check(source + "check('value')\n")) == 1


@pytest.mark.parametrize("annotation", ["Outcome | None", "Accepted | str", "list[Outcome]", "Accepted", "object"])
def test_non_closed_record_union_is_preserved(annotation: str) -> None:
    assert _check(_BASE.replace("-> Outcome", f"-> {annotation}") + "check('value')\n") == []


@pytest.mark.parametrize(
    "change",
    [
        ("Literal['rejected']", "Literal['accepted']"),
        ("kind: Literal['rejected']", "other: Literal['rejected']"),
        ("kind: Literal['rejected']", "kind: str"),
        ("kind: Literal['rejected']", "kind: Literal[1]"),
        ("class Accepted(BaseModel):", "@rewrites_fields\nclass Accepted(BaseModel):"),
        ("class Accepted(BaseModel):", "class Accepted(UnknownBase):"),
        ("def check(value", "@rewrites_result\ndef check(value"),
        ("type Outcome = Accepted | Rejected", "type Outcome = Accepted | Accepted"),
        ("type Outcome = Accepted | Rejected", "type Outcome = Other\nOther = Outcome"),
    ],
    ids=(
        "overlap",
        "different-fields",
        "open-tag",
        "non-string-tag",
        "decorated-record",
        "unknown-base",
        "decorated-callable",
        "single-variant",
        "uncertain-alias",
    ),
)
def test_near_miss_contracts(change: tuple[str, str]) -> None:
    assert _check(_BASE.replace(*change) + "check('value')\n") == []


@pytest.mark.parametrize(
    "mutation",
    [
        "check = command",
        "check.__annotations__ = {}",
        "Accepted.kind = str",
        "Rejected = Other",
        "from opaque import *",
        "def reset():\n    global check\n    check = command",
    ],
)
def test_mutation_invalidates_contract(mutation: str) -> None:
    assert _check(_BASE + mutation + "\ncheck('value')\n") == []


def test_two_independent_outcomes_have_original_locations() -> None:
    source = _BASE + "check('one')\ncheck('two')\n"
    findings = _check(source)
    assert [(item.line, item.col) for item in findings] == [(12, 1), (13, 1)]


def test_exact_suppression_and_generated_source() -> None:
    assert _check(_BASE + "check('value')  # sarj-noqa: SARJ548 -- intentionally observe side effects only\n") == []
    assert NoDiscardedTaggedOutcome().check(Path("generated/outcomes.py"), _BASE + "check('value')\n") == []


def test_dataclass_variants() -> None:
    source = _BASE.replace("from pydantic import BaseModel", "from dataclasses import dataclass")
    source = source.replace("class Accepted(BaseModel):", "@dataclass(frozen=True)\nclass Accepted:")
    source = source.replace("class Rejected(BaseModel):", "@dataclass(frozen=True)\nclass Rejected:")
    assert len(_check(source + "check('value')\n")) == 1


def test_required_typeddict_variants() -> None:
    source = _BASE.replace("from pydantic import BaseModel", "from typing import TypedDict as BaseModel")
    assert len(_check(source + "check('value')\n")) == 1
    assert (
        _check(
            source.replace("class Rejected(BaseModel):", "class Rejected(BaseModel, total=False):") + "check('value')\n"
        )
        == []
    )


def test_distinct_names_do_not_define_outcome_policy() -> None:
    source = _BASE.replace("Accepted", "Left").replace("Rejected", "Right").replace("Outcome", "Choice")
    assert len(_check(source + "check('value')\n")) == 1


def test_imported_function_and_type_aliases(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='outcomes'\nversion='0.0.0'\n")
    provider = package / "models.py"
    provider.write_text(_BASE)
    consumer = package / "consumer.py"
    consumer.write_text("from app.models import check as inspect_value\ninspect_value('value')\n")
    findings = analyze([NoDiscardedTaggedOutcome.id], [provider, consumer])
    assert [(item.path, item.line) for item in findings] == [(consumer, 2)]


def test_malformed_source_abstains() -> None:
    assert _check("def check(:") == []


def test_bounded_alias_and_union_expansion() -> None:
    aliases = "".join(f"type Deep{index} = Deep{index + 1}\n" for index in range(30))
    source = _BASE + aliases + "type Deep30 = Outcome\n"
    source = source.replace("-> Outcome", "-> Deep0")
    assert _check(source + "check('value')\n") == []
    union = " | ".join(["Accepted"] * 300 + ["Rejected"])
    source = _BASE.replace("-> Outcome", "-> " + union)
    assert _check(source + "check('value')\n") == []


def test_dynamic_dataclass_decorator_abstains() -> None:
    source = _BASE.replace("from pydantic import BaseModel", "from dataclasses import dataclass")
    source = source.replace("class Accepted(BaseModel):", "@dataclass(rewrite())\nclass Accepted:")
    source = source.replace("class Rejected(BaseModel):", "@dataclass\nclass Rejected:")
    assert _check(source + "check('value')\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "import typing\n"
        + _BASE.replace("class Accepted", "typing.Literal = list\nclass Accepted").replace(
            "kind: Literal[", "kind: typing.Literal["
        ),
        _BASE.replace("from pydantic import BaseModel", "import pydantic\npydantic.BaseModel = Other").replace(
            "(BaseModel)", "(pydantic.BaseModel)"
        ),
        "from typing import ClassVar\n"
        + _BASE.replace(
            "class Accepted(BaseModel):",
            "class Accepted(BaseModel):\n    Literal: ClassVar[type] = list",
        ),
        "from typing import ClassVar\n"
        + _BASE.replace(
            "class Accepted(BaseModel):",
            "type Tag = Literal['accepted']\nclass Accepted(BaseModel):\n    Tag: ClassVar[type] = str",
        ).replace("kind: Literal['accepted']", "kind: Tag"),
    ],
    ids=("typing-namespace-write", "pydantic-base-write", "class-literal-shadow", "class-alias-shadow"),
)
def test_native_and_class_annotation_identity_is_required(source: str) -> None:
    assert _check(f"{source}check('value')\n") == []


@pytest.mark.parametrize(
    ("declaration", "mutation", "annotation", "implementation"),
    [
        (
            "from app.models import Accepted, Rejected, check as produce\n",
            "Accepted = Other\n",
            "Accepted | Rejected",
            "produce(value)",
        ),
        (
            "from app.models import Outcome, check as produce\n",
            "Outcome = Other\n",
            "Outcome",
            "produce(value)",
        ),
        (
            "import app.models as models\n",
            "models.Outcome = Other\n",
            "models.Outcome",
            "models.check(value)",
        ),
    ],
    ids=("imported-record-rebound", "imported-alias-rebound", "qualified-alias-mutated"),
)
def test_imported_annotation_identity_is_required(
    tmp_path: Path, declaration: str, mutation: str, annotation: str, implementation: str
) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='outcomes'\nversion='0.0.0'\n")
    provider = package / "models.py"
    provider.write_text(_BASE)
    consumer = package / "consumer.py"
    operation = f"def check(value: str) -> {annotation}:\n    return {implementation}\ncheck('value')\n"
    consumer.write_text(declaration + operation)
    assert len(analyze([NoDiscardedTaggedOutcome.id], [provider, consumer])) == 1
    consumer.write_text(declaration + mutation + operation)
    assert analyze([NoDiscardedTaggedOutcome.id], [provider, consumer]) == []


def test_stable_literal_alias_retains_definition_scope() -> None:
    source = _BASE.replace(
        "class Accepted(BaseModel):",
        "type Tag = Literal['accepted']\nclass Accepted(BaseModel):",
    ).replace("kind: Literal['accepted']", "kind: Tag")
    assert len(_check(source + "check('value')\n")) == 1


@pytest.mark.parametrize(
    "escape",
    [
        "rewrite(check)",
        "saved = check\nrewrite(saved)",
        "def factory():\n    return check",
    ],
    ids=("direct", "alias", "returned"),
)
def test_escaped_callable_identity_abstains(escape: str) -> None:
    assert _check(_BASE + escape + "\ncheck('value')\n") == []


@pytest.mark.parametrize(
    "alias",
    [
        "saved = check\nsaved('other')",
        "saved = check\ndef use(saved):\n    rewrite(saved)",
    ],
    ids=("direct-alias-call", "shadowed-alias-escape"),
)
def test_safe_callable_alias_preserves_original_warning(alias: str) -> None:
    assert len(_check(_BASE + alias + "\ncheck('value')\n")) == 1


@pytest.mark.parametrize(
    ("declaration", "implementation", "call"),
    [
        ("def", "yield Accepted(kind='accepted', value=value)", "check('value')"),
        ("def", "yield from (Accepted(kind='accepted', value=value),)", "check('value')"),
        (
            "async def",
            "yield Accepted(kind='accepted', value=value)",
            "async def save():\n    await check('value')",
        ),
        (
            "def",
            "def nested(argument=(yield 1)):\n        return argument\n    return Accepted(kind='accepted', value=value)",
            "check('value')",
        ),
    ],
    ids=("yield", "yield-from", "async-generator", "yield-in-nested-default"),
)
def test_generator_call_is_not_a_returned_outcome(declaration: str, implementation: str, call: str) -> None:
    source = _BASE.replace("def check(value", f"{declaration} check(value")
    source = source.replace("return Accepted(kind='accepted', value=value)", implementation)
    assert _check(source + call + "\n") == []


def test_nested_generator_does_not_hide_the_outer_outcome() -> None:
    source = _BASE.replace(
        "    return Accepted",
        "    def nested():\n        yield 1\n    return Accepted",
    )
    assert len(_check(source + "check('value')\n")) == 1


def test_bounded_callable_alias_graph_abstains() -> None:
    aliases = "saved0 = check\n" + "".join(f"saved{index + 1} = saved{index}\n" for index in range(30))
    assert _check(_BASE + aliases + "check('value')\n") == []


@pytest.mark.parametrize(
    "change",
    [
        (
            "    return Accepted(kind='accepted', value=value)\n",
            "    return Accepted(kind='accepted', value=value)\nrewrite(check)\n",
        ),
        ("return Accepted(kind='accepted', value=value)", "yield Accepted(kind='accepted', value=value)"),
    ],
    ids=("escaped-provider", "generator-provider"),
)
def test_imported_callable_requires_stable_non_generator_provider(tmp_path: Path, change: tuple[str, str]) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='outcomes'\nversion='0.0.0'\n")
    provider = package / "models.py"
    provider.write_text(_BASE.replace(*change))
    consumer = package / "consumer.py"
    consumer.write_text("from app.models import check as inspect_value\ninspect_value('value')\n")
    assert analyze([NoDiscardedTaggedOutcome.id], [provider, consumer]) == []
