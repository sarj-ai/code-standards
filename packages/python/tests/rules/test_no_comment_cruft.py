from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_comment_cruft import NoCommentCruft


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoCommentCruft().check(Path("<t>.py"), source)


def _standalone(body: str) -> list[Diagnostic]:
    """Wrap `body` as a lone own-line comment between two real code lines.

    Returns:
        The diagnostics from checking the wrapped source.

    """
    return _check(f"x = 1\n# {body}\ny = 2\n")


COMMENTED_OUT_CODE = [
    "return x + 1",
    "return x",
    "import os",
    "from foo import bar",
    "yield item",
    "await coro()",
    "del foo",
    "pass",
    "break",
    "continue",
    "global counter",
    "nonlocal state",
    "print(result)",
    "x = compute()",
    "self.value = 42",
    "obj.method(arg)",
    "foo()",
    "result += 1",
    "count -= 1",
    "scale *= 2",
    "ratio /= 3",
    "matches[key] = value",
    "for row in rows:",
    "if condition:",
    "while True:",
    "with open(f) as fh:",
    "def helper():",
    "class Foo:",
    "async def go():",
    "@decorator",
    "@app.route('/x')",
    "assert result == expected",
    'raise ValueError("boom")',
]


@pytest.mark.parametrize("body", COMMENTED_OUT_CODE)
def test_flags_commented_out_code(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


BANNERS = [
    "====================",
    "--------------------",
    "####################",
    "********************",
    "~~~~~~~~~~~~~~~~~~~~",
    "____________________",
    "++++++++++++++++++++",
    "....................",
    "====",
    "----",
    "Section ============",
    "helpers ------------",
    "boundary ~~~~",
    "region",
    "region helpers",
    "endregion",
    "endregion helpers",
    "use ---- sparingly",
    "value = a **** b",
]


@pytest.mark.parametrize("body", BANNERS)
def test_flags_banner_or_region(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


LEGIT_PROSE = [
    "assert this is true before we proceed",
    "raise the question with the team first",
    "return to this later when we refactor",
    "import the concept of idempotency here",
    "pass this along to the reviewer",
    "break out of the pattern when stuck",
    "continue reading below for context",
    "yield better results over time",
    "del old behavior noted here for us",
    "global state matters for this cache",
    "for clarity we inline the call here",
    "if in doubt ask the team lead first",
    "class of problems we deliberately avoid",
    "with great power comes responsibility",
    "try harder next time around",
    "except when it rains outside",
    "else the fallback path runs slowly",
    "finally the invariant holds again",
    "returns cached value when warm",
    "importantly we cache here for speed",
    "classifier config lives below this",
    "forwards the request to upstream",
    "withhold the retry until backoff ends",
    "passes validation before persisting",
    "deletes stale rows once nightly",
    "printing happens elsewhere in code",
    "retry because the upstream API is flaky",
    "this must match the value in settings.py",
    "ordering matters here for migration 042",
    "do not change this because Clerk caches it",
    "see incident PLATFORM-1XW for context",
    "count: int = 0",
    "value: dict[str, int] = {}",
    "x == expected",
    "a === b in the JS bridge, not ==",
    "compare x == y for equality",
    "use --- sparingly in prose",
    "handles the try: header edge case",
    "نتحقق من الرقم قبل الإرسال",
]


@pytest.mark.parametrize("body", LEGIT_PROSE)
def test_ignores_legit_prose(body: str):
    assert _standalone(body) == []


_NARRATION = [
    "First, fetch the user",
    "Then, map over the results",
    "Step 2: validate the payload",
    "this is a temporary hack that only works when x",
    "hardcoded for now",
    "not sure if this is the right approach",
]


@pytest.mark.parametrize("body", _NARRATION)
def test_flags_redundant_narration(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "narrates" in diags[0].message


def test_flags_dummy_translational_comments():
    diags = _standalone("increment i by 1")
    assert len(diags) == 1
    diags = _standalone("return the response")
    assert len(diags) == 1


@pytest.mark.parametrize(
    "body",
    [
        "finally the invariant holds again",
        "firstName is required by the upstream API",
        "now-deprecated path kept for back-compat",
    ],
)
def test_narration_words_in_prose_not_flagged(body: str):
    assert _standalone(body) == []


DIRECTIVES = [
    "type: ignore",
    "type: ignore[assignment]",
    "noqa",
    "noqa: F401",
    "sarj-noqa: SARJ016 — intentional",
    "pragma: no cover",
    "pragma: allowlist secret",
    "pyright: ignore",
    "mypy: ignore",
    "fmt: off",
    "fmt: on",
    "isort: skip",
    "ruff: noqa",
    "pylint: disable=redefined-outer-name",
    "flake8: noqa",
    "nosec",
    "nosemgrep",
    "hack: workaround for upstream bug",
    "xxx: dangerous assumption here",
    "-*- coding: utf-8 -*-",
]


@pytest.mark.parametrize("body", DIRECTIVES)
def test_ignores_directive_comments(body: str):
    assert _standalone(body) == []


def test_flags_untracked_todo_and_fixme():
    assert len(_standalone("todo: revisit this soon")) == 1
    assert len(_standalone("fixme: broken under load")) == 1


def test_ignores_tracked_todo_and_fixme():
    assert _standalone("todo: revisit this soon (JIRA-1234)") == []
    assert _standalone("fixme: broken under load http://github.com/issue/12") == []


def test_header_keywords_without_body_are_not_code():
    for body in ("try:", "except ValueError:", "else:", "elif cond:", "finally:"):
        assert _standalone(body) == [], body


def test_inline_trailing_comment_is_never_flagged():
    assert _check("x = compute()  # return x + 1\n") == []
    assert _check("y = 1  # ====================\n") == []
    assert _check("z = 2  # region helpers\n") == []


def test_hash_inside_string_is_not_a_comment():
    assert _check('x = "# return y"\n') == []
    assert _check("x = '# region helpers'\n") == []


def test_hash_inside_multiline_string_is_not_a_comment():
    assert _check('x = """\n# return y\n# ====\n"""\n') == []


def test_docstring_is_not_a_comment():
    assert _check('"""Module why: it does the thing for a reason."""\nx = 1\n') == []


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   \n\t\n",
        "def (:\n",
        'x = "unterminated\n',
        "x = (\n",
    ],
)
def test_empty_or_unparseable_source_returns_nothing(source: str):
    assert _check(source) == []


def test_reports_1based_line_and_1based_col_top_level():
    diags = _check("# return x + 1\nv = 1\n")
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (1, 1)


def test_reports_line_and_col_for_indented_comment():
    diags = _check("def f():\n    # return x + 1\n    return f()\n")
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (2, 5)


def test_diagnostic_carries_code_and_path():
    diags = _check("# return x + 1\nv = 1\n")
    assert diags[0].code == "SARJ016"
    assert diags[0].path == Path("<t>.py")


def test_multiple_violations_are_sorted_by_line():
    src = "# region a\n# return b\n# ====\nx = 1\n"
    diags = _check(src)
    assert [d.line for d in diags] == [1, 2, 3]


def test_flags_each_consecutive_commented_out_line():
    src = "# return a\n# import os\n# obj.call()\nx = 1\n"
    assert len(_check(src)) == 3


def test_region_and_endregion_both_flag():
    src = "x = 1\n# region helpers\ny = 2\n# endregion\nz = 3\n"
    diags = _check(src)
    assert len(diags) == 2
    assert all("Section-banner" in d.message for d in diags)


def test_box_drawing_run_is_a_banner():
    diags = _check("x = 1\n# ════════\ny = 2\n")
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


def test_three_char_symbol_run_is_not_a_banner():
    assert _standalone("split on --- here and === there") == []


def test_flags_leading_file_header_preamble():
    # A content-free header: bare labels, nothing explained. A preamble that
    # carries a prose sentence is documentation and is exempt — see
    # `test_preamble_with_a_prose_sentence_is_documentation`.
    src = "# module: ingest\n# author: apham\n# version: 3\n# status: draft\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message
    assert (diags[0].line, diags[0].col) == (1, 1)


def test_preamble_message_reports_line_count():
    src = "# a1\n# b2\n# c3\n# d4\n# e5\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "(5 lines)" in diags[0].message


# --- file-header preamble: the "no prose sentence" guard -------------------
# Shared spec with the TS twin's `fileHeaderPreamble` arm. The naive
# 4-consecutive-comment-lines test penalises syntax rather than content, so it
# flags a module header precisely when someone bothered to write one. Measured
# over bulbul + noura-be + django/fastapi/celery: 7 hits, 7 false positives.
# Each case below is minimized from one of them.


def test_preamble_with_a_prose_sentence_is_documentation():
    # django/django/contrib/auth/urls.py:1 — explains why the URLconf exists.
    src = (
        "# The views used below are normally mapped in the AdminSite instance.\n"
        "# This URLs file is used to provide a reliable view deployment for test\n"
        "# purposes. It is also provided as a convenience to those who want to\n"
        "# deploy these URLs elsewhere.\n"
        "from django.urls import path\n"
    )
    assert _check(src) == []


def test_preamble_whose_lead_in_ends_in_a_colon_is_documentation():
    # fastapi/tests/test_no_schema_split.py:1 — links the upstream discussion.
    src = (
        "# Test with parts from, and to verify the report in:\n"
        "# https://github.com/fastapi/fastapi/discussions/14177\n"
        "# Made an issue in:\n"
        "# https://github.com/fastapi/fastapi/issues/14247\n"
        "from enum import Enum\n"
    )
    assert _check(src) == []


def test_preamble_of_cli_usage_prose_is_documentation():
    # django/scripts/manage_translations.py:2 — the script's CLI reference.
    src = (
        "# This Python file contains utility scripts to manage translations.\n"
        "# It has to be run inside the django git root directory.\n"
        "#\n"
        "# The following commands are available:\n"
        "#\n"
        "# * update_catalogs: check for new strings in core catalogs.\n"
        "import os\n"
    )
    assert _check(src) == []


def test_content_free_label_stack_is_still_a_preamble():
    # The shape the arm is kept for: no line is a sentence, nothing is explained.
    src = "# module: ingest\n# owner: platform\n# version: 3\n# status: draft\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message


def test_one_prose_line_anywhere_in_the_run_exempts_the_whole_preamble():
    # The guard is `any`, not `all`: a single explained line makes it a doc.
    src = (
        "# module: ingest\n"
        "# owner: platform\n"
        "# Retries are capped at three because the upstream rate-limits us.\n"
        "# status: draft\n"
        "import os\n"
    )
    assert _check(src) == []


def test_three_line_preamble_is_below_threshold():
    src = "# alpha note\n# beta note\n# gamma note\nimport os\n"
    assert _check(src) == []


def test_short_leading_comment_is_allowed():
    assert _check("# why this module exists at all\nimport os\n") == []


def test_license_header_preamble_is_allowed():
    src = (
        "# Copyright 2023 LiveKit, Inc.\n"
        "#\n"
        '# Licensed under the Apache License, Version 2.0 (the "License");\n'
        "# you may not use this file except in compliance with the License.\n"
        "# See the License for the specific language governing permissions.\n"
        "import os\n"
    )
    assert _check(src) == []


def test_blank_line_breaks_the_preamble_run():
    src = "# alpha\n# beta\n\n# gamma\n# delta\nimport os\n"
    assert _check(src) == []


def test_directive_line_breaks_the_preamble_run():
    src = "# alpha\n# noqa: E501\n# gamma\n# delta\n# epsilon\nimport os\n"
    assert _check(src) == []


def test_shebang_is_skipped_but_preamble_still_counts_below_it():
    src = "#!/usr/bin/env python\n# alpha\n# beta\n# gamma\n# delta\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message
    assert diags[0].line == 2


def test_all_comment_file_with_no_code_flags_preamble():
    src = "# alpha\n# beta\n# gamma\n# delta\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message


def test_midfile_comment_run_is_not_a_preamble():
    src = "import os\n\nx = 1\n# alpha note\n# beta note\n# gamma note\n# delta note\ny = 2\n"
    assert _check(src) == []


def test_comment_run_after_module_docstring_is_not_a_preamble():
    src = '"""Module docstring."""\n# alpha\n# beta\n# gamma\n# delta\nx = 1\n'
    assert _check(src) == []


def test_preamble_and_embedded_banner_both_flag():
    # The second `====` run follows another banner line, so it is a real
    # section banner, not a heading underline beneath prose.
    src = "# alpha note\n# ================\n# ================\n# delta note\nimport os\n"
    diags = _check(src)
    assert len(diags) == 2
    assert "preamble" in diags[0].message
    assert "Section-banner" in diags[1].message
    assert diags[1].line == 3


def test_heading_underline_beneath_prose_comment_is_not_a_banner():
    # Minimized from trio's epoll design essay: an RST-style underline directly
    # beneath a texty comment line is typography inside a prose block.
    src = "x = 1\n\n# Some facts about epoll\n# ----------------------\n#\n# It is like a dict.\ny = 2\n"
    assert _check(src) == []


def test_ascii_diagram_row_beneath_texty_comment_is_not_a_banner():
    # Minimized from trio's _run.py control-flow diagram.
    src = "x = 1\n\n# | Host loop does whatever |\n# +---------------------------+\ny = 2\n"
    assert _check(src) == []


def test_banner_beneath_commented_out_code_still_flags():
    src = "x = 1\n# return b\n# ================\ny = 2\n"
    diags = _check(src)
    assert [d.message.split(" ")[0] for d in diags] == ["Commented-out", "Section-banner"]


def test_preamble_suppressed_when_first_line_is_commented_out_code():
    src = "# return x + 1\n# beta note\n# gamma note\n# delta note\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_annotated_assignment_body_is_not_flagged():
    assert _standalone("count: int = 0") == []


def test_bare_comparison_body_is_not_flagged():
    assert _standalone("result == expected") == []


@pytest.mark.parametrize("ch", ["~", "#", "*", "=", "-"])
def test_run_char_banner_boundary_three_vs_four(ch: str):
    assert _standalone(ch * 3) == [], ch
    diags = _standalone(ch * 4)
    assert len(diags) == 1, ch
    assert "Section-banner" in diags[0].message, ch


@pytest.mark.parametrize("ch", ["+", "_", "."])
def test_full_only_fill_char_banner_boundary_three_vs_four(ch: str):
    assert _standalone(ch * 3) == [], ch
    assert len(_standalone(ch * 4)) == 1, ch


@pytest.mark.parametrize(
    "body", ["wait ---- for it", "issue #### tracked", "rating **** stars", "range ~~~~ approx", "a ==== b"]
)
def test_four_run_of_rule_char_inside_prose_is_flagged(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


@pytest.mark.parametrize("body", ["cost .... approx", "scores ++++ higher", "dunder ____ name here"])
def test_full_only_fill_chars_do_not_flag_inside_prose(body: str):
    assert _standalone(body) == []


def test_trailing_inline_comment_on_commented_out_code_still_flags():
    diags = _standalone("x = compute()  # legacy path")
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_annotated_assignment_with_call_rhs_is_not_flagged():
    assert _standalone("cache: Dict = build()") == []


def test_two_word_assignment_aphorism_is_flagged_as_code():
    assert len(_standalone("time = money")) == 1
    assert len(_standalone("a = b in math")) == 1


def test_global_keyword_with_assignment_prose_is_not_code():
    assert _standalone("global config = None") == []


def test_at_sign_with_space_is_not_a_decorator():
    assert _standalone("@ the office we standardize this") == []


def test_directive_without_space_after_colon_is_ignored():
    assert _standalone("type:ignore") == []
    assert _standalone("fmt:off") == []


def test_uppercase_endregion_is_flagged():
    diags = _standalone("ENDREGION")
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


def test_word_starting_with_region_is_not_a_banner():
    assert _standalone("regionally we differ here") == []


def test_arabic_prose_comment_is_not_flagged():
    assert _standalone("نتحقق من الرقم قبل الإرسال") == []


def test_commented_code_with_arabic_identifier_is_flagged():
    diags = _standalone("return النتيجة")
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_ascii_banner_around_arabic_text_is_flagged():
    diags = _standalone("==== قسم ====")
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


def test_empty_comment_line_counts_toward_preamble():
    src = "# alpha\n#\n# gamma\n# delta\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message
    assert "(4 lines)" in diags[0].message


def test_todos_assignment_is_commented_out_code_not_a_directive():
    diags = _standalone("todos = []")
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_identifier_starting_with_noqa_is_not_a_directive():
    diags = _standalone("noqant = fetch()")
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_illustration_under_for_example_lead_in_is_not_flagged():
    src = "x = 1\n# For example:\n# result = {**a, **b}\ny = 2\n"
    assert _check(src) == []


def test_prose_continuation_line_that_parses_is_not_flagged():
    src = "x = 1\n# passes a value that already called\n# self._type_adapter.validate_python(value)\ny = 2\n"
    assert _check(src) == []


def test_prose_describing_else_branch_over_isinstance_call_is_not_flagged():
    src = "x = 1\n# matches when the argument is a request, i.e.\n# isinstance(args[0], BaseRequest)\ny = 2\n"
    assert _check(src) == []


def test_pseudocode_placeholder_markers_are_not_flagged():
    for body in ("_a = %sent%", "config[...] = default", "handler = <FunctionBody>", "opt = value[opt]"):
        assert _standalone(body) == [], body


def test_real_two_line_commented_block_after_prose_lead_still_fires_on_both():
    src = "x = 1\n# old = compute()\n# save(old)\ny = 2\n"
    diags = _check(src)
    assert len(diags) == 2
    assert all("Commented-out code" in d.message for d in diags)


def test_dead_code_after_short_prose_reason_still_suppressed_conservatively():
    src = "x = 1\n# reason we keep this note\n# self.retry()\ny = 2\n"
    assert _check(src) == []


def test_banner_preceding_code_line_does_not_suppress_it():
    src = "x = 1\n# ================\n# return legacy\ny = 2\n"
    diags = _check(src)
    assert len(diags) == 2
    assert "Section-banner" in diags[0].message
    assert "Commented-out code" in diags[1].message


def test_single_dead_code_line_adjacent_to_live_code_still_fires():
    diags = _standalone("x = foo()")
    assert len(diags) == 1
    assert "Commented-out code" in diags[0].message


def test_generated_file_is_exempt():
    # Minimized from trio's _generated_instrumentation.py warning header.
    src = (
        "# ***********************************************************\n"
        "# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******\n"
        "# *************************************************************\n"
        "x = 1\n"
    )
    assert _check(src) == []


def test_sphinx_docs_conf_is_exempt():
    src = "# -- General configuration ------------------------------------------------\nextensions = []\n"
    rule = NoCommentCruft()
    assert rule.check(Path("docs/source/conf.py"), src) == []
    assert len(rule.check(Path("pkg/conf.py"), src)) == 1


def test_language_injection_pragma_is_exempt():
    # PyCharm language-injection directive above an embedded snippet
    # (pydantic's create_module tests).
    src = "x = 1\n# language=Python\ny = '<code>'\n"
    assert _check(src) == []


def test_step_narration_with_rationale_is_exempt():
    # Minimized from trio's _ssl.py: "First, ... because ..." carries a why.
    src = "x = 1\n# First, we take the outer send lock, because of standard semantics.\ny = 2\n"
    assert _check(src) == []


def test_step_narration_without_rationale_still_fires():
    src = "x = 1\n# First, take the lock.\ny = 2\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "narrates" in diags[0].message


# --------------------------------------------------------------------------- #
# FP guards found in a third-party sweep (httpx, flask, rich, pydantic).       #
# --------------------------------------------------------------------------- #


def test_doctest_block_including_its_output_is_exempt():
    # httpx/_client.py: the `>>>` lines document usage and the lines beneath
    # them are expected output, which looks exactly like commented-out code.
    src = """
def build():
    # So, eg...
    #
    # >>> client = Client(base_url="https://www.example.com/subpath")
    # >>> client.base_url
    # URL('https://www.example.com/subpath/')
    return 1
"""
    assert _check(src) == []


def test_commented_out_code_after_the_doctest_block_still_fires():
    src = """
def build():
    # >>> client = Client()
    # URL('https://example.com/')

    # return _legacy_path(url)
    return 1
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "cookie",
    ["# encoding=utf-8", "# -*- coding: utf-8 -*-", "# coding: latin-1"],
)
def test_pep263_coding_cookie_is_exempt(cookie: str):
    # rich carries these at the top of test modules; the interpreter reads them.
    assert _check(f"{cookie}\nx = 1\n") == []


def test_dot_banner_is_still_flagged():
    # Regression: a banner of dots begins with "...", so arming the doctest
    # exemption on that prefix silently disabled the banner check.
    src = """
# ....................
def f():
    return 1
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guards found in a 2,657-file sweep (pydantic, fastapi, black, flask, ...). #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        "insert_assert(exc_info.value.errors(include_url=False))",
        "insert_assert(Model.model_json_schema())",
        "insert_assert (m.foobar)",
    ],
)
def test_insert_assert_regeneration_recipe_is_exempt(body: str):
    # pydantic parks this above the assertion it writes; uncommenting it makes
    # pytest-examples rewrite the file, so git history never held the line.
    assert _standalone(body) == [], body


