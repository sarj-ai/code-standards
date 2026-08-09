from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_file_level_suppression import NoFileLevelSuppression


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


SRC_PATH = "python/app/app/calls/call_service.py"


def _check(source: str, path: str = SRC_PATH) -> list[Diagnostic]:
    return NoFileLevelSuppression().check(Path(path), source)


_PUBLIC_EXAMPLES = NoFileLevelSuppression.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_unparsable_source_yields_no_diagnostics() -> None:
    assert _check("# type: ignore\ndef (:\n") == []


# Ruff ownership: PGH004 owns bare Ruff file-wide noqa.                         #


@pytest.mark.parametrize(
    "source",
    [
        "# ruff: noqa\nimport os\n",
        "# ruff:noqa\nimport os\n",
        "#ruff: noqa\nimport os\n",
        "# RUFF: NOQA\nimport os\n",
        "# ruff: noqa   \nimport os\n",
        # A prose reason after the directive still names no codes.
        "# ruff: noqa — legacy module, cleanup tracked in BUL-123\nimport os\n",
        "# ruff: noqa - see ticket\nimport os\n",
        "# ruff: noqa:\nimport os\n",
        # Ruff honours the file-level exemption wherever it appears.
        '"""Doc."""\n\nimport os\n\n# ruff: noqa\n',
        "import os\n\n\ndef f():\n    # ruff: noqa\n    return os\n",
        "x = 1  # ruff: noqa\n",
    ],
)
def test_defers_bare_ruff_noqa_to_pgh004(source: str):
    assert _check(source) == []


# Positive: standalone `# type: ignore` / `# pyright: ignore` above line 1.    #


@pytest.mark.parametrize(
    "source",
    [
        "# type: ignore\nimport os\n",
        "# type:ignore\nimport os\n",
        "#type: ignore\nimport os\n",
        "# type: ignore — vendored\nimport os\n",
        "#!/usr/bin/env python\n# type: ignore\nimport os\n",
        "# -*- coding: utf-8 -*-\n# type: ignore\nimport os\n",
        "# Copyright 2026 Sarj\n# type: ignore\nimport os\n",
        "\n\n# type: ignore\n\nimport os\n",
        # No statement at all: the blanket still governs the whole file.
        "# type: ignore\n",
    ],
)
def test_flags_file_level_type_ignore(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ038"
    assert "type: ignore" in diags[0].message
    assert "mypy" in diags[0].message


@pytest.mark.parametrize(
    "source",
    [
        "# pyright: ignore\nimport os\n",
        "# pyright:ignore\nimport os\n",
        "# pyright: ignore — vendored\nimport os\n",
        "#!/usr/bin/env python\n# pyright: ignore\nimport os\n",
        "# pyright: ignore\n",
    ],
)
def test_flags_file_level_pyright_ignore(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert "pyright: ignore" in diags[0].message


# Negative: scoped suppressions are reviewed, legible decisions.               #


@pytest.mark.parametrize(
    "source",
    [
        "# ruff: noqa: E501\nimport os\n",
        "# ruff: noqa: E501, F401\nimport os\n",
        "# ruff:noqa:E501\nimport os\n",
        "# ruff: noqa: E501 — long generated URLs\nimport os\n",
        "# RUFF: NOQA: E501\nimport os\n",
        "# type: ignore[attr-defined]\nimport os\n",
        "# type: ignore[attr-defined, no-untyped-def]\nimport os\n",
        "# type:ignore[misc]\nimport os\n",
        "# pyright: ignore[reportUnusedImport]\nimport os\n",
        "# pyright: ignore[reportUnusedImport, reportMissingImports]\nimport os\n",
    ],
)
def test_allows_scoped_suppressions(source: str):
    assert _check(source) == []


# Negative: per-line suppressions bind to one line by construction.            #


@pytest.mark.parametrize(
    "source",
    [
        "x = 1  # type: ignore\n",
        "x = 1  # type: ignore[assignment]\n",
        "x = 1  # pyright: ignore\n",
        "x = 1  # pyright: ignore[reportGeneralTypeIssues]\n",
        "from legacy import thing  # type: ignore\n",
        # A trailing form on the very first line is still per-line.
        "import os  # type: ignore\nimport sys\n",
        # Comment inside a continuation is not standalone either.
        "from legacy import (  # type: ignore\n    thing,\n)\n",
        "x = foo(\n    1,\n)  # type: ignore\n",
    ],
)
def test_allows_trailing_per_line_suppressions(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        # A module docstring is a statement, so what follows it is not file-level.
        '"""Module doc."""\n\n# type: ignore\n\nimport os\n',
        '"""Module doc."""\n# pyright: ignore\nimport os\n',
        "import os\n\n# type: ignore\nimport sys\n",
        "import os\n\n\ndef f():\n    # type: ignore\n    return 1\n",
        "import os\n\n\ndef f():\n    # pyright: ignore\n    return 1\n",
    ],
)
def test_allows_standalone_suppression_after_first_statement(source: str):
    assert _check(source) == []


# Negative: other comments that legitimately sit at the top of a file.         #


@pytest.mark.parametrize(
    "source",
    [
        "#!/usr/bin/env python\nimport os\n",
        "# -*- coding: utf-8 -*-\nimport os\n",
        "# Copyright 2026 Sarj. All rights reserved.\n# SPDX-License-Identifier: MIT\nimport os\n",
        '"""Module doc."""\n\nimport os\n',
        # Per-line noqa without the `ruff:` prefix is a different rule's business.
        "# noqa\nimport os\n",
        "# noqa: E501\nimport os\n",
        "x = 1  # noqa\n",
        # A different `ruff:` directive.
        "# ruff:ignore[global-statement] — single-slot memo\nimport os\n",
        "# ruff: isort: skip_file\nimport os\n",
        # Pyright configuration, not a blanket ignore.
        "# pyright: strict\nimport os\n",
        "# pyright: basic\nimport os\n",
        # Words that merely start with a directive head.
        "# type: ignored by the parser\nimport os\n",
        "# ruff: noqas\nimport os\n",
        # A space before the colon is not a directive any tool honours.
        "# ruff : noqa\nimport os\n",
        "# type : ignore\nimport os\n",
        # Prose that merely mentions the directive.
        "# never add a blanket ruff: noqa to this file\nimport os\n",
        "# see the type: ignore convention in CONTRIBUTING\nimport os\n",
    ],
)
def test_allows_unrelated_comments(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'directive = "# ruff: noqa"\n',
        'directive = "# type: ignore"\n',
        'directive = "# pyright: ignore"\n',
    ],
)
def test_allows_directive_text_inside_strings(source: str):
    assert _check(source) == []


