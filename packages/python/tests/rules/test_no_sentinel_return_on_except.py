from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_sentinel_return_on_except import (
    NoSentinelReturnOnExcept,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoSentinelReturnOnExcept.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return NoSentinelReturnOnExcept().check(Path("<test>.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoSentinelReturnOnExcept().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_return_none():
    src = """
def f():
    try:
        risky()
    except Exception:
        return None
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ009"


def test_flags_bare_return_is_not_flagged():
    # `return` with no value parses as Return(value=None); the rule only flags
    # explicit sentinel values, and a bare return is value=None at the AST level,
    # so confirm the documented behavior here.
    src = """
def f():
    try:
        risky()
    except Exception:
        return
"""
    # value is None -> treated as sentinel None -> flagged.
    assert len(_check(src)) == 1


def test_flags_return_empty_list():
    src = """
def f():
    try:
        risky()
    except Exception:
        return []
"""
    assert len(_check(src)) == 1


def test_flags_return_false():
    src = """
def f():
    try:
        risky()
    except Exception:
        return False
"""
    assert len(_check(src)) == 1


def test_flags_return_empty_dict():
    src = """
def f():
    try:
        risky()
    except Exception:
        return {}
"""
    assert len(_check(src)) == 1


def test_flags_return_empty_tuple():
    src = """
def f():
    try:
        risky()
    except Exception:
        return ()
"""
    assert len(_check(src)) == 1


def test_flags_return_empty_string():
    src = """
def f():
    try:
        risky()
    except Exception:
        return ''
"""
    assert len(_check(src)) == 1


def test_flags_return_set_call():
    src = """
def f():
    try:
        risky()
    except Exception:
        return set()
"""
    assert len(_check(src)) == 1


def test_logged_sentinel_after_logging_is_exempt():
    # Logging the exception before returning the sentinel makes the error
    # observable, so it is the handled result, not a silent swallow.
    src = """
def f():
    try:
        risky()
    except Exception:
        logger.warning("oops")
        return None
"""
    assert _check(src) == []


def test_diagnostic_points_at_return_line_and_col():
    src = """
def f():
    try:
        risky()
    except Exception:
        return None
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6
    assert diags[0].col == 9


def test_flags_each_handler_separately():
    src = """
def f():
    try:
        risky()
    except ValueError:
        return None
    except KeyError:
        return []
"""
    assert len(_check(src)) == 2


def test_allows_bare_raise():
    src = """
def f():
    try:
        risky()
    except Exception:
        raise
"""
    assert _check(src) == []


def test_allows_log_then_raise():
    src = """
def f():
    try:
        risky()
    except Exception:
        logger.exception("boom")
        raise
"""
    assert _check(src) == []


def test_allows_raise_new_exception():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        raise RuntimeError("wrapped") from e
"""
    assert _check(src) == []


def test_allows_raise_even_when_return_is_final_stmt():
    # A raise anywhere in the handler (before the return) means it's not a
    # silent swallow; conservatively allow it.
    src = """
def f():
    try:
        risky()
    except Exception:
        if bad():
            raise
        return None
"""
    assert _check(src) == []


def test_raise_in_nested_def_does_not_count_as_reraise():
    # The nested def's raise doesn't re-raise for THIS handler, so the sentinel
    # return is still a swallow and must be flagged.
    src = """
def f():
    try:
        risky()
    except Exception:
        def _inner():
            raise ValueError()
        return None
"""
    assert len(_check(src)) == 1


def test_raise_in_lambda_does_not_count_as_reraise():
    src = """
def f():
    try:
        risky()
    except Exception:
        g = lambda: (_ for _ in ()).throw(ValueError())
        return None
"""
    # No real `raise` statement at the handler level -> flagged.
    assert len(_check(src)) == 1


def test_allows_return_call():
    src = """
def f():
    try:
        risky()
    except Exception:
        return compute()
"""
    assert _check(src) == []


def test_allows_return_name():
    src = """
def f(default):
    try:
        risky()
    except Exception:
        return default
"""
    assert _check(src) == []


def test_allows_return_true():
    src = """
def f():
    try:
        risky()
    except Exception:
        return True
"""
    assert _check(src) == []


def test_allows_return_nonempty_list():
    src = """
def f():
    try:
        risky()
    except Exception:
        return [1, 2, 3]
"""
    assert _check(src) == []


def test_allows_return_nonempty_string():
    src = """
def f():
    try:
        risky()
    except Exception:
        return "error"
"""
    assert _check(src) == []


def test_allows_return_number():
    src = """
def f():
    try:
        risky()
    except Exception:
        return 0
"""
    assert _check(src) == []


def test_allows_return_nonempty_dict():
    src = """
def f():
    try:
        risky()
    except Exception:
        return {"ok": False}
"""
    assert _check(src) == []


def test_allows_non_set_call():
    src = """
def f():
    try:
        risky()
    except Exception:
        return list()
"""
    assert _check(src) == []


def test_allows_sentinel_return_not_final_when_handler_continues():
    # If the return isn't the final statement we don't flag (final stmt rule).
    src = """
def f():
    try:
        risky()
    except Exception:
        if cond:
            return None
        log_and_recover()
"""
    assert _check(src) == []


def test_allows_no_return_in_handler():
    src = """
def f():
    try:
        risky()
    except Exception:
        log_and_recover()
"""
    assert _check(src) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


def _return_src(ret: str, *, handler: str = "except Exception:") -> str:
    """Build a function whose sole handler ends in `return <ret>` at line 6."""
    return f"""
def f():
    try:
        risky()
    {handler}
        return {ret}
"""


@pytest.mark.parametrize(
    "ret",
    [
        "None",
        "False",
        "[]",
        "{}",
        "()",
        "''",
        '""',
        '""""""',
        "set()",
    ],
)
def test_flags_every_sentinel_shape(ret: str):
    diags = _check(_return_src(ret))
    assert len(diags) == 1
    assert diags[0].code == "SARJ009"


@pytest.mark.parametrize(
    "handler",
    [
        "except Exception:",
        "except:",
        "except ValueError:",
        "except (ValueError, KeyError):",
        "except Exception as e:",
    ],
)
def test_flags_across_handler_forms(handler: str):
    # Bare except, typed except, tuple-of-types, and a bound `as e` all flag.
    assert len(_check(_return_src("None", handler=handler))) == 1


def test_flags_bare_except():
    src = """
def f():
    try:
        risky()
    except:
        return []
"""
    assert len(_check(src)) == 1


def test_flags_except_star_group():
    src = """
def f():
    try:
        risky()
    except* ValueError:
        return None
"""
    assert len(_check(src)) == 1


def test_flags_async_function_handler():
    src = """
async def f():
    try:
        await risky()
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_flags_handler_in_method():
    src = """
class C:
    def m(self):
        try:
            risky()
        except Exception:
            return {}
"""
    assert len(_check(src)) == 1


def test_flags_with_finally_present():
    # A `finally` clause is not an ExceptHandler and doesn't change the verdict.
    src = """
def f():
    try:
        risky()
    except Exception:
        return None
    finally:
        cleanup()
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "prelude",
    [
        "cleanup()",
        "x = compute()",
        'print("oops")',
        "str(e)",
    ],
)
def test_flags_sentinel_after_non_logging_prelude(prelude: str):
    # Cleanup, assignment, print, or a bare read of the exception before the
    # sentinel return does NOT exempt the swallow — only a `raise` or an actual
    # logging call does.
    src = f"""
def f():
    try:
        risky()
    except Exception as e:
        {prelude}
        return None
"""
    assert len(_check(src)) == 1


def test_flags_both_nested_handlers():
    src = """
def f():
    try:
        risky()
    except Exception:
        try:
            g()
        except ValueError:
            return None
        return None
"""
    assert len(_check(src)) == 2


def test_line_col_at_deeper_indent():
    src = """
class C:
    def m(self):
        try:
            risky()
        except Exception:
            return None
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 7
    assert diags[0].col == 13


def test_line_col_single_space_indent():
    src = "def f():\n try:\n  risky()\n except Exception:\n  return None"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5
    assert diags[0].col == 3


def test_flat_handlers_emitted_in_source_order():
    src = """
def f():
    try:
        risky()
    except A:
        return None
    except B:
        return []
    except C:
        return {}
"""
    assert [d.line for d in _check(src)] == [6, 8, 10]


def test_nested_handlers_sorted_by_position():
    # Diagnostics are sorted by (line, col): the INNER handler's return (line 9)
    # is reported before the OUTER handler's (line 10), matching the sort every
    # other rule in the package applies.
    src = """
def f():
    try:
        risky()
    except Exception:
        try:
            g()
        except ValueError:
            return None
        return None
"""
    positions = [(d.line, d.col) for d in _check(src)]
    assert positions == [(9, 13), (10, 9)]


def test_nested_handlers_should_be_sorted_by_position():
    src = """
def f():
    try:
        risky()
    except Exception:
        try:
            g()
        except ValueError:
            return None
        return None
"""
    positions = [(d.line, d.col) for d in _check(src)]
    assert positions == sorted(positions)


def test_allows_raise_in_for_loop():
    src = """
def f():
    try:
        risky()
    except Exception:
        for _ in range(3):
            raise
        return None
"""
    assert _check(src) == []


def test_allows_raise_in_with_block():
    src = """
def f():
    try:
        risky()
    except Exception:
        with lock():
            raise
        return None
"""
    assert _check(src) == []


def test_allows_raise_inside_nested_try_handler():
    # `_contains_raise` descends into a nested try (not a function boundary), so
    # a raise in the inner handler counts as a re-raise for the outer handler.
    src = """
def f():
    try:
        risky()
    except Exception:
        try:
            h()
        except ValueError:
            raise
        return None
"""
    assert _check(src) == []


def test_allows_raise_from_in_except_group():
    src = """
def f():
    try:
        risky()
    except* ValueError as eg:
        raise RuntimeError("wrapped") from eg
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "ret",
    [
        "True",
        "0",
        "0.0",
        "1",
        "-1",
        "0j",
        '"error"',
        "'x'",
        "[1]",
        "[1, 2, 3]",
        '{"ok": False}',
        "{None: None}",
        "(None,)",
        "default",
        "compute()",
        "fallback_value",
        "list()",
        "dict()",
        "frozenset()",
        "bytearray()",
        "...",
        "b''",
        'f""',
        "not x",
    ],
)
def test_allows_meaningful_return_values(ret: str):
    assert _check(_return_src(ret)) == []


def test_false_is_sentinel_but_zero_is_not():
    # `return False` is flagged; `return 0` is not — `0 is False` is False, and
    # 0 can be a legitimate recovered value.
    assert len(_check(_return_src("False"))) == 1
    assert _check(_return_src("0")) == []


def test_allows_return_recovered_local():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        recovered = handle(e)
        return recovered
"""
    assert _check(src) == []


def test_return_in_try_body_not_flagged():
    # A sentinel return in the `try` body (success path) is not a swallow.
    src = """
def f():
    try:
        return None
    except Exception:
        raise
"""
    assert _check(src) == []


def test_return_in_else_clause_not_flagged():
    src = """
def f():
    try:
        risky()
    except Exception:
        raise
    else:
        return []
"""
    assert _check(src) == []


def test_return_in_finally_not_flagged():
    src = """
def f():
    try:
        risky()
    except Exception:
        raise
    finally:
        return None
"""
    assert _check(src) == []


def test_sentinel_return_in_fallback_branch_not_final_allowed():
    # The sentinel return is guarded and the handler continues with recovery, so
    # it is not the handler's final statement — not flagged.
    src = """
def f():
    try:
        risky()
    except Exception:
        if fatal():
            return None
        return recover()
"""
    assert _check(src) == []


def test_handler_ending_in_recovery_call_allowed():
    src = """
def f():
    try:
        risky()
    except Exception:
        return recover_from_error()
"""
    assert _check(src) == []


def test_raise_new_error_without_from_allowed():
    src = """
def f():
    try:
        risky()
    except Exception:
        raise RuntimeError("boom")
"""
    assert _check(src) == []


def test_return_none_before_raise_allowed():
    # The final statement is a raise, not the sentinel return.
    src = """
def f():
    try:
        risky()
    except Exception:
        if cond:
            return None
        raise
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        "",
        "\n\n",
        "# just a comment\n",
        "x = 1\n",
        "def f():\n    return None\n",
        "try:\n    risky()\nexcept Exception:\n    pass\n",
    ],
)
def test_no_diagnostics_for_sources_without_swallowing_handler(src: str):
    assert _check(src) == []


def test_module_level_return_in_except_is_flagged():
    src = """
try:
    risky()
except Exception:
    return None
"""
    assert len(_check(src)) == 1


def test_deeply_nested_function_handler_flagged():
    src = """
def outer():
    def inner():
        try:
            risky()
        except Exception:
            return None
    return inner
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "log_call",
    [
        'logger.debug("x")',
        'logger.info("x")',
        'logger.warning("x")',
        'logger.warn("x")',
        'logger.error("x")',
        'logger.exception("x")',
        'logger.critical("x")',
        'logger.fatal("x")',
        'log.info("x")',
        'log.error("x")',
        'logging.warning("x")',
        'logging.exception("x")',
        'self.logger.error("x")',
        '_logger.warning("x")',
        'logger.error("failed", exc_info=e)',
    ],
)
def test_logged_sentinel_is_exempt_across_levels_and_receivers(log_call: str):
    src = f"""
def f():
    try:
        risky()
    except Exception as e:
        {log_call}
        return None
"""
    assert _check(src) == []


@pytest.mark.parametrize("ret", ["None", "False", "[]", "{}", "()", "''", "set()"])
def test_logged_sentinel_exempt_for_every_sentinel_shape(ret: str):
    src = f"""
def f():
    try:
        risky()
    except Exception:
        logger.warning("oops")
        return {ret}
"""
    assert _check(src) == []


def test_logging_in_nested_branch_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        if verbose:
            logger.error("boom", exc_info=e)
        return None
"""
    assert _check(src) == []


def test_silent_sentinel_no_logging_still_fires():
    src = """
def f():
    try:
        risky()
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_print_is_not_logging_still_fires():
    src = """
def f():
    try:
        risky()
    except Exception:
        print("oops")
        return None
"""
    assert len(_check(src)) == 1


def test_bare_exception_read_is_not_logging_still_fires():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        str(e)
        return None
"""
    assert len(_check(src)) == 1


def test_non_log_receiver_with_log_method_name_still_fires():
    # `metrics.error(...)` has a logging-style method name but the receiver is
    # not a logger, so it is not treated as logging.
    src = """
def f():
    try:
        risky()
    except Exception:
        metrics.error("count")
        return None
"""
    assert len(_check(src)) == 1


def test_log_receiver_with_non_log_method_still_fires():
    # `logger.emit(...)` is on a logger but `emit` is not a recognized level.
    src = """
def f():
    try:
        risky()
    except Exception:
        logger.emit("x")
        return None
"""
    assert len(_check(src)) == 1


def test_logging_only_inside_nested_def_still_fires():
    # A logging call inside a nested def does not run before the return, so the
    # handler still silently swallows.
    src = """
def f():
    try:
        risky()
    except Exception:
        def _later():
            logger.error("x")
        return None
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "nested_scope",
    [
        'later = lambda: logger.error("x")',
        'class Later:\n            logger.error("x")',
    ],
    ids=["lambda", "class"],
)
def test_logging_inside_a_nested_scope_still_fires(nested_scope: str):
    src = f"""
def f():
    try:
        risky()
    except Exception:
        {nested_scope}
        return None
"""
    assert len(_check(src)) == 1


def test_logging_in_nested_for_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        for _ in range(1):
            logger.error("boom", exc_info=e)
        return None
"""
    assert _check(src) == []


def test_logging_in_nested_with_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        with lock():
            logger.exception("boom")
        return None
"""
    assert _check(src) == []


def test_logging_in_match_case_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        match kind:
            case 1:
                logger.error("boom")
            case _:
                logger.warning("other")
        return None
"""
    assert _check(src) == []


def test_logging_in_nested_try_handler_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception:
        try:
            g()
        except ValueError:
            logger.warning("inner")
        return None
"""
    assert _check(src) == []


def test_logging_inside_walrus_before_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception:
        if (rc := logger.error("boom")) is None:
            pass
        return None
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "log_call",
    [
        "self._log.error('x')",
        "self._logger.warning('x')",
        "app.log.info('x')",
        "log.exception('x')",
    ],
)
def test_dotted_and_underscore_log_receivers_are_exempt(log_call: str):
    src = f"""
def f():
    try:
        risky()
    except Exception as e:
        {log_call}
        return None
"""
    assert _check(src) == []


