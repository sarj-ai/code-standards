from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_or_pattern import PreferOrPattern


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


SRC_PATH = "python/app/observability/setup.py"


def _check(source: str, path: str = SRC_PATH) -> list[Diagnostic]:
    return PreferOrPattern().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferOrPattern.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferOrPattern().check(Path(focus.path), focus.source)) == example.expected_count


# Core detection: adjacent arms repeating one body.                            #


_TWO_CLASS_ARMS = """
def f(cfg):
    match cfg:
        case SarjGroqSTTSettings():
            stt_model = None
        case SarjCustomSTTSettings():
            stt_model = None
        case _:
            assert_never(cfg)
    return stt_model
"""


def test_flags_two_adjacent_arms_with_identical_bodies():
    diags = _check(_TWO_CLASS_ARMS)
    assert len(diags) == 1
    assert diags[0].code == "SARJ070"
    assert "2 consecutive" in diags[0].message


def test_reports_at_the_first_arms_pattern():
    (diag,) = _check(_TWO_CLASS_ARMS)
    assert diag.line == 4
    assert diag.col == 14


def test_message_names_both_patterns():
    (diag,) = _check(_TWO_CLASS_ARMS)
    assert "SarjGroqSTTSettings()" in diag.message
    assert "SarjCustomSTTSettings()" in diag.message


def test_message_text_is_exact():
    (diag,) = _check(_TWO_CLASS_ARMS)
    assert diag.message == (
        "2 consecutive `case` arms repeat an identical body — merge them into one "
        "or-pattern (`case SarjGroqSTTSettings() | SarjCustomSTTSettings():`) so the "
        "shared handling is written once."
    )


def test_flags_a_run_of_four_arms_once():
    diags = _check(
        """
        def f(tts):
            match tts:
                case CartesiaTTSSettings(voice=voice):
                    tts_voice = voice
                case DeepgramTTSSettings(voice=voice):
                    tts_voice = voice
                case SarjF5TTSSettings(voice=voice):
                    tts_voice = voice
                case SarjOmniTTSSettings(voice=voice):
                    tts_voice = voice
            return tts_voice
        """
    )
    assert len(diags) == 1
    assert "4 consecutive" in diags[0].message


def test_reports_two_separate_runs_in_one_match():
    diags = _check(
        """
        def f(x):
            match x:
                case A():
                    return 1
                case B():
                    return 1
                case C():
                    return 2
                case D():
                    return 3
                case E():
                    return 3
        """
    )
    assert len(diags) == 2
    assert [d.line for d in diags] == [4, 10]


def test_reports_each_match_statement_separately():
    diags = _check(
        """
        def f(x, y):
            match x:
                case A():
                    return 1
                case B():
                    return 1
            match y:
                case C():
                    return 2
                case D():
                    return 2
        """
    )
    assert len(diags) == 2


def test_finds_a_match_nested_inside_another_arm():
    diags = _check(
        """
        def f(outer, inner):
            match outer:
                case Wrapper():
                    match inner:
                        case A():
                            return 1
                        case B():
                            return 1
                case _:
                    return 0
        """
    )
    assert len(diags) == 1
    assert diags[0].line == 6


@pytest.mark.parametrize(
    ("pattern_a", "pattern_b"),
    [
        pytest.param("Kind.A", "Kind.B", id="enum-value-patterns"),
        pytest.param('"a"', '"b"', id="string-literal-patterns"),
        pytest.param("[1, x]", "[2, x]", id="sequence-patterns"),
        pytest.param('{"a": x}', '{"b": x}', id="mapping-patterns"),
        pytest.param("None", "True", id="singleton-patterns"),
        pytest.param("A() | B()", "C()", id="existing-or-pattern-extended"),
        pytest.param("A(x=x)", "B() as x", id="mixed-capture-shapes"),
    ],
)
def test_flags_every_refutable_pattern_kind(pattern_a: str, pattern_b: str):
    binds_x = "x" in pattern_a
    body = "return x" if binds_x else "return 1"
    diags = _check(
        f"""
        def f(v):
            match v:
                case {pattern_a}:
                    {body}
                case {pattern_b}:
                    {body}
        """
    )
    assert len(diags) == 1