# Counts, ordering, position.                                                  #


def test_multiple_blankets_each_reported_sorted_by_line():
    src = "# type: ignore\n# pyright: ignore\nimport os\n\nx = 1  # ruff: noqa\n"
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == [1, 2]
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_and_col_are_one_based():
    src = "# type: ignore\nimport os\n"
    diags = _check(src)
    assert (diags[0].line, diags[0].col) == (1, 1)


def test_trailing_ruff_noqa_col_points_at_the_comment():
    assert _check("x = 1  # ruff: noqa\n") == []


def test_scoped_and_bare_in_the_same_file_reports_only_the_bare_one():
    src = "# ruff: noqa: E501\n# type: ignore\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_reasoned_sarj_noqa_suppresses_a_justified_blanket():
    src = "# type: ignore  # sarj-noqa: SARJ038 — generated module\nimport os\n"
    diagnostic = _check(src)[0]
    assert is_suppressed(src.splitlines(), diagnostic.line, diagnostic.code)


def test_sarj_noqa_for_another_rule_does_not_suppress_the_blanket():
    src = "# type: ignore  # sarj-noqa: SARJ054 — generated module\nimport os\n"
    diagnostic = _check(src)[0]
    assert not is_suppressed(src.splitlines(), diagnostic.line, diagnostic.code)


# Edge cases: malformed and trivial sources.                                   #


@pytest.mark.parametrize(
    "source",
    [
        "",
        "  ",
        "\n\n",
        "# just a note\n",
        "# one\n# two\n# three\n",
    ],
)
def test_empty_or_comment_only_sources(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def f(:\n    pass\n",
        'x = "unterminated\n',
        'x = """unterminated\n',
        "def f():\n        pass\n  pass\n",
        "# ruff: noqa\ndef f(:\n",
    ],
)
def test_malformed_source_returns_empty_without_raising(source: str):
    assert _check(source) == []