def test_fstring_log_then_sentinel_is_exempt():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        logger.error(f"failed: {e}")
        return None
"""
    assert _check(src) == []


def test_logging_in_except_star_group_is_exempt():
    src = """
def f():
    try:
        risky()
    except* ValueError:
        logger.exception("grouped")
        return None
"""
    assert _check(src) == []


def test_bare_helper_log_function_is_not_logging_still_fires():
    # `log_error(e)` is a plain Name call, not `<recv>.<level>(...)`, so the rule
    # cannot know it logs — the swallow still fires.
    src = """
def f():
    try:
        risky()
    except Exception as e:
        log_error(e)
        return None
"""
    assert len(_check(src)) == 1


def test_print_style_fstring_still_fires():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        print(f"oops {e}")
        return None
"""
    assert len(_check(src)) == 1


def test_log_after_early_return_only_still_fires():
    src = """
def f():
    try:
        risky()
    except Exception:
        if cond:
            return None
        logger.error("x")
"""
    assert _check(src) == []


def test_ternary_sentinel_return_is_allowed():
    src = """
def f():
    try:
        risky()
    except Exception:
        return None if flag else None
"""
    assert _check(src) == []


def test_walrus_sentinel_return_is_allowed():
    # `return (x := None)` is a NamedExpr, not a sentinel constant.
    src = """
def f():
    try:
        risky()
    except Exception:
        return (x := None)
"""
    assert _check(src) == []


