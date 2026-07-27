from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_fstring_over_concat import PreferFstringOverConcat


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


SRC_PATH = "python/bulbul/services/render.py"


def _check(source: str, path: str = SRC_PATH) -> list[Diagnostic]:
    return PreferFstringOverConcat().check(Path(path), textwrap.dedent(source))


# --------------------------------------------------------------------------- #
# The shapes the rule exists for.                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('msg = "user " + name + " failed"', id="literal-name-literal"),
        pytest.param('url = base + "/" + path', id="name-sep-name"),
        pytest.param('label = "id=" + str(user.id)', id="str-coercion"),
        pytest.param('greeting = "hello " + name', id="two-operand-prefix"),
        pytest.param('suffix = name + "!"', id="two-operand-suffix"),
        pytest.param('key = "prefix_" + record.identifier', id="attribute-operand"),
        pytest.param('key = "prefix_" + record["id"]', id="subscript-operand"),
        pytest.param('key = "prefix_" + compute()', id="call-operand"),
        pytest.param('key = "prefix_" + row[0].name.upper()', id="mixed-chain-operand"),
        pytest.param('body = "head\\n" + f"{value}"', id="fstring-operand"),
        pytest.param('masked = number[:6] + "****" + number[-4:]', id="masking"),
        pytest.param('path = "django.db.models" + tail.removeprefix("django")', id="dotted-path"),
        pytest.param('await_ed = "v" + (await fetch())', id="await-operand"),
        pytest.param('walrus = "v" + (found := lookup())', id="walrus-operand"),
    ],
)
def test_fires(source: str):
    assert len(_check(source)) == 1


def test_reports_position_of_the_whole_chain():
    diags = _check('\nvalue = "a" + name + "b"\n')
    assert (diags[0].line, diags[0].col) == (2, 9)
    assert diags[0].code == "SARJ060"


def test_reports_outermost_chain_only():
    assert len(_check('value = "a" + one + "b" + two + "c" + three')) == 1


def test_reports_each_independent_chain():
    assert len(_check('a = "x" + one\nb = "y" + two\n')) == 2


def test_message_mentions_dropping_str():
    (diag,) = _check('label = "id=" + str(user.id)')
    assert "str(...)" in diag.message


def test_message_omits_str_hint_without_a_str_call():
    (diag,) = _check('label = "id=" + user.id')
    assert "str(...)" not in diag.message


def test_message_suggests_join_for_long_chains():
    (diag,) = _check('v = "a" + b + "c" + d + "e" + f + "g"')
    assert "join" in diag.message


def test_message_omits_join_hint_for_short_chains():
    (diag,) = _check('v = "a" + b + "c"')
    assert "join" not in diag.message


# --------------------------------------------------------------------------- #
# false-positive guards: non-string `+` (the type-evidence requirement)        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("total = a + b", id="two-bare-names"),
        pytest.param("total = a + b + c", id="three-bare-names"),
        pytest.param("total = count + 1", id="int-literal"),
        pytest.param("total = amount + 1.5", id="float-literal"),
        pytest.param("total = flag + True", id="bool-literal"),
        pytest.param('blob = b"GET " + payload', id="bytes-literal"),
        pytest.param('blob = payload + b"\\r\\n"', id="bytes-literal-suffix"),
        pytest.param('mixed = "a" + name + b"z"', id="bytes-anywhere-in-chain"),
        pytest.param("merged = items + extras", id="list-concat-names"),
        pytest.param("when = start + delta", id="timedelta-shaped"),
        pytest.param("moved = Path(base) + suffix", id="domain-add-overload"),
        pytest.param("merged = xs + [1, 2]", id="list-literal-operand"),
        pytest.param("merged = xs + (1, 2)", id="tuple-literal-operand"),
    ],
)
def test_skips_without_string_literal_evidence(source: str):
    assert _check(source) == []


def test_fires_once_a_string_literal_joins_the_chain():
    # Same shape as `total = a + b`, with the one piece of type evidence added.
    assert len(_check('total = a + "-" + b')) == 1