def test_flags_multi_statement_identical_bodies():
    diags = _check(
        """
        def f(err):
            match err:
                case PartnerErrorCode.INVITATION_CODE_INVALID:
                    error_type = PartnerErrorType.INVALID_INVITATION_CODE
                    localization_slug = "error_invalid_invitation_code"
                    ui_type = "simple"
                case PartnerErrorCode.INVITATION_CODE_NOT_EXIST:
                    error_type = PartnerErrorType.INVALID_INVITATION_CODE
                    localization_slug = "error_invalid_invitation_code"
                    ui_type = "simple"
            return error_type
        """
    )
    assert len(diags) == 1


def test_flags_arms_that_bind_the_same_name_at_different_positions():
    diags = _check(
        """
        def f(v):
            match v:
                case [x, _]:
                    return x
                case [_, x]:
                    return x
        """
    )
    assert len(diags) == 1


# false-positive guards — guarded arms                                         #


def test_skips_run_when_the_first_arm_is_guarded():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A() if v.ready:
                        return 1
                    case B():
                        return 1
            """
        )
        == []
    )


def test_skips_run_when_the_second_arm_is_guarded():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
                    case B() if v.ready:
                        return 1
            """
        )
        == []
    )


def test_flags_the_same_pair_once_the_guard_is_removed():
    assert (
        len(
            _check(
                """
                def f(v):
                    match v:
                        case A():
                            return 1
                        case B():
                            return 1
                """
            )
        )
        == 1
    )


def test_guarded_arm_breaks_a_run_in_two():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    return 1
                case B() if v.ready:
                    return 1
                case C():
                    return 1
                case D():
                    return 1
        """
    )
    assert len(diags) == 1
    assert diags[0].line == 8


# false-positive guards — irrefutable arms                                     #


@pytest.mark.parametrize(
    "wildcard",
    [pytest.param("_", id="bare-wildcard"), pytest.param("rest", id="bare-capture")],
)
def test_skips_an_irrefutable_arm(wildcard: str):
    assert (
        _check(
            f"""
            def f(v):
                match v:
                    case A():
                        return 1
                    case {wildcard}:
                        return 1
            """
        )
        == []
    )


def test_as_pattern_with_a_subpattern_is_refutable_and_still_flagged():
    diags = _check(
        """
        def f(v):
            match v:
                case A() as hit:
                    return hit
                case B() as hit:
                    return hit
        """
    )
    assert len(diags) == 1


# false-positive guards — differing bodies                                     #


def test_skips_arms_whose_bodies_differ():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
                    case B():
                        return 2
            """
        )
        == []
    )


def test_skips_arms_whose_bodies_have_different_lengths():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        log()
                        return 1
                    case B():
                        return 1
            """
        )
        == []
    )


def test_skips_arms_whose_bodies_share_a_first_statement_but_differ_in_length():
    """The length check must run *before* the element-wise compare."""
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        log()
                        return 1
                    case B():
                        log()
            """
        )
        == []
    )


def test_flags_the_same_shared_prefix_once_the_bodies_are_the_same_length():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    log()
                    return 1
                case B():
                    log()
                    return 1
        """
    )
    assert len(diags) == 1


def test_skips_arms_that_differ_only_in_a_nested_literal():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return handle(mode="fast")
                    case B():
                        return handle(mode="slow")
            """
        )
        == []
    )


# false-positive guards — comments distinguishing the arms                     #


def test_skips_arms_with_different_trailing_comments():
    assert (
        _check(
            """
            def f(period):
                match period:
                    case TimePeriod.WEEK:
                        granularity = TimeGranularity.DAY  # 7 data points
                    case TimePeriod.MONTH:
                        granularity = TimeGranularity.DAY  # 30-31 data points
                return granularity
            """
        )
        == []
    )


def test_flags_the_same_pair_when_the_comments_match():
    diags = _check(
        """
        def f(period):
            match period:
                case TimePeriod.WEEK:
                    granularity = TimeGranularity.DAY  # coarse
                case TimePeriod.MONTH:
                    granularity = TimeGranularity.DAY  # coarse
            return granularity
        """
    )
    assert len(diags) == 1


def test_skips_when_only_one_arm_carries_a_comment():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1  # the common case
                    case B():
                        return 1
            """
        )
        == []
    )


def test_skips_when_a_comment_sits_between_the_arms():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
                    # providers that do not expose a model
                    case B():
                        return 1
            """
        )
        == []
    )