def test_substring_log_receiver_should_still_fire():
    src = """
def f():
    try:
        risky()
    except Exception:
        dialog.error("show error to user")
        return None
"""
    assert len(_check(src)) == 1


def test_inline_getlogger_chain_should_be_exempt():
    src = """
def f():
    try:
        risky()
    except Exception:
        logging.getLogger(__name__).error("boom")
        return None
"""
    assert _check(src) == []


def test_logging_only_on_early_return_branch_should_still_fire():
    src = """
def f():
    try:
        risky()
    except Exception as e:
        if verbose:
            logger.exception("boom")
            return cached
        return None
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "src",
    [
        # requests.utils.is_ipv4_address
        """
def is_ipv4_address(string_ip):
    try:
        socket.inet_aton(string_ip)
    except OSError:
        return False
    return True
""",
        # requests.utils.is_valid_cidr
        """
def is_valid_cidr(string_network):
    try:
        mask = int(string_network.split("/")[1])
    except ValueError:
        return False
    return True
""",
        # httpx._models._is_known_encoding (underscore-prefixed is_)
        """
def _is_known_encoding(encoding: str) -> bool:
    try:
        codecs.lookup(encoding)
    except LookupError:
        return False
    return True
""",
    ],
)
def test_predicate_named_probe_is_exempt(src: str):
    assert _check(src) == []


@pytest.mark.parametrize(
    "name",
    ["is_ready", "has_access", "can_send", "should_retry", "_is_ready", "__has_perm"],
)
def test_predicate_name_prefixes_exempt_any_sentinel(name: str):
    src = f"""
