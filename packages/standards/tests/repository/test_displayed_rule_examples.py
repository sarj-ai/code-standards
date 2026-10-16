from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field
import pytest
from sarj_rule_contracts import ExampleFile
from sarj_rule_contracts.examples import verify_examples

from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


class _DisplayFile(BaseModel):
    path: str
    source: str


class _DisplayExample(BaseModel):
    id: str
    files: tuple[_DisplayFile, ...]
    fixed_files: tuple[_DisplayFile, ...] = Field(alias="fixedFiles")


class _DisplayRule(BaseModel):
    examples: tuple[_DisplayExample, ...]


class _DisplayProjection(BaseModel):
    rules: dict[str, _DisplayRule]


_ROOT = Path(__file__).resolve().parents[4]
_DISPLAY = _DisplayProjection.model_validate_json(
    (_ROOT / "apps/docs/src/generated/formatted-code.v1.json").read_text(encoding="utf-8")
)


def _compile_displayed_python(example: _DisplayExample) -> None:
    # Native analyzers may deliberately skip malformed sources as unprovable.
    for file in (*example.files, *example.fixed_files):
        if PurePosixPath(file.path).suffix == ".py":
            compile(file.source, file.path, "exec", dont_inherit=True)


@pytest.mark.parametrize("collection", ["files", "fixed_files"])
@pytest.mark.parametrize("path", ["app/focus.py", "app/companion.py"])
def test_displayed_python_syntax_rejects_malformed_focus_companions_and_fixes(collection: str, path: str) -> None:
    example = _DisplayExample(
        id="no-match", files=(_DisplayFile(path="app/focus.py", source="value = 1\n"),), fixedFiles=()
    )
    malformed = example.model_copy(update={collection: (_DisplayFile(path=path, source="def broken(\n"),)})

    with pytest.raises(SyntaxError):
        _compile_displayed_python(malformed)


@pytest.mark.parametrize("key", tuple(key for key in _DISPLAY.rules if not key.startswith("eslint:")))
def test_displayed_examples_preserve_the_live_rule_outcome(key: str) -> None:
    rule = selected(RuleSelector.parse(key))
    displayed = _DISPLAY.rules[key].examples
    by_id = {example.id: example for example in displayed}
    public = tuple(example for example in rule.spec.examples if example.public)
    assert len(by_id) == len(displayed)
    assert set(by_id) == {example.example_id for example in public}
    for example in displayed:
        _compile_displayed_python(example)
    examples = tuple(
        replace(
            example,
            files=tuple(ExampleFile(PurePosixPath(file.path), file.source) for file in by_id[example.example_id].files),
            fixed_files=tuple(
                ExampleFile(PurePosixPath(file.path), file.source) for file in by_id[example.example_id].fixed_files
            ),
        )
        for example in public
    )

    assert verify_examples(examples, rule.analyze, expected_code=rule.spec.code) == len(public)
