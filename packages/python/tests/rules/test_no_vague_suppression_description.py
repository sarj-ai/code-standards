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
        "# basedpyright: ignore[reportUnknownMemberType] -- required by the linter",
        "# ruff: ignore[attr-defined] – workaround",
        "# noqa: F401 -- needed here",
        "# noqa: F401 -- necessary",
        "# noqa: F401 -- intentional workaround",
        "# noqa: F401 -- lint issue",
        "# noqa: F401 -- false-positive",
        "# noqa: F401 -- because needed!",
        "# noqa: F401 -- temporary workaround",
        "# noqa: F401 -- known issue",
        "# noqa: F401 -- expected",
        "# noqa: F401 -- by design",
        "# noqa: F401 -- safe",
        "# noqa: F401 -- " + "TO" + "DO",
        "# noqa: F401 -- upstream bug",
    ],
)
def test_flags_closed_generic_reasons(comment: str) -> None:
    assert len(_check(f"value = thing  {comment}\n")) == 1


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: F401",
        "# noqa: F401 -- imported for plugin registration",
        "# noqa: F401 -- needed for Python 3.10 compatibility",
        "# type: ignore[attr-defined] -- vendor stubs omit the runtime field",
        "# type: ignore[attr-defined] -- false positive: typeshed omits the runtime descriptor",
        "# pyright: ignore[reportAny] -- same",
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


def test_reports_as_warning_and_quotes_the_reason() -> None:
    finding = _check("value = thing  # noqa: F401 -- needed\n")[0]

    assert finding.severity.value == "warning"
    assert '"needed"' in finding.message


def test_plain_standalone_directive_is_not_an_effective_suppression() -> None:
    assert _check("# noqa: F401 -- needed\nvalue = thing\n") == []
    assert _check("# ruff: ignore[F401] -- needed\nvalue = thing\n") == []


@pytest.mark.parametrize(
    "comment",
    [
        "# ruff: file-ignore[import-error] -- needed",
        "# ruff: noqa: F401 -- workaround",
        "# flake8: noqa -- intentional",
    ],
)
def test_file_scope_directive_may_stand_alone(comment: str) -> None:
    assert len(_check(f"{comment}\nvalue = thing\n")) == 1


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: F401 -- plugin registration # type: ignore[attr-defined] -- needed",
        "# noqa: F401 -- needed # type: ignore[attr-defined] -- vendor stubs omit the runtime field",
        "# noqa: F401 -- needed # type: ignore[attr-defined] -- workaround",
    ],
)
def test_checks_every_directive_but_reports_once_per_comment(comment: str) -> None:
    assert len(_check(f"value = thing  {comment}\n")) == 1


def test_hash_issue_reference_does_not_split_a_description() -> None:
    assert _check("value = thing  # noqa: F401 -- vendor bug #123\n") == []


def test_modern_directive_with_multiple_codes_is_supported() -> None:
    findings = _check("value = thing  # ruff: ignore[attr-defined,assignment] — tool limitation?\n")

    assert len(findings) == 1


def test_directive_text_inside_a_string_is_not_a_comment() -> None:
    assert _check('reason = "# ruff: ignore[attr-defined] -- needed"\n') == []


def test_rule_cannot_suppress_its_own_vague_description(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("value = thing  # sarj-noqa: SARJ419 — needed\n", encoding="utf-8")

    assert [finding.code for finding in analyze([NoVagueSuppressionDescription.id], [path])] == ["SARJ419"]