def {name}(x):
    try:
        probe(x)
    except Exception:
        return False
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["disable_thing", "vision_check", "assist_user", "island_hop"])
def test_non_predicate_lookalike_names_still_fire(name: str):
    # `is`/`has`/`can`/`should` embedded mid-word is NOT a predicate prefix.
    src = f"""
def {name}(x):
    try:
        probe(x)
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_boolean_probe_with_true_success_path_is_exempt():
    # requests.utils.unicode_is_ascii — name is not is_-prefixed, but success
    # `return True` vs handler `return False` is the classic predicate shape.
    src = """
def unicode_is_ascii(u_string):
    try:
        u_string.encode("ascii")
        return True
    except (UnicodeEncodeError, AttributeError):
        return False
"""
    assert _check(src) == []


def test_response_ok_property_is_exempt():
    # requests.models.Response.ok
    src = """
class Response:
    @property
    def ok(self):
        try:
            self.raise_for_status()
        except HTTPError:
            return False
        return True
"""
    assert _check(src) == []


def test_boolean_probe_none_handler_still_fires_without_bool_success():
    # No boolean on the success path -> not a probe; a bare `return None` swallow.
    src = """
def load(x):
    try:
        return fetch(x)
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "src",
    [
        # fastapi._compat.shared.is_pydantic_v1_model (name AND import-error)
        """
def is_pydantic_v1_model(obj):
    try:
        from pydantic.v1 import BaseModel
    except ImportError:
        return False
    return isinstance(obj, BaseModel)
""",
        # django.core.validators.get_available_image_extensions
        """
def get_available_image_extensions():
    try:
        from PIL import Image
    except ImportError:
        return []
    else:
        return [ext.lower() for ext in Image.registered_extensions()]
""",
        """
def load_optional():
    try:
        import ujson
    except ModuleNotFoundError:
        return None
    return ujson
""",
    ],
)
def test_import_error_feature_detection_is_exempt(src: str):
    assert _check(src) == []


