"""Direct tests for the logger-receiver resolver shared by SARJ012/SARJ017 (and SARJ062).

The module exists so the secret-in-log and f-string-in-log rules recognise the
same receiver forms. A gap here is a SILENT false negative in every consumer at
once -- which is exactly how `get_logger().info(...)`, structlog's own documented
module-level idiom, went unlinted by both rules.
"""

import ast

import pytest

from sarj_python_lint.rules._logging import LOGGER_FACTORIES, is_logger_expr


def _expr(source: str) -> ast.expr:
    call = ast.parse(source, mode="eval").body
    assert isinstance(call, ast.Call)
    receiver = call.func
    assert isinstance(receiver, ast.Attribute)
    return receiver.value


@pytest.mark.parametrize(
    "source",
    [
        'logger.info("x")',
        'log.warning("x")',
        'logging.info("x")',
        '_logger.info("x")',
        '_log.info("x")',
        'LOGGER.info("x")',
        'self.logger.error("x")',
        'logger.bind(a=1).info("x")',
        'logger.opt(lazy=True).debug("x")',
        'logging.getLogger(__name__).info("x")',
        'structlog.get_logger().info("x")',
        'get_logger().info("x")',
        'get_logger(__name__).bind(a=1).info("x")',
    ],
)
def test_every_receiver_shape_that_evaluates_to_a_logger(source: str) -> None:
    assert is_logger_expr(_expr(source))


def test_a_bare_name_factory_only_counts_when_it_is_called() -> None:
    """`get_logger()` is a logger; the bare name `get_logger` is a function.

    That is why the factories live in their own set rather than in the logger
    NAMES set -- and why the bare-callee branch has to exist: a bare callee is an
    `ast.Name`, and recursing on it lands in the names branch, which by design
    does not carry the factory names.
    """
    assert is_logger_expr(_expr('get_logger().info("x")'))
    assert not is_logger_expr(_expr('get_logger.info("x")'))


@pytest.mark.parametrize(
    "source",
    [
        'response.info("x")',
        'self.client.info("x")',
        'make_thing().info("x")',
        '"literal".info("x")',
    ],
)
def test_a_non_logger_receiver_is_not_mistaken_for_one(source: str) -> None:
    assert not is_logger_expr(_expr(source))


def test_receiver_names_are_matched_case_insensitively() -> None:
    """`getLogger` and `getlogger` must resolve the same way in every branch.

    The set is exported so `no_fstring_in_log` tests the SAME names with the
    same casing; a divergence makes a factory a logger to one rule and not the
    other.
    """
    assert frozenset({"getlogger", "get_logger"}) == LOGGER_FACTORIES
    assert is_logger_expr(_expr('LOGGER.info("x")'))
    assert is_logger_expr(_expr('GetLogger().info("x")'))
    assert is_logger_expr(_expr('self.Logger.info("x")'))