def test_fires_on_bytes_shape_once_the_literal_is_str():
    assert len(_check('blob = "GET " + payload')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: logging (SARJ017 says the opposite there)            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('logger.info("call " + cid + " failed")', id="logger-info"),
        pytest.param('log.error("call " + cid)', id="log-error"),
        pytest.param('logging.warning("call " + cid)', id="logging-module"),
        pytest.param('self.logger.debug("call " + cid)', id="self-logger"),
        pytest.param('logger.bind(x=1).info("call " + cid)', id="loguru-bind-builder"),
        pytest.param('logging.getLogger(__name__).info("call " + cid)', id="getlogger-inline"),
        pytest.param('logger.exception("call " + cid)', id="logger-exception"),
        pytest.param('logger.info("msg", extra={"k": "v" + cid})', id="nested-in-logging-arg"),
    ],
)
def test_skips_logging_calls(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('warnings.warn("call " + cid, stacklevel=2)', id="warnings-warn-formats-eagerly"),
        pytest.param('console.log("call " + cid)', id="non-logger-receiver"),
        pytest.param('audit.info("call " + cid)', id="non-logger-named-receiver"),
        pytest.param('result = logger_name + " ready"', id="logger-shaped-name-not-a-call"),
    ],
)
def test_fires_outside_logging_calls(source: str):
    assert len(_check(source)) == 1


def test_fires_on_the_same_concat_outside_a_logger_receiver():
    # `logger.info("call " + cid)` is exempt; the identical expression assigned
    # to a variable is not.
    assert len(_check('message = "call " + cid')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: braces (regex / format templates)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(r'pattern = r"\s*\{" + re.escape(key) + r"\}\s*"', id="regex-with-braces"),
        pytest.param(r'pattern = r"(\d{4,6})(?!\s*" + CURRENCY + r")"', id="regex-repetition-braces"),
        pytest.param('template = fmt + "\\n{exception}"', id="loguru-template"),
        pytest.param('template = "{" + key + "}"', id="brace-wrapping"),
        pytest.param('template = "prefix }" + key', id="closing-brace-only"),
    ],
)
def test_skips_literals_containing_braces(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(r'pattern = r"\s*" + re.escape(key) + r"\s*"', id="regex-without-braces"),
        pytest.param('template = fmt + "\\nexception"', id="template-without-braces"),
    ],
)
def test_fires_when_the_braces_are_removed(source: str):
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: `%`-format template assembly                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('line = ("%0" + width + "d. %s") % (index, text)', id="width-in-template"),
        pytest.param('line = ("%" + str(arg)) % value', id="spec-in-template"),
    ],
)
def test_skips_percent_format_template_assembly(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('line = ("%0" + width + "d. %s")', id="template-not-applied"),
        pytest.param('line = value % ("%0" + width + "d")', id="chain-on-the-right-of-percent"),
    ],
)
def test_fires_when_the_chain_is_not_the_percent_left_operand(source: str):
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: `.join(...)` operands                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('msg = "routes:\\n" + "\\n".join(rows)', id="literal-then-join"),
        pytest.param('msg = " AND ".join(conds) + " LIMIT 1"', id="join-then-literal"),
        pytest.param('msg = "a" + sep.join(rows) + "b"', id="join-in-the-middle"),
        pytest.param('msg = "a" + os.path.join(root, name)', id="os-path-join-conservative"),
    ],
)
def test_skips_join_operands(source: str):
    assert _check(source) == []


def test_fires_when_the_join_is_replaced_by_a_plain_call():
    assert len(_check('msg = "routes:\\n" + render(rows)')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: string repetition                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('prompt = "A" * MIN_LENGTH + " tail"', id="literal-times-name"),
        pytest.param('bar = COUNT * "-" + title', id="name-times-literal"),
        pytest.param('sample = "x" + "\\n" * 51 + "y"', id="repetition-in-the-middle"),
    ],
)
def test_skips_string_repetition(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('prompt = prefix + " tail"', id="repetition-removed"),
        pytest.param('sample = "x" + middle + "y"', id="repetition-replaced-by-name"),
    ],
)
def test_fires_without_the_repetition(source: str):
    assert len(_check(source)) == 1