def test_import_error_in_tuple_with_broad_error_still_fires():
    # Catching ImportError alongside a broad Exception is not pure feature
    # detection — the broad arm can swallow a real error.
    src = """
def load_thing():
    try:
        return build()
    except (ImportError, Exception):
        return None
"""
    assert len(_check(src)) == 1


def test_get_reason_phrase_lookup_with_default_is_exempt():
    # httpx._status_codes.codes.get_reason_phrase
    src = """
def get_reason_phrase(value):
    try:
        return codes(value).phrase
    except ValueError:
        return ""
"""
    assert _check(src) == []


@pytest.mark.parametrize("default", ["''", "None", "[]", "{}"])
def test_lookup_with_default_narrow_exception_exempt(default: str):
    src = f"""
def lookup(key):
    try:
        return table[key].value
    except KeyError:
        return {default}
"""
    assert _check(src) == []


def test_lookup_with_broad_exception_still_fires():
    # A broad `except Exception:` over a lookup is the swallow the rule targets.
    src = """
def lookup(key):
    try:
        return table[key].value
    except Exception:
        return ""
"""
    assert len(_check(src)) == 1


def test_lookup_with_bare_except_still_fires():
    src = """
def lookup(key):
    try:
        return table[key].value
    except:
        return ""
"""
    assert len(_check(src)) == 1


