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


def test_line_and_col_point_at_the_fstring_single_line():
    diags = _check('logger.info(f"val {x}")\n')
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 13


def test_line_and_col_point_at_the_fstring_multiline():
    diags = _check('logger.info(\n    f"val {x}",\n)\n')
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


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


def test_flags_fstring_concatenated_with_plus():
    assert len(_check('logger.info(f"{x}" + "!")\n')) == 1


def test_ignores_getchild_on_non_logger_receiver():
    assert _check('widget.getChild("panel").info(f"{x}")\n') == []


@pytest.mark.parametrize(
    "source",
    [
        'logging.getLogger(__name__).error(f"boom {x}", exc_info=e)\n',
        'logging.getLogger("svc").warning(f"slow {dt}")\n',
        'logging.getLogger("svc").getChild("sub").error(f"{e}")\n',
        'getLogger(__name__).info(f"{x}")\n',
    ],
)
def test_ignores_stdlib_getlogger_chain(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "kwarg",
    ["exc_info=e", "stack_info=True", 'extra={"k": 1}'],
)
def test_ignores_stdlib_only_kwargs(kwarg: str):
    assert _check(f'self.logger.error(f"Exception on {{path}}", {kwarg})\n') == []


def test_ignores_flask_style_self_logger_with_exc_info():
    assert _check('self.logger.error(f"Exception on {path}", exc_info=sys.exc_info())\n') == []


# --------------------------------------------------------------------------- #
# FP guard: a stdlib `logging` receiver. The structured-keyword fix raises      #
# `TypeError` on stdlib, so the rule must stay silent. Corpus: 70 of 94 hits.   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        'logging.info(f"Using config: {c}")',
        'logging.debug(f"Checking PR: #{n}")',
        'logging.error(f"Response was not 200, after: {a}")',
    ],
)
def test_ignores_stdlib_module_level_convenience_functions(call: str):
    assert _check(f"import logging\n\n{call}\n") == []


def test_ignores_aliased_stdlib_logging_module():
    assert _check('import logging as log\n\nlog.info(f"{x}")\n') == []


def test_ignores_submodule_import_binding_of_logging():
    assert _check('import logging.handlers\n\nlogging.info(f"{x}")\n') == []


def test_bare_logging_receiver_without_the_import_still_fires():
    # The opposite case: the exemption is import-backed, exactly like the
    # loguru-vs-hand-rolled distinction elsewhere — an unbacked name is a guess.
    assert len(_check('logging.info(f"{x}")\n')) == 1


@pytest.mark.parametrize(
    "binding",
    [
        "LOG = logging.getLogger(__name__)",
        "LOG: logging.Logger = logging.getLogger(__name__)",
        "LOG = getLogger(__name__)",
    ],
)
def test_ignores_module_level_logger_assigned_from_getlogger(binding: str):
    src = f'import logging\n\n{binding}\n\ndef f():\n    LOG.info(f"Cleaning up {{p}}")\n'
    assert _check(src) == []


def test_ignores_builder_chain_on_an_assigned_stdlib_logger():
    src = 'import logging\n\nLOG = logging.getLogger(__name__)\nLOG.getChild("s").info(f"{x}")\n'
    assert _check(src) == []


def test_same_name_assigned_from_a_non_getlogger_factory_still_fires():
    src = 'import logging\n\nLOG = loguru.logger.bind(a=1)\nLOG.info(f"{x}")\n'
    assert len(_check(src)) == 1


def test_stdlib_attribute_binding_does_not_poison_an_unrelated_bare_logger():
    # `self.logger = logging.getLogger(...)` binds `self.logger`, NOT `logger`;
    # matching on the loose name would silence every loguru call in the file.
    src = """
import logging
from loguru import logger

class C:
    def __init__(self):
        self.logger = logging.getLogger("c")

    def go(self):
        self.logger.info(f"stdlib {x}")

def f():
    logger.info(f"loguru {x}")
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 13


def test_flags_loguru_import_and_bare_logger():
    src = 'from loguru import logger\nlogger.info(f"val {x}")\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ017"


def test_still_flags_loguru_exception_method_without_stdlib_kwargs():
    assert len(_check('logger.exception(f"failed for {call_id}")\n')) == 1