def test_skips_numeric_multiplication_operand_too():
    # `n * 3` carries no string literal of its own, but the chain still needs
    # its own literal to fire — and here it has one, so the guard must be the
    # string-repetition test, not a blanket Mult exclusion.
    assert len(_check('v = "n=" + n * 3')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: whitespace-only two-operand chains                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('out = json.dumps(payload) + "\\n"', id="trailing-newline"),
        pytest.param('out = "\\n" + body', id="leading-newline"),
        pytest.param('out = name + " "', id="trailing-space"),
        pytest.param('out = name + ""', id="empty-literal"),
        pytest.param('out = name + "\\t"', id="trailing-tab"),
    ],
)
def test_skips_two_operand_whitespace_terminators(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('out = first + " " + last', id="three-operands-still-fire"),
        pytest.param('out = json.dumps(payload) + "END"', id="non-whitespace-literal"),
        pytest.param('out = body + " ok"', id="whitespace-plus-text"),
    ],
)
def test_fires_when_the_whitespace_guard_does_not_apply(source: str):
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: lazy translation / SafeString operands               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('title = "Error: " + _("not found")', id="gettext-underscore"),
        pytest.param('title = "Error: " + gettext_lazy("not found")', id="gettext-lazy"),
        pytest.param('title = "Error: " + ngettext("a", "b", n)', id="ngettext"),
        pytest.param('title = "Error: " + translation.gettext("x")', id="dotted-gettext"),
        pytest.param('html = "<b>" + mark_safe(fragment)', id="mark-safe"),
        pytest.param('html = "<b>" + format_html("{}", value)', id="format-html"),
    ],
)
def test_skips_lazy_and_safe_string_operands(source: str):
    assert _check(source) == []


def test_fires_on_an_ordinary_call_operand():
    assert len(_check('title = "Error: " + describe("not found")')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: conditional-expression operands                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('order = ("-" if desc else "") + "datefield"', id="conditional-prefix"),
        pytest.param('clause = "SESSION" + (" UTC" if use_tz else "")', id="conditional-suffix"),
    ],
)
def test_skips_conditional_operands(source: str):
    assert _check(source) == []


def test_fires_when_the_conditional_is_hoisted_to_a_name():
    assert len(_check('order = sign + "datefield"')) == 1


def test_fires_when_the_whole_chain_is_a_conditional_branch():
    # The IfExp is the parent here, not an operand — the chain itself is plain.
    assert len(_check('order = ("-" + field) if desc else field')) == 1


# --------------------------------------------------------------------------- #
# false-positive guards: SQL fragments (defer to S608 / SARJ021)              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "SELECT * FROM " + table', id="select-from"),
        pytest.param('q = "DELETE FROM " + table', id="delete-from"),
        pytest.param('q = "... WHERE " + predicate', id="where"),
        pytest.param('q = "INSERT INTO " + table', id="insert-into"),
        pytest.param('q = "ORDER BY " + column', id="order-by"),
    ],
)
def test_skips_sql_fragments(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('note = "selected from " + source_name + " today"', id="keyword-not-at-the-end"),
        pytest.param('label = "Updated " + when', id="prose-not-sql"),
    ],
)
def test_fires_on_prose_that_merely_contains_sql_words(source: str):
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# file-scope gating and robustness                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "src/service.py",
        "tests/test_service.py",
        "conftest.py",
        "scripts/build.py",
    ],
)
def test_fires_everywhere_including_tests(path: str):
    # A general readability rule, not a test-scoped one: tests build ids and
    # fixtures with `"prefix_" + str(uuid7())` more than production code does.
    assert len(_check('name = "trunk_" + str(uuid7())', path)) == 1


@pytest.mark.parametrize(
    "header",
    [
        "# Code generated by Speakeasy. DO NOT EDIT.",
        "# This file was automatically generated by protoc.",
        "# @generated",
    ],
)
def test_skips_generated_files(header: str):
    assert _check(f'{header}\nvalue = "a" + name\n') == []


def test_fires_when_the_generated_header_is_absent():
    assert len(_check('# Hand written module\nvalue = "a" + name\n')) == 1


def test_syntax_error_source_is_silent():
    assert _check('def broken(:\n    x = "a" + name\n') == []


def test_source_without_plus_is_silent():
    assert _check('value = f"{name} ok"') == []


def test_diagnostics_are_sorted_by_position():
    diags = _check('a = "z" + one\nb = "y" + two\nc = "x" + three\n')
    assert [d.line for d in diags] == [1, 2, 3]


def test_augmented_assignment_operand_still_fires():
    assert len(_check('msg += " (" + reason + ")"')) == 1


def test_implicit_literal_concatenation_alone_is_silent():
    assert _check('msg = ("part one " "part two")') == []


def test_explicit_literal_only_concatenation_is_silent():
    # Ruff's ISC003 owns literal + literal; this rule requires a runtime operand.
    assert _check('msg = "part one " + "part two"') == []
