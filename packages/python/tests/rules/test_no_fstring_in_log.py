from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_fstring_in_log import NoFstringInLog


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoFstringInLog().check(Path("<t>.py"), source)


_LOG_METHODS = (
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "fatal",
    "trace",
    "success",
    "log",
)


@pytest.mark.parametrize("method", _LOG_METHODS)
def test_flags_fstring_in_every_log_method(method: str):
    diags = _check(f'logger.{method}(f"val {{x}}")\n')
    assert len(diags) == 1
    assert diags[0].code == "SARJ017"
    assert "keyword arguments" in diags[0].message


@pytest.mark.parametrize(
    "receiver",
    [
        "logger",
        "log",
        "logging",
        "loguru",
        "_logger",
        "_log",
    ],
)
def test_flags_every_bare_logger_name(receiver: str):
    assert len(_check(f'{receiver}.info(f"{{x}}")\n')) == 1


@pytest.mark.parametrize(
    "receiver",
    [
        "LOGGER",
        "Logger",
        "LOG",
        "Loguru",
        "_LOG",
    ],
)
def test_logger_name_match_is_case_insensitive(receiver: str):
    assert len(_check(f'{receiver}.info(f"{{x}}")\n')) == 1


@pytest.mark.parametrize(
    "receiver",
    [
        "self.logger",
        "self._log",
        "cls.logger",
        "app.logging",
        "a.b.logger",
        "foo.log",
        "self.loguru",
    ],
)
def test_flags_attribute_chain_ending_in_logger_name(receiver: str):
    assert len(_check(f'{receiver}.error(f"{{err}}")\n')) == 1


@pytest.mark.parametrize(
    "call",
    [
        'logger.bind(call_id=cid).info(f"done {x}")',
        'logger.opt(lazy=True).debug(f"v={value}")',
        'logger.getChild("sub").info(f"{v}")',
        'logger.bind(a=1).bind(b=2).info(f"{x}")',
    ],
)
def test_flags_builder_and_factory_chains(call: str):
    assert len(_check(call + "\n")) == 1


def test_flags_fstring_as_first_positional_with_trailing_kwargs():
    assert len(_check('logger.info(f"{x}", call_id=cid)\n')) == 1


def test_flags_fstring_as_first_positional_with_trailing_positional():
    assert len(_check('logger.info(f"first {x}", f"second {y}")\n')) == 1


def test_flags_nested_fstring():
    assert len(_check("logger.info(f\"outer {f'inner {x}'}\")\n")) == 1


def test_flags_fstring_inside_comprehension():
    assert len(_check('[logger.info(f"{i}") for i in items]\n')) == 1


def test_flags_fstring_inside_lambda():
    assert len(_check('cb = lambda: logger.info(f"{x}")\n')) == 1


def test_flags_multiline_call():
    assert len(_check('logger.info(\n    f"val {x}",\n)\n')) == 1


@pytest.mark.parametrize(
    "source",
    [
        'logger.info("call done", call_id=call_id)\n',
        'logger.info("nothing interpolated")\n',
        "logger.info('single quoted plain')\n",
        'logger.info("value %s and %d", name, count)\n',
        'logger.warning("%(key)s", {"key": v})\n',
    ],
)
def test_allows_plain_and_lazy_percent_style(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'logger.info(f"constant text")\n',
        'logger.debug(f"")\n',
        "logger.error(f'no placeholders here')\n",
    ],
)
def test_allows_fstring_without_interpolation(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'response.info(f"{x}")\n',
        'client.debug(f"{x}")\n',
        'self.metrics.error(f"{x}")\n',
        'obj.warning(f"{x}")\n',
    ],
)
def test_ignores_fstring_on_non_logger_receiver(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'logger.bind(context=f"{x}")\n',
        'logger.opt(record=f"{x}")\n',
        'logger.new(f"{x}")\n',
        'logger.remove(f"{x}")\n',
    ],
)
def test_ignores_fstring_on_non_log_method(source: str):
    assert _check(source) == []


def test_ignores_fstring_passed_as_keyword_argument():
    assert _check('logger.info("msg", detail=f"{x}")\n') == []


def test_ignores_log_call_with_level_as_first_positional():
    assert _check('logger.log(logging.INFO, f"msg {x}")\n') == []


def test_ignores_logger_attribute_access_without_call():
    assert _check("handler = logger.info\n") == []


@pytest.mark.parametrize(
    "source",
    [
        'print(f"{x}")\n',
        'sys.stdout.write(f"{x}")\n',
        'raise ValueError(f"bad {x}")\n',
        'f = f"{x}"\n',
    ],
)
def test_ignores_fstring_outside_any_logging_call(source: str):
    assert _check(source) == []


def test_documents_name_based_heuristic_flags_reassigned_local():
    assert len(_check("logger = build_response()\nlogger.info(f'{x}')\n")) == 1


def test_empty_source_returns_no_diagnostics():
    assert _check("") == []


@pytest.mark.parametrize(
    "source",
    [
        "def (:\n",
        "logger.info(f'{x}'\n",
        "class:\n",
    ],
)
def test_syntax_error_returns_empty(source: str):
    assert _check(source) == []


