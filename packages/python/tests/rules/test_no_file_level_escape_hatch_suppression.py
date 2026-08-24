from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_file_level_escape_hatch_suppression import (
    ESCAPE_HATCH_SELECTORS,
    NoFileLevelEscapeHatchSuppression,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoFileLevelEscapeHatchSuppression.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return NoFileLevelEscapeHatchSuppression().check(Path("svc/tests/test_thing.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoFileLevelEscapeHatchSuppression().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("# ruff: noqa: TID251\nimport os\n", id="alone"),
        pytest.param("# ruff:noqa: TID251\nimport os\n", id="no-space-after-ruff"),
        pytest.param("#ruff: noqa:TID251\nimport os\n", id="tight-spacing"),
        pytest.param("# RUFF: NOQA: TID251\nimport os\n", id="uppercase-directive"),
        pytest.param("# ruff: noqa: tid251\nimport os\n", id="lowercase-code"),
        pytest.param("# ruff: noqa: E501, TID251\nimport os\n", id="second-in-a-list"),
        pytest.param("# ruff: noqa: TID251, E501\nimport os\n", id="first-in-a-list"),
        pytest.param("#!/usr/bin/env python\n# ruff: noqa: TID251\nimport os\n", id="under-a-shebang"),
        pytest.param('"""Docstring."""\n\n# ruff: noqa: TID251\nimport os\n', id="under-a-docstring"),
        pytest.param("import os\n\n# ruff: noqa: TID251\n", id="at-the-bottom-of-the-file"),
    ],
)
def test_flags_file_level_escape_hatch_exemption(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ054"
    assert "TID251" in diags[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("# ruff: file-ignore[TID251]\nimport os\n", id="code"),
        pytest.param("# ruff: file-ignore[banned-api]\nimport os\n", id="preferred-rule-name"),
        pytest.param("# RUFF: FILE-IGNORE[ BANNED-API ]\nimport os\n", id="case-and-spacing"),
        pytest.param("# ruff: file-ignore[E501, banned-api]\nimport os\n", id="second-in-list"),
        pytest.param("# ruff: file-ignore[banned-api, E501]\nimport os\n", id="first-in-list"),
        pytest.param("# ruff: file-ignore[TID251, banned-api]\nimport os\n", id="aliases-deduplicate"),
    ],
)
def test_flags_modern_file_ignore_escape_hatch(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ054"


def test_message_points_at_the_inline_form():
    diags = _check("# ruff: noqa: TID251\nimport os\n")
    assert "# noqa: TID251 — " in diags[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from unittest import mock  # noqa: TID251 — vendor SDK\n", id="inline-per-line-form"),
        pytest.param("import os  # ruff: noqa: TID251\n", id="ruff-prefixed-inline-is-not-file-level"),
        pytest.param("# ruff: noqa: E501\nimport os\n", id="mechanical-code"),
        pytest.param("# ruff: noqa: F401, F403\nfrom x import *\n", id="mechanical-code-list"),
        pytest.param("# ruff: noqa: UP035\nimport os\n", id="another-mechanical-code"),
        pytest.param("# ruff: noqa\nimport os\n", id="unscoped-blanket-is-pgh004"),
        pytest.param("# ruff: noqa:\nimport os\n", id="trailing-colon-names-nothing"),
        pytest.param("# ruff: noqa — legacy module\nimport os\n", id="prose-only-reason"),
        pytest.param("# noqa: TID251\nimport os\n", id="no-ruff-prefix"),
        pytest.param("# ruff: isort: skip_file\nimport os\n", id="other-ruff-directive"),
        pytest.param("# TID251 is banned at file level\nimport os\n", id="prose-naming-the-code"),
        pytest.param("# ruff: noqa: TID2510\nimport os\n", id="longer-code-with-the-same-prefix"),
        pytest.param("# ruff: file-ignore[E501]\nimport os\n", id="modern-mechanical-rule"),
        pytest.param("# ruff: file-ignore: TID251\nimport os\n", id="invalid-colon-file-ignore"),
        pytest.param("# ruff: file-ignore[TID]\nimport os\n", id="invalid-code-prefix"),
        pytest.param("# ruff: file-ignore[banned-api-extra]\nimport os\n", id="longer-name-with-the-same-prefix"),
        pytest.param("# ruff: disable[banned-api]\nimport os\n# ruff: enable[banned-api]\n", id="balanced-range"),
    ],
)
def test_allows(source: str):
    assert _check(source) == []


def test_reports_each_offending_comment():
    src = "# ruff: noqa: TID251\nimport os\n\n# ruff: noqa: TID251\n"
    assert [d.line for d in _check(src)] == [1, 4]


def test_does_not_fire_on_a_directive_inside_a_string():
    src = 'BANNED = "# ruff: noqa: TID251"\n'
    assert _check(src) == []


def test_unparsable_source_yields_no_diagnostics():
    assert _check("# ruff: noqa: TID251\ndef (:\n") == []


def test_reasoned_sarj_noqa_suppresses_a_deliberate_file_level_hatch():
    src = "# ruff: noqa: TID251  # sarj-noqa: SARJ054 — vendored SDK test harness\n"
    diagnostic = _check(src)[0]
    assert is_suppressed(src.splitlines(), diagnostic.line, diagnostic.code)


def test_sarj_noqa_for_another_rule_does_not_suppress_the_hatch():
    src = "# ruff: noqa: TID251  # sarj-noqa: SARJ016 — vendored SDK test harness\n"
    diagnostic = _check(src)[0]
    assert not is_suppressed(src.splitlines(), diagnostic.line, diagnostic.code)


def test_escape_hatch_set_is_exactly_the_banned_api_code():
    # The set is derived from ruff.strict.toml's banned-api messages, which are the only ones instructing an inline reasoned suppression.
    assert frozenset({"TID251", "BANNED-API"}) == ESCAPE_HATCH_SELECTORS


def test_owns_scoped_ruff_hatch_while_ruff_owns_the_bare_blanket():
    src = "# ruff: noqa\n# ruff: noqa: TID251\nimport os\n"
    path = Path("svc/app/thing.py")
    assert [d.line for d in NoFileLevelEscapeHatchSuppression().check(path, src)] == [2]
