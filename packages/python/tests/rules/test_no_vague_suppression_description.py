from pathlib import Path

import pytest

from sarj_python_lint.rules.no_vague_suppression_description import NoVagueSuppressionDescription


def _check(source: str, name: str = "app.py"):
    return NoVagueSuppressionDescription().check(Path(name), source)


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: F401 -- needed",
        "# sarj-noqa: SARJ023 — intentional",
        "# type: ignore[attr-defined] -- false positive",
        "# pyright: ignore[reportUnknownMemberType] -- to satisfy the type checker",
    ],
)
def test_flags_closed_generic_reasons(comment: str) -> None:
    assert len(_check(f"value = thing  {comment}\n")) == 1


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: F401",
        "# noqa: F401 -- imported for plugin registration",
        "# type: ignore[attr-defined] -- vendor stubs omit the runtime field",
        "# this false positive example is ordinary prose",
    ],
)
def test_preserves_missing_or_concrete_reasons(comment: str) -> None:
    assert _check(f"value = thing  {comment}\n") == []


def test_skips_generated_files_and_malformed_source() -> None:
    assert _check("# @generated\nvalue = thing  # noqa: F401 -- needed\n") == []
    assert _check("value = (\n# noqa: F401 -- needed\n") == []


def test_public_examples_execute() -> None:
    examples = NoVagueSuppressionDescription.public_examples()
    assert [len(_check(example.focus_file.source)) for example in examples] == [1, 0]