def test_multiple_violations_returned_in_line_order():
    src = 'logger.info(f"{a}")\nlogger.debug(f"{b}")\nlogger.error(f"{c}")\n'
    diags = _check(src)
    assert [d.line for d in diags] == [1, 2, 3]


@pytest.mark.parametrize(
    ("source", "line", "col"),
    [
        pytest.param('logger.info(f"val {x}")\n', 1, 13, id="single-line"),
        pytest.param('logger.info(\n    f"val {x}",\n)\n', 2, 5, id="multiline"),
    ],
)
def test_line_and_col_point_at_the_fstring(source: str, line: int, col: int):
    (diag,) = _check(source)
    assert (diag.line, diag.col) == (line, col)


def test_only_the_first_positional_argument_is_inspected():
    assert _check('logger.info("safe %s", f"{x}", f"{y}")\n') == []


def test_flags_implicit_concat_of_plain_and_fstring():
    assert len(_check('logger.info("prefix: " f"{x}")\n')) == 1


def test_flags_implicit_concat_fstring_then_plain():
    assert len(_check('logger.error(f"{x}" " suffix")\n')) == 1


@pytest.mark.parametrize(
    "source",
    [
        'logger.info(f"{x!r}")\n',
        'logger.info(f"{x:>10}")\n',
        'logger.info(f"{x:{width}}")\n',
    ],
)
def test_flags_fstring_with_conversion_or_format_spec(source: str):
    assert len(_check(source)) == 1


def test_allows_escaped_braces_only_fstring():
    assert _check('logger.info(f"{{x}} literal braces")\n') == []


def test_allows_str_format_call_as_first_arg():
    assert _check('logger.info("msg {}".format(x))\n') == []


@pytest.mark.parametrize(
    "receiver",
    [
        "catalog",
        "dialog",
        "backlog",
        "logout",
        "log_event",
        "blog",
    ],
)
def test_ignores_receiver_that_merely_contains_log_substring(receiver: str):
    assert _check(f'{receiver}.info(f"{{x}}")\n') == []


def test_flags_deep_builder_chain_bind_then_opt():
    assert len(_check('self.logger.bind(a=1).opt(lazy=True).info(f"{x}")\n')) == 1


def test_flags_structlog_get_logger_chain():
    assert len(_check('structlog.get_logger().info(f"{x}")\n')) == 1


@pytest.mark.parametrize(
    "source",
    [
        'import logging\nlogging.info(f"{x}")\n',
        'import logging as log\nlog.warning(f"slow {dt}")\n',
        'import logging.handlers\nlogging.error(f"{error}")\n',
    ],
    ids=["module", "aliased-module", "submodule-import"],
)
def test_suppresses_stdlib_module_logging_calls(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'import logging\nLOG = logging.getLogger(__name__)\nLOG.info(f"{x}")\n',
        'import logging\nlog: logging.Logger = logging.getLogger()\nlog.error(f"{x}")\n',
        'import logging\nself.logger = logging.getLogger()\nself.logger.warning(f"{x}")\n',
    ],
    ids=["assigned-name", "annotated-name", "assigned-attribute"],
)
def test_suppresses_names_bound_to_stdlib_loggers(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'logging.getLogger(__name__).info(f"{x}")\n',
        'logging.getLogger().bind(a=1).info(f"{x}")\n',
        'LOG = logging.getLogger()\nLOG.bind(a=1).info(f"{x}")\n',
    ],
    ids=["inline-factory", "inline-builder", "bound-builder"],
)
def test_suppresses_stdlib_factory_through_receiver_chain(source: str):
    assert _check(source) == []


@pytest.mark.parametrize("keyword", ["exc_info", "stack_info", "extra"])
def test_suppresses_calls_with_stdlib_only_keyword(keyword: str):
    assert _check(f'logger.error(f"{{error}}", {keyword}=value)\n') == []


def test_stdlib_attribute_binding_does_not_suppress_unrelated_logger():
    source = 'import logging\nself.logger = logging.getLogger()\nlogger.info(f"{x}")\n'
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'get_logger().info(f"{x}")\n',
        'get_logger(__name__).warning(f"slow {dt}")\n',
        'get_logger().bind(request_id=rid).info(f"{x}")\n',
        'getLogger().error(f"{x}")\n',
    ],
    ids=["snake-case", "snake-case-with-arg", "snake-case-builder", "camel-case"],
)
def test_bare_name_factory_is_suppressed_because_it_is_ambiguous(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'warnings.warn(f"{x}")\n',
        'console.log(f"{x}")\n',
    ],
    ids=["warnings", "rich-console"],
)
def test_non_logger_apis_with_log_method_names_are_ignored(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'logger.info(f"{x}" + "!")\n',
        'logger.info("value: " + f"{x}")\n',
    ],
    ids=["fstring-first", "fstring-last"],
)
def test_flags_interpolating_fstring_in_explicit_concatenation(source: str):
    assert len(_check(source)) == 1


def test_allows_explicit_concatenation_with_constant_fstring():
    assert _check('logger.info(f"constant" + "!")\n') == []