def test_other_commented_out_dev_tool_calls_still_fire():
    # The opposite case: `debug(...)` prints, it does not regenerate anything,
    # so a commented-out call to it is ordinary dead debugging code.
    for body in ("debug(v)", "insert_asserts(v)", "my_insert_assert(v)"):
        diags = _standalone(body)
        assert len(diags) == 1, body
        assert "Commented-out code" in diags[0].message


def test_snippet_block_under_colon_lead_in_survives_a_blank_comment_row():
    # flask/helpers.py: `# Original implementation:`, a blank `#`, then the
    # snippet — the lead-in is two rows up, not one.
    src = "x = 1\n# Original implementation:\n#\n#     session.setdefault('_f', []).append(c)\ny = 2\n"
    assert _check(src) == []


def test_snippet_block_covers_every_row_of_the_run():
    # black/comments.py: the second snippet row is indented under the first,
    # so its predecessor is code-shaped rather than prose.
    src = (
        "x = 1\n"
        "# The one-liner has been split across multiple lines:\n"
        "#     if True:\n"
        '#         print("a"); print("b")\n'
        "y = 2\n"
    )
    assert _check(src) == []


def test_snippet_block_ends_when_plain_prose_resumes():
    src = (
        "x = 1\n"
        "# Original implementation:\n"
        "#     session.setdefault('_f', []).append(c)\n"
        "# That assumed the session tracked mutations, which it does not.\n"
        "# self.retry()\n"
        "# self.log()\n"
        "y = 2\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6


def test_bare_block_keyword_lead_in_does_not_arm_a_snippet_block():
    # pydantic/v1/mypy.py: `# else:` announces nothing — it is dead code, and
    # the indented rows beneath it are the dead branch, not an illustration.
    src = "x = 1\n# else:\n#     v.is_staticmethod = True\n#     dec = Decorator(func, v)\ny = 2\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_prose_lead_in_without_a_colon_does_not_arm_a_snippet_block():
    # sqlmodel/tests/test_select_typing.py: a disabled test body under a plain
    # prose reason stays flagged past the first row.
    src = (
        "x = 1\n"
        "# check typing of select with 5 fields, which does not pass mypy yet\n"
        "# with Session(engine) as session:\n"
        "#     statement = select(Hero.id)\n"
        "#     results = session.exec(statement)\n"
        "y = 2\n"
    )
    diags = _check(src)
    assert [d.line for d in diags] == [4, 5]


@pytest.mark.parametrize(
    "prev",
    [
        "typing-extensions swallows one of the warnings, so we support",
        "strip trailing newline, not usually part of a text repr",
    ],
)
def test_narration_on_a_wrapped_sentence_tail_is_exempt(prev: str):
    # The why lives in the row above; this row is half a sentence.
    assert _check(f"x = 1\n# {prev}\n# both ways for now.\ny = 2\n") == []


@pytest.mark.parametrize("prev", ["we cache the parsed value here.", "see the note above:", "reuse it (cheaply)"])
def test_narration_after_a_finished_sentence_still_fires(prev: str):
    diags = _check(f"x = 1\n# {prev}\n# First, take the lock.\ny = 2\n")
    assert len(diags) == 1
    assert "narrates" in diags[0].message


def test_blank_comment_row_ends_the_paragraph_so_narration_still_fires():
    src = "x = 1\n# we keep two counters here\n#\n# First, take the lock.\ny = 2\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_letterless_line_art_header_is_not_a_preamble():
    # requests/__init__.py carries its logo as a four-line comment block.
    src = "#   __\n#  /__)  _  _     _   _ _/   _\n# / (   (- (/ (/ (- _)  /  _)\n#          /\nimport os\n"
    assert _check(src) == []


def test_header_preamble_with_a_single_letter_still_flags():
    src = "# a1\n# b2\n# c3\n# d4\nimport os\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "preamble" in diags[0].message


# --- region markers vs prose that opens with the word "region" ---------------


@pytest.mark.parametrize(
    "body",
    [
        "region",
        "endregion",
        "region helpers",
        "region: Constants",
        "endregion helpers",
        "region auth / session",
    ],
)
def test_region_marker_shapes_flag(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


@pytest.mark.parametrize(
    "body",
    [
        # demo-gateway/demos/momah-furas-anas/pipeline/matching.py:159 — a prose
        # comment whose first word happens to be "region".
        "region, sector AND facility_type are HARD constraints when the investor names them",
        "region is derived from the caller's IP, which the CDN rewrites",
        "regions are resolved lazily",
        "region names must stay lowercase; the API rejects mixed case.",
    ],
)
def test_prose_opening_with_region_is_not_a_marker(body: str):
    assert _standalone(body) == []


# --- ticket-bearing scoping notes --------------------------------------------


def test_meta_commentary_with_a_ticket_is_exempt():
    assert _standalone("EN-only for now; add an AR variant once AR audio exists (PROD-249)") == []


def test_meta_commentary_with_a_url_is_exempt():
    assert _standalone("hacky — mirrors https://example.com/api/quirk until they fix it") == []


def test_ticket_anywhere_in_the_run_exempts_the_whole_run():
    src = (
        "x = 1\n"
        "# Zoho freshness canary: the sink writes Description so Modified_Time advances.\n"
        "# EN-only for now (PROD-249).\n"
        "y = 2\n"
    )
    assert _check(src) == []


def test_meta_commentary_without_a_ticket_still_fires():
    diags = _standalone("quick fix, clean this up")
    assert len(diags) == 1
    assert "narrates" in diags[0].message


# --- SARJ016 extensions -------------------------------------------------------


@pytest.mark.parametrize("body", ["Constants", "Helpers", "Types", "Main", "Handlers:", "Hooks"])
def test_bare_section_label_flags(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "narrates" in diags[0].message


@pytest.mark.parametrize("body", ["Riyadh", "SAR", "seconds", "idempotent"])
def test_one_word_comment_outside_the_label_vocabulary_is_kept(body: str):
    assert _standalone(body) == []


@pytest.mark.parametrize(
    "body",
    [
        "Helper function to check if a path is active",
        "Helper component for header with tooltip",
        "A helper class to wrap the row",
    ],
)
def test_helper_opener_flags(body: str):
    diags = _standalone(body)
    assert len(diags) == 1
    assert "narrates" in diags[0].message


def test_lets_with_a_narration_verb_flags():
    diags = _standalone("Let's not await the promise")
    assert len(diags) == 1


@pytest.mark.parametrize(
    "body",
    [
        "lets a same-day re-run find the message it already posted",
        "Lets describeAppointmentWithUser skip the extra round-trip",
        "lets `.` match a newline",
    ],
)
def test_third_person_lets_is_kept(body: str):
    assert _standalone(body) == []


def test_isolated_enumeration_marker_flags():
    diags = _standalone("1. Load the config")
    assert len(diags) == 1
    assert "narrates" in diags[0].message


def test_enumeration_run_is_a_walkthrough_and_is_kept():
    src = "x = 1\n# 1. Load the config\ny = 2\n# 2. Reconcile the rows\nz = 3\n# 3. Emit\nw = 4\n"
    assert _check(src) == []


def test_isolated_phase_marker_flags():
    assert len(_standalone("Phase 2: reconcile")) == 1


def test_region_prose_with_a_full_stop_is_not_a_marker():
    # demo-gateway/.../voice/action/route.ts:1187 — a short noun phrase that
    # would pass the title shape if a sentence-final period were allowed.
    assert _standalone("Region centroids for map_pan.") == []


def test_section_label_inside_a_literal_groups_its_elements():
    # pydantic/pydantic/__init__.py:98 — `# config` sits inside `__all__`,
    # grouping the names beneath it rather than signposting the file.
    src = '__all__ = [\n    "model_serializer",\n    # config\n    "ConfigDict",\n]\n'
    assert _check(src) == []


def test_section_label_at_module_level_still_flags():
    diags = _check("import os\n\n# Constants\nMAX = 1\n")
    assert len(diags) == 1
    assert "narrates" in diags[0].message