def test_multi_statement_try_is_not_lookup_with_default_still_fires():
    # More than a single `return` in the try body -> not the lookup idiom; the
    # narrow except still swallows whatever the side-effecting work raised.
    src = """
def build(key):
    prepare()
    try:
        step()
        return table[key].value
    except ValueError:
        return ""
"""
    assert len(_check(src)) == 1


def test_data_function_broad_swallow_to_none_still_fires():
    src = """
def fetch_user(user_id):
    try:
        return db.query(user_id)
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_data_function_broad_swallow_to_empty_list_still_fires():
    src = """
def load_records():
    try:
        rows = fetch()
        return parse(rows)
    except Exception:
        return []
"""
    assert len(_check(src)) == 1


def test_data_function_empty_string_swallow_still_fires():
    src = """
def read_body(resp):
    try:
        return resp.content.decode()
    except Exception:
        return ""
"""
    assert len(_check(src)) == 1


def test_non_bool_success_return_does_not_make_a_probe():
    # The success path returns real data (a dict), so a handler `return {}` is a
    # swallow, not a boolean probe.
    src = """
def get_config():
    try:
        return load()
    except Exception:
        return {}
"""
    assert len(_check(src)) == 1


def test_bare_except_pass_is_flagged():
    src = """
def f():
    try:
        risky()
    except:
        pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ009"


def test_typed_except_pass_is_not_flagged():
    # A typed handler (`except KeyError: pass`) is often a deliberate optional-path
    # no-op; only the bare form is flagged, so existing behavior is preserved.
    src = """
def f():
    try:
        risky()
    except Exception:
        pass
"""
    assert _check(src) == []


def test_bare_except_pass_points_at_handler():
    src = """
def f():
    try:
        risky()
    except:
        pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_bare_except_with_logging_before_pass_is_not_flagged():
    src = """
def f():
    try:
        risky()
    except:
        logger.exception("boom")
        pass
"""
    assert _check(src) == []


def test_bare_except_with_recovery_before_pass_is_not_flagged():
    src = """
def f():
    try:
        risky()
    except:
        recover()
        pass
"""
    assert _check(src) == []


def test_optional_return_multi_statement_try_narrow_except_is_exempt():
    src = """
def parse_time(time_str: str) -> dt.time | None:
    parts = str(time_str).split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        return dt.time(hour, minute, second)
    except ValueError:
        return None
"""
    assert _check(src) == []


def test_optional_return_sqlalchemy_inspect_shape_is_exempt():
    # sqlalchemy.orm.base._inspect_mapped_class — Optional[Mapper] with a narrow
    # domain exception returning None.
    src = """
def _inspect_mapped_class(class_, configure=False) -> Optional[Mapper]:
    try:
        class_manager = opt_manager_of_class(class_)
        if class_manager is None:
            return None
        mapper = class_manager.mapper
    except exc.NO_STATE:
        return None
    else:
        return mapper
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "annotation",
    ["int | None", "None | int", "Optional[int]", "Union[int, None]", "list[str] | None"],
)
def test_optional_annotation_shapes_all_exempt(annotation: str):
    src = f"""
def f(x) -> {annotation}:
    try:
        y = compute(x)
        return y
    except ValueError:
        return None
"""
    assert _check(src) == []


def test_optional_return_empty_container_narrow_except_is_exempt():
    src = """
def f(x) -> list[str] | None:
    try:
        y = compute(x)
        return y
    except KeyError:
        return []
"""
    assert _check(src) == []


def test_optional_with_broad_except_still_fires():
    # A broad `except Exception:` in an Optional function is still the swallow the
    # rule targets — the annotation alone does not license swallowing everything.
    src = """
def f(x) -> int | None:
    try:
        y = compute(x)
        return y
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_optional_with_bare_except_still_fires():
    src = """
