from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_vague_annotations import NoVagueAnnotations


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/models.py") -> list[Diagnostic]:
    return NoVagueAnnotations().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    NoVagueAnnotations.public_examples(),
    ids=[example.example_id for example in NoVagueAnnotations.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    "annotation",
    [
        "object",
        "dict[str, Any]",
        "Mapping[str, Any]",
        "list[dict[str, Any]]",
        "dict[str, object] | None",
        "'dict[str, Any]'",
    ],
)
def test_flags_vague_annotations_in_all_positions(annotation: str) -> None:
    source = f"from typing import Any, Mapping\nvalue: {annotation}\ndef use(arg: {annotation}) -> {annotation}: ...\n"

    assert len(_check(source, "tests/test_models.py")) == 3


@pytest.mark.parametrize(
    "source",
    [
        "value: JsonValue\n",
        "def use(value: Payload) -> Result: ...\n",
        "class object: ...\nvalue: object\n",
        "from vendor import Any\nvalue: dict[str, Any]\n",
    ],
)
def test_allows_named_precise_or_unproven_types(source: str) -> None:
    assert _check(source) == []


def test_exact_suppression_is_honored() -> None:
    assert _check("from typing import Any\nvalue: dict[str, Any]  # sarj-noqa: SARJ447 — raw boundary\n") == []


@pytest.mark.parametrize("path", ["generated/client.py", "vendor/client.py", "third_party/client.py"])
def test_skips_generated_and_vendor_sources(path: str) -> None:
    assert _check("value: object\n", path) == []
