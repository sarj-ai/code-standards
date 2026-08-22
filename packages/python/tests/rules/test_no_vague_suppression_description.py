from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze
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
        "# noqa: F401 -- needed here",
        "# noqa: F401 -- necessary",
        "# noqa: F401 -- intentional workaround",
        "# noqa: F401 -- lint issue",
        "# noqa: F401 -- false-positive",
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


def test_reports_as_error() -> None:
    assert _check("value = thing  # noqa: F401 -- needed\n")[0].severity.value == "error"


def test_rule_cannot_suppress_its_own_vague_description(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("value = thing  # sarj-noqa: SARJ419 — needed\n", encoding="utf-8")

    assert [finding.code for finding in analyze([NoVagueSuppressionDescription.id], [path])] == ["SARJ419"]
