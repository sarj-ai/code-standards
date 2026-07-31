# SARJ009 `no-sentinel-return-on-except` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_sentinel_return_on_except.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

An `except` block whose final statement is `return <sentinel>` (None, False,
empty collection, empty string) and which never re-raises can silently discard the
error. Callers then can't distinguish "no result" from "something broke", which
hides bugs and corrupts idempotency decisions.

Prefer re-raising, or returning a typed result (e.g. a Result/Optional that the
caller must explicitly handle).

A handler that logs the exception (`logger.*` / `log.*` / `logging.*`) before
returning the sentinel is exempt: the error is observable, so the sentinel is the
handled result the caller expects rather than a silent swallow. The rule's value
is catching *silent* swallows — a handler that returns a sentinel with no logging
still fires.

Real-world sweeps (requests, httpx, FastAPI, Django) showed that a large share of
`except: return <sentinel>` sites are the function's *intended typed result*, not a
swallowed error. Four such shapes are exempt:

- **Predicate name:** the enclosing function is named like a boolean probe
  (`is_*` / `has_*` / `can_*` / `should_*`, plus `_`-prefixed forms) — e.g.
  `is_ipv4_address`, `_is_known_encoding`, `is_pydantic_v1_model`.
- **Boolean probe:** the handler returns `False`/`None` and a *non-exception* path
  of the same function returns a boolean — the classic `except: return False` /
  success `return True` predicate (e.g. `Response.ok`, `unicode_is_ascii`).
- **Feature detection / optional dependency:** the handler catches only
  `ImportError` / `ModuleNotFoundError` and returns a falsy sentinel — e.g.
  `is_pydantic_v1_model` (`except ImportError: return False`),
  `get_available_image_extensions` (`except ImportError: return []`).
- **Lookup-with-default:** the `try` body is a single `return <lookup>` guarded by a
  *narrow* exception (not bare `except:`, not `Exception`/`BaseException`) and the
  handler returns an empty sentinel — e.g. httpx `get_reason_phrase`
  (`try: return codes(value).phrase except ValueError: return ""`). Starred
  exception groups (`except (*JSON_DECODE_EXCEPTIONS, ValueError):`) are narrow.
- **Optional contract:** the enclosing function is annotated `X | None` /
  `Optional[X]` / `Union[..., None]`, the handler is *narrow*, and it returns the
  `None` arm (or an empty container) — the multi-statement compute-then-return
  Optional idiom, e.g. `parse_time(...) -> time | None` returning `None` on
  `except ValueError:`.