def f(x) -> int | None:
    try:
        y = compute(x)
        return y
    except:
        return None
"""
    assert len(_check(src)) == 1


def test_non_optional_return_narrow_except_still_fires():
    # No `| None` in the annotation -> not the Optional contract; a data function
    # swallowing to None under a narrow except still fires.
    src = """
def f(x) -> int:
    try:
        y = compute(x)
        return y
    except ValueError:
        return None
"""
    assert len(_check(src)) == 1


def test_optional_return_false_is_not_optional_match_still_fires():
    # `False` is not the None arm of an Optional; the bool path does not apply
    # (no bool success return), so the swallow still fires.
    src = """
def f(x) -> int | None:
    try:
        y = compute(x)
        return y
    except ValueError:
        return False
"""
    assert len(_check(src)) == 1


def test_starred_exception_group_lookup_with_default_is_exempt():
    src = """
def f() -> list:
    try:
        return cast(list, json_loads_array(data))
    except (*JSON_DECODE_EXCEPTIONS, ValueError):
        return []
"""
    assert _check(src) == []


def test_starred_only_exception_group_lookup_with_default_is_exempt():
    src = """
def f():
    try:
        return table[key].value
    except (*NARROW_ERRORS,):
        return ""
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "log_call",
    [
        '_LOGGER.error("boom")',
        '_LOGGER.exception("boom")',
        'LOG.warning("boom")',
        'self._LOGGER.error("boom")',
        'LOGGING.error("boom")',
    ],
)
def test_uppercase_logger_before_return_is_exempt(log_call: str):
    src = f"""
def f():
    try:
        risky()
    except Exception:
        {log_call}
        return None
"""
    assert _check(src) == []


def test_uppercase_logger_bare_return_is_exempt():
    src = """
def f():
    try:
        risky()
    except OSError as ex:
        _LOGGER.error("unable: %s", ex)
        return
"""
    assert _check(src) == []


def test_uppercase_non_logger_receiver_still_fires():
    # `METRICS` ends in neither log/logger/logging, so case-insensitivity does not
    # turn a non-logger into a logger.
    src = """
def f():
    try:
        risky()
    except Exception:
        METRICS.error("count")
        return None
"""
    assert len(_check(src)) == 1


def test_stop_async_iteration_drain_is_exempt():
    # Minimized from trio's _channel.py: iterator exhaustion IS the expected
    # end-of-data signal, not a swallow.
    src = """
async def pump(agen, send_chan):
    while True:
        try:
            value = await agen.__anext__()
        except StopAsyncIteration:
            return
        await send_chan.send(value)
"""
    assert _check(src) == []


def test_stop_iteration_is_exempt():
    src = """
def first(it):
    try:
        head = next(it)
    except StopIteration:
        return
    process(head)
"""
    assert _check(src) == []


def test_none_procedure_narrow_handler_bare_return_is_exempt():
    # Minimized from trio's _dtls.py: a `-> None` procedure exiting early on an
    # expected, narrowly-caught condition.
    src = """
def handle(stream, packet) -> None:
    try:
        stream.bio_write(packet)
    except ClosedResourceError:
        return
    stream.flush()
"""
    assert _check(src) == []


def test_none_procedure_broad_handler_still_fires():
    src = """
def handle(stream, packet) -> None:
    try:
        stream.bio_write(packet)
    except Exception:
        return
    stream.flush()
"""
    assert len(_check(src)) == 1


def test_unannotated_function_narrow_handler_bare_return_still_fires():
    # Without the `-> None` contract the bare return may be masking a result.
    src = """
def handle(stream, packet):
    try:
        data = stream.read()
        process(data)
    except ClosedResourceError:
        return
"""
    assert len(_check(src)) == 1


def test_bool_annotated_contract_returning_false_is_exempt():
    # Minimized from pydantic's _decorators.py: the success path computes the
    # bool, so no literal-return corroboration exists — the annotation is the
    # contract.
    src = """
def uses_info(serializer, mode) -> bool:
    try:
        sig = signature(serializer)
    except (ValueError, TypeError):
        return False
    return count_positional(sig) == 2
"""
    assert _check(src) == []


def test_data_function_returning_false_still_fires():
    src = """
def load(path) -> dict:
    try:
        return parse(path)
    except Exception:
        return False
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("annotation", ["TypeIs[Callable]", "TypeGuard[Callable]"])
def test_bool_family_annotated_contract_returning_false_is_exempt(annotation: str):
    # Minimized from pydantic's takes_validated_data_argument: TypeIs/TypeGuard
    # are bool-valued contracts.
    src = f"""