def test_flags_the_same_pair_once_the_separating_comment_is_gone():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    return 1

                case B():
                    return 1
        """
    )
    assert len(diags) == 1


def test_a_comment_on_the_second_arms_case_line_is_not_a_gap_comment():
    """The gap ends one line *above* the second `case`."""
    diags = _check(
        """
        def f(v):
            match v:
                case A():  # provider
                    return 1
                case B():  # provider
                    return 1
        """
    )
    assert len(diags) == 1


def test_differing_comments_on_the_case_lines_still_suppress():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():  # the cheap provider
                        return 1
                    case B():  # the expensive provider
                        return 1
            """
        )
        == []
    )


def test_a_comment_after_the_run_does_not_suppress_it():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    return 1
                case B():
                    return 1
                # everything else is unsupported
                case _:
                    raise ValueError(v)
        """
    )
    assert len(diags) == 1


# false-positive guards — illegal merges (different bound names)               #


def test_skips_arms_binding_different_names():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case ast.MatchAs(name=bound):
                        return bound == name
                    case ast.MatchMapping(rest=rest):
                        return rest == name
            """
        )
        == []
    )


def test_flags_the_same_pair_once_the_names_agree():
    diags = _check(
        """
        def f(v):
            match v:
                case ast.MatchAs(name=bound):
                    return bound == name
                case ast.MatchMapping(rest=bound):
                    return bound == name
        """
    )
    assert len(diags) == 1


def test_skips_when_one_arm_binds_a_name_the_other_does_not():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
                    case B(x=x):
                        return 1
            """
        )
        == []
    )


def test_skips_when_star_captures_use_different_names():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case [1, *head]:
                        return handle()
                    case [2, *tail]:
                        return handle()
            """
        )
        == []
    )


def test_flags_star_captures_that_share_a_name():
    diags = _check(
        """
        def f(v):
            match v:
                case [1, *rest]:
                    return rest
                case [2, *rest]:
                    return rest
        """
    )
    assert len(diags) == 1


def test_skips_when_mapping_rest_names_differ():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case {"a": 1, **extra}:
                        return handle()
                    case {"b": 2, **other}:
                        return handle()
            """
        )
        == []
    )


# false-positive guards — empty bodies                                         #


@pytest.mark.parametrize(
    "body",
    [pytest.param("pass", id="pass"), pytest.param("...", id="ellipsis")],
)
def test_skips_arms_whose_shared_body_is_empty(body: str):
    assert (
        _check(
            f"""
            def f(v):
                match v:
                    case A():
                        {body}
                    case B():
                        {body}
            """
        )
        == []
    )


def test_flags_the_same_pair_once_the_body_does_something():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    ignored.append(v)
                case B():
                    ignored.append(v)
        """
    )
    assert len(diags) == 1


def test_empty_arm_breaks_a_run():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        pass
                    case B():
                        pass
                    case C():
                        pass
            """
        )
        == []
    )


def test_a_docstring_style_string_body_is_not_treated_as_empty():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    "noted"
                case B():
                    "noted"
        """
    )
    assert len(diags) == 1


# false-positive guards — non-adjacent arms                                    #