- **Bool contract:** the enclosing function is annotated `-> bool` and the
  handler returns a boolean — same as the boolean-probe shape but keyed off the
  annotation, for probes whose success path computes the bool rather than
  returning a literal (pydantic's `_serializer_info_arg` callers).
- **Iteration control-flow:** the handler catches only `StopIteration` /
  `StopAsyncIteration` — mapping iterator exhaustion to an exit is THE idiom
  (trio's `agen.__anext__()` drain loop), not a swallow.
- **Procedure early-exit:** the enclosing function is annotated `-> None`, the
  handler is *narrow*, and it ends in a bare `return` — a procedure has no
  result to corrupt, and a targeted except-return is a deliberate early exit on
  an expected condition (trio's `except ClosedResourceError: return`).

A 2,657-file third-party sweep added three more, each keyed to a *narrow* handler
or to a `try` body that has nothing to swallow — the broad-handler swallow the
rule exists to catch is untouched by all three:

- **Declared falsy result:** the handler is narrow and returns the very sentinel
  the function already returns on a NON-exception path, so the sentinel is the
  function's published answer and every caller must already handle it (requests'
  `_accept_connection`: `if not ready: return None` above `except OSError:
  return None`; pydantic's `extract_docstrings_from_cls`: `except OSError:
  return {}` beside a plain `if not source: return {}`).
- **Printed exception:** a narrow handler that `print(...)`s the exception it
  bound (`except OSError as err: print(f"Can't open {filename}: {err}")`) makes
  the error observable — in a script or CLI, `print` IS the log (black's
  `blib2to3/pgen2/conv.py`). A handler that prints something unrelated to the
  exception is still a silent swallow.
- **Nothing to swallow:** a `try` body that is only imports (the optional-
  dependency guard `try: from rich._win32_console import ... except: pass`,
  rich's `test_windows_renderer.py`) or only inert statements (`pass` / `...` /
  a docstring, black's `remove_except_types_parens*` fixtures). An import guard
  is the documented feature-detection shape; an inert body can raise nothing at
  all, so no error is being discarded.

The genuine bug — a data-returning function whose success path yields real data and
whose broad handler swallows to a sentinel — still fires. A bare `except: pass`
that discards the error with no return is also flagged.

## Implementation notes

### `_handler_reraises`

A `raise` inside a nested def/lambda doesn't re-raise for *this* handler, so
we stop walking at function/lambda boundaries.

### `_is_logger_name`

Matches the final underscore-delimited word, case-insensitively so the stdlib
module-level `_LOGGER` convention counts — not a mere substring (`dialog`,
`catalog`).

### `_is_logger_receiver`

Matches a name whose final word is `log`/`logger`/`logging` (`logger`, `_log`,
`self.logger`, `app.log`), or an inline `getLogger(...)` / `get_logger(...)`
call chain.

### `_is_logging_call`

`<level>` is a standard logging method (`logger.warning`, `log.info`,
`logging.error`) and `<recv>` is a logger. `print(...)` and bare reads of the
exception are not logging.

### `_is_irrefutable_case`

Such a case always matches, so it makes the match exhaustive (no implicit
unlogged fall-through past the match).

### `_stmt_props`

A path 'falls through' if control can continue to the next statement; 'logged'
means a logging call ran on that path. Nested def/lambda/class bodies are not
entered — their logging cannot execute inline before the sentinel return.

### `_list_props`

A path can fall off the end of the list (reach the statement that follows it)
without having logged, or having logged. `False, False` means every path
diverts (return/raise) before the end.

### `_handler_logs_before_return`

The final `return` is the caller's handled result; a logging call exempts the
swallow only when a control-flow path leads from that call to the sentinel
return (the error is observable on the path that yields the sentinel). Logging
that sits on a branch which diverts elsewhere — e.g. `if v: log(); return x` —
never reaches the sentinel and does not exempt it. Nested def/lambda bodies
are not entered, since their logging can't run inline.

### `_value_kind`

`None` (bare return or `None` literal) is "none"; `True`/`False` are "bool".

### `_is_lookup_with_default`

The idiom is a `try` body of exactly `return <lookup>` guarded by a narrow
exception, with the handler supplying an empty default (`get_reason_phrase`:
`try: return codes(v).phrase / except ValueError: return ""`). A bare `except:`
or a broad `except Exception:` is NOT narrow — that is the swallow the rule
exists to catch, so it still fires.

### `_non_except_returns`

Descend through ordinary statements but never into `except` handler bodies or
nested function/lambda scopes.

### `_has_non_except_bool_return`

Returns inside `except` handlers (the exception path) and inside nested
functions/lambdas do not count — only the success path of THIS function.

### `_is_predicate_name`

Matches `is_*`, `has_*`, `can_*`, `should_*`, and their underscore-prefixed
forms (`_is_known_encoding`).

### `_is_feature_detection`

An import-only handler is an optional-dependency fallback whose falsy return is
the intended 'feature unavailable' result.

### `_returns_bool`

Covers `-> bool` and the bool-valued narrowing forms `-> TypeGuard[X]` /
`-> TypeIs[X]` (pydantic's `takes_validated_data_argument`).

### `_is_iteration_control`

`except StopAsyncIteration: return` is the drain-loop exit idiom, not a
swallow — the exception IS the expected end-of-data signal.

### `_sentinel_matches_optional`

An Optional function's declared falsy result is `None` (bare `return` or the
literal) or an empty collection/string. `False` is excluded — a bool is handled
by the boolean-probe path, not the Optional contract.

### `_returns_optional`

Recognizes `X | None`, `None | X`, `Optional[X]`, and `Union[..., None]`.

### `_is_narrow_handler`

A bare `except:` (exc_names is None) or one catching `Exception`/`BaseException`
is broad — the swallow the rule targets. Anything else is narrow and targeted.

### `_handler_prints_exception`

In a script or CLI there is no logger; `print(f"...: {err}")` is how the
error is surfaced, so it is observable rather than silently swallowed. The
printed expression must reference the bound name, so a `print("done")` that
says nothing about the failure does not exempt anything, and the handler
must be narrow — a broad `except Exception` that prints and returns a
sentinel is still the swallow this rule targets.

### `_guarded_body_swallows_nothing`

Two shapes: a body of only `import` statements (the optional-dependency
guard — the documented feature-detection idiom, spelled with a bare
`except:` in the wild) and a body of only inert statements (`pass`, `...`,
a bare docstring), which cannot raise at all.

### `_sentinel_is_declared_result`

When the success path already answers `None` / `{}` / `[]` for "nothing
here", that value is the function's published result and every caller
handles it — the narrow handler is mapping an expected failure onto the
contract, not inventing a silent one. Only checked for narrow handlers: a
broad `except Exception` mapping onto the same sentinel is still a swallow.

### `_is_intended_result`

Covers predicate-named functions, boolean probes, optional-dependency feature
detection, and lookup-with-default — the shapes real sweeps flagged as
false positives. A broad handler in a data-returning function is not exempt.

### `_is_bare_except_pass`

This discards the error with no observable trace and no returned result — the
archetypal silent swallow. Typed handlers (`except ImportError: pass`) are left
alone: `pass` there is often a deliberate optional-path no-op.