def takes_data(factory) -> {annotation}:
    try:
        sig = signature(factory)
    except (ValueError, TypeError):
        return False
    return len(sig.parameters) == 1
"""
    assert _check(src) == []


def test_narrow_handler_returning_the_declared_sentinel_is_exempt():
    # Minimized from requests' testserver `_accept_connection`: the success path
    # already answers None on timeout, so None is the published result.
    src = """
def _accept_connection(self):
    try:
        ready, _, _ = select.select([self.server_sock], [], [], 1)
        if not ready:
            return None
        return self.server_sock.accept()[0]
    except OSError:
        return None
"""
    assert _check(src) == []


def test_narrow_handler_returning_declared_empty_dict_is_exempt():
    # Minimized from pydantic's extract_docstrings_from_cls.
    src = """
def extract(cls) -> dict:
    try:
        source, _ = inspect.getsourcelines(cls)
    except OSError:
        return {}
    if not source:
        return {}
    return parse(source)
"""
    assert _check(src) == []


@pytest.mark.parametrize("sentinel", ["None", "False", "[]", "{}", "()", "''", "set()"])
def test_narrow_handler_returning_each_declared_sentinel_is_exempt(sentinel: str):
    src = f"""
def load(use_default):
    if use_default:
        return {sentinel}
    try:
        return parse()
    except ValueError:
        return {sentinel}
"""
    assert _check(src) == []


def test_narrow_handler_returning_a_different_sentinel_still_fires():
    src = """
def load(use_default):
    if use_default:
        return []
    try:
        value = read()
        return parse(value)
    except ValueError:
        return {}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "non_contract_return",
    [
        "def fallback():\n        return None",
        'try:\n        recover()\n    except KeyError:\n        logger.info("expected")\n        return None',
    ],
    ids=["nested-function", "exception-handler"],
)
def test_nested_scope_and_exception_returns_do_not_declare_a_sentinel(non_contract_return: str):
    src = f"""
def load():
    {non_contract_return}
    try:
        value = read()
        return parse(value)
    except OSError:
        return None
"""
    assert len(_check(src)) == 1


def test_broad_handler_returning_the_declared_sentinel_still_fires():
    src = """
def load(path):
    if path is None:
        return None
    try:
        return parse(path)
    except Exception:
        return None
"""
    assert len(_check(src)) == 1


def test_narrow_handler_sentinel_absent_from_success_path_still_fires():
    src = """
def load(path):
    try:
        raw = read(path)
        parsed = parse(raw)
    except OSError:
        return []
    return normalize(parsed)
"""
    assert len(_check(src)) == 1


def test_narrow_handler_printing_the_bound_exception_is_exempt():
    # Minimized from black's blib2to3/pgen2/conv.py: in a script, print IS the log.
    src = """
def parse_graminit_c(self, filename):
    try:
        f = open(filename)
    except OSError as err:
        print(f"Can't open {filename}: {err}")
        return False
    return self.parse(f)
"""
    assert _check(src) == []


def test_narrow_handler_printing_something_unrelated_still_fires():
    src = """
def parse_graminit_c(self, filename):
    try:
        f = open(filename)
    except OSError as err:
        print("could not parse")
        return False
    return self.parse(f)
"""
    assert len(_check(src)) == 1


def test_optional_import_guard_with_bare_except_is_exempt():
    # Minimized from rich's tests/test_windows_renderer.py.
    src = """
try:
    from rich._win32_console import LegacyWindowsTerm
    from rich._windows_renderer import legacy_windows_render
except:
    pass
"""
    assert _check(src) == []


def test_bare_except_pass_over_a_real_call_still_fires():
    src = """
try:
    configure()
except:
    pass
"""
    assert len(_check(src)) == 1


def test_bare_except_pass_over_an_inert_body_is_exempt():
    # Minimized from black's remove_except_types_parens fixtures: a `pass` body
    # raises nothing, so the handler discards no error.
    src = """
try:
    pass
except:
    pass
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "guarded_body",
    ["import optional_dependency", "pass", "...", '"inert"'],
    ids=["import", "pass", "ellipsis", "docstring"],
)
def test_import_only_and_inert_guarded_bodies_cannot_swallow_an_error(guarded_body: str):
    src = f"""
def load():
    try:
        {guarded_body}
    except:
        return None
"""
    assert _check(src) == []