def test_skips_non_adjacent_arms_with_the_same_body():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
                    case B():
                        return 2
                    case C():
                        return 1
            """
        )
        == []
    )


def test_flags_the_same_arms_once_they_are_adjacent():
    diags = _check(
        """
        def f(v):
            match v:
                case A():
                    return 1
                case C():
                    return 1
                case B():
                    return 2
        """
    )
    assert len(diags) == 1


def test_identical_bodies_in_different_matches_are_not_merged():
    assert (
        _check(
            """
            def f(x, y):
                match x:
                    case A():
                        return 1
                match y:
                    case B():
                        return 1
            """
        )
        == []
    )


# path gating and robustness                                                   #


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("src/service.py", id="src-module"),
        pytest.param("tests/test_thing.py", id="test-module"),
        pytest.param("scripts/one_off.py", id="script"),
        pytest.param("conftest.py", id="conftest"),
    ],
)
def test_fires_regardless_of_path(path: str):
    assert len(_check(_TWO_CLASS_ARMS, path)) == 1


def test_syntax_error_source_yields_no_diagnostics():
    assert PreferOrPattern().check(Path(SRC_PATH), "def f(:\n    match\n") == []


def test_empty_source_yields_no_diagnostics():
    assert PreferOrPattern().check(Path(SRC_PATH), "") == []


def test_module_without_any_match_yields_no_diagnostics():
    assert (
        _check(
            """
            def f(v):
                if isinstance(v, A):
                    return 1
                if isinstance(v, B):
                    return 1
                return 0
            """
        )
        == []
    )


def test_single_arm_match_yields_no_diagnostics():
    assert (
        _check(
            """
            def f(v):
                match v:
                    case A():
                        return 1
            """
        )
        == []
    )


def test_diagnostics_are_sorted_by_position():
    diags = _check(
        """
        def f(x, y):
            match y:
                case C():
                    return 2
                case D():
                    return 2
            match x:
                case A():
                    return 1
                case B():
                    return 1
        """
    )
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_a_long_pattern_uses_a_concise_description_instead_of_invalid_syntax():
    diags = _check(
        """
        def f(v):
            match v:
                case AWSSTTSettings() | AzureSTTSettings() | ElevenLabsSTTSettings() | HamsaSTTSettings():
                    stt_model = None
                case SarjGroqSTTSettings():
                    stt_model = None
        """
    )
    assert len(diags) == 1
    assert "(`case " not in diags[0].message
    assert "into one or-pattern so" in diags[0].message


_PREVIEW_AT_LIMIT = f"C{'x' * 87}() | B()"
_PREVIEW_OVER_LIMIT = f"C{'x' * 88}() | B()"


def test_a_complete_preview_at_the_render_limit_is_kept_whole():
    assert len(_PREVIEW_AT_LIMIT) == 96
    diags = _check(
        f"""
        def f(v):
            match v:
                case C{"x" * 87}():
                    stt_model = None
                case B():
                    stt_model = None
        """
    )
    assert len(diags) == 1
    assert _PREVIEW_AT_LIMIT in diags[0].message


def test_a_preview_over_the_render_limit_is_omitted_whole():
    assert len(_PREVIEW_OVER_LIMIT) == 97
    diags = _check(
        f"""
        def f(v):
            match v:
                case C{"x" * 88}():
                    stt_model = None
                case B():
                    stt_model = None
        """
    )
    assert len(diags) == 1
    assert _PREVIEW_OVER_LIMIT not in diags[0].message
    assert "(`case " not in diags[0].message


def test_preview_is_valid_syntax_for_multiline_patterns_with_captures():
    (diag,) = _check(
        """
        def f(v):
            match v:
                case First(
                    value=token,
                ):
                    return token
                case Second(
                    value=token,
                ):
                    return token
        """
    )
    preview = diag.message.split("(`case ", maxsplit=1)[1].split(":`)", maxsplit=1)[0]
    assert compile(f"match v:\n    case {preview}:\n        pass\n", "<suggested pattern>", "exec") is not None


def test_preview_parenthesizes_as_patterns_around_an_existing_or_pattern() -> None:
    (diag,) = _check(
        """
        def f(value):
            match value:
                case (A() | B()) as item:
                    return item
                case C() as item:
                    return item
        """
    )

    preview = diag.message.split("(`case ", maxsplit=1)[1].split(":`)", maxsplit=1)[0]
    assert compile(f"match value:\n    case {preview}:\n        pass\n", "<suggested pattern>", "exec") is not None
    assert preview == "(A() | B() as item) | (C() as item)"


def test_run_inside_a_loop_body_is_found():
    diags = _check(
        """
        def f(items):
            for item in items:
                match item:
                    case A():
                        continue
                    case B():
                        continue
        """
    )
    assert len(diags) == 1


def test_run_inside_a_class_method_is_found():
    diags = _check(
        """
        class Handler:
            def dispatch(self, v):
                match v:
                    case A():
                        return self.a()
                    case B():
                        return self.a()
        """
    )
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (5, 18)


def test_run_inside_a_with_block_reports_the_nested_position():
    diags = _check(
        """
        def f(v):
            with open(path) as handle:
                match v:
                    case A():
                        handle.write("a")
                    case B():
                        handle.write("a")
        """
    )
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (5, 18)


def test_async_function_body_is_found():
    diags = _check(
        """
        async def f(v):
            match v:
                case A():
                    await run(v)
                case B():
                    await run(v)
        """
    )
    assert len(diags) == 1


def test_rule_metadata():
    rule = PreferOrPattern()
    assert rule.id == "prefer-or-pattern"
    assert rule.code == "SARJ070"
    assert len(rule.description) >= 10
