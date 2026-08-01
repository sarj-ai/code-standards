# SARJ080 `prefer-match-type-dispatch` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_match_type_dispatch.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Parsers and field deserializers often contain hideous type-dispatch idioms:
sequential `if x is None: return x` / `if isinstance(x, Unset): return x` guards,
followed by a `try` block containing `if not isinstance(x, T): raise TypeError()`
to artificially jump control flow into an `except (TypeError, ...): pass` block.

Raising an exception inside a `try` block solely to trigger that block's `except`
handler is using `raise` as a goto (control flow via exceptions).

Preferred Python 3.10+ match/case patterns:
- For `None`: `case None:`
- For singleton classes: `case Unset():`
- For builtins (`int`, `str`, `list`, `dict`): `case int():`, `case str():`, etc.
- For combined conditions: `case None | Unset():`

Example refactoring:
    match data:
        case None | Unset():
            return data
        case str():
            try:
                return datetime.datetime.fromisoformat(data)
            except ValueError:
                pass
        case dict():
            return parse_dict(data)
    return cast(..., data)

## Not reported

* **generated files** (`_paths.is_generated`). This is the exemption that
  matters most for this rule: the try/raise idiom in the module summary above
  is *transcribed from* openapi-python-client's `_parse_*` template, and it
  reproduces once per nullable field. Before the path half of `is_generated`
  existed, 314 of this rule's 334 findings over two first-party corpora came
  from a single checked-in SDK — a tree the consuming repo already excludes
  from ruff, from its pre-commit hook and from its CI invocation. The
  generator's output is not a refactor anyone can accept; re-running the
  generator would undo it. The 20 findings that remain are hand-written.

## 2026-07 false-positive audit

Measured over 24,644 deduped `.py` files (seven first-party repositories plus
django, celery, airflow, litellm, prefect, saleor, zulip, fastapi, pydantic,
rich, httpx, requests), the rule reported **1,635** findings: 1,364 from the
control-flow-raise arm and 271 from the sequential-guard arm. Two seeded random
samples of 25 read by hand put the false-positive rate at **56% and 84%**. After
the work below: **58**. Every guard is the narrowest predicate that kills a
*measured* class, and each is followed by what it cost.

### The guard arm carried a CORRECTNESS bug, not just noise

The rule was recommending a silent behaviour change. When the comparator is a
bare `Name`, **`case NAME:` is a capture pattern, not an equality test**: it
matches every value and rebinds the name. A guard reading
`if ticket_data is TICKET_NOT_FOUND: return ticket_data` becomes
`case TICKET_NOT_FOUND:`, which swallows everything that reaches it. **5 of the
271** findings would have been broken by following the advice. A bare-`Name`
comparator therefore no longer reports at all — that is the case where match/case
needs a `case _ if ...` guard clause and is not an improvement anyway. The
`case _ if data is UNSET:` line was removed from the recommended patterns above
for the same reason.

### Sequential-guard arm: 271 → 6

The prose above describes one shape — a sentinel *passthrough*, where the guard
returns the very variable it just tested — but the check accepted any `Compare`
with `is`/`is not`/`==`/`!=` on a `Name`, returning anything at all. Over the 271:

* **261/271 (96.3%)** returned something other than the guarded variable, so they
  were ordinary early returns and not the documented idiom. Only 4/271 were the
  full documented shape.
* **74/271 (27.3%)** contained no type check anywhere in the chain — enum and
  string equality early-returns reported as "sentinel/type guards".

A guard now counts only when it returns the tested variable unchanged and its
test translates directly into a class or literal pattern: `isinstance(x, T)`,
`issubclass(x, T)`, `x is None`, `x is not None`. That leaves **6 findings**, all
of the `to_python(self, value)` / `deserialize(o)` form the summary opens with,
and all correct. The arm is small but it is the only one that matches the rule's
name, and its precision on the corpus is 6/6.

### Control-flow-raise arm: 1,364 → 52, a five-guard ladder

1. **The handler re-raises, so the exception is not consumed** — 920/1,364
   (67.4%). The old check asked only "could some handler catch this type", never
   "does that handler *keep* it". `except ProxyException as e: raise e` thirty
   lines below the raise is not a goto: the exception leaves the function, and
   the message's claim that it "jumps directly to a local except handler" was
   simply false. The matching handler must now not raise on every terminal path.
   Cost: 1,364 → 440. Deliberately *strict* — a handler that re-raises only on
   some branch (retry loops, `if not retryable: raise`) still reports.
2. **`except Exception` fault barrier wrapped around a whole endpoint** —
   647/1,364 (47.4%) matched only because the handler caught the generic
   `Exception`, never because it named the raised type. Median try-body span for
   those was 39 lines and p90 was 220; one sat inside a 956-line try. The idiom
   this rule targets has a three-line try body. The handler must now name the
   raised type explicitly; a bare `except:` does not qualify either. Cost: 440 →
   319. This also fixes a soundness bug: four findings raised
   `SystemExit`/`KeyboardInterrupt`/`CancelledError` and were reported as
   "caught" by an `except Exception` that would not catch them.
3. **Try body longer than 20 lines.** The same fault-barrier population seen from
   the other side: a raise buried in a long try block is error propagation, not
   dispatch. Cost: 319 → 209.
4. **Try body is a single `raise`** — 132/1,364 (9.7%) were scaffolding that must
   raise in order to obtain a live exception object, because `sys.exc_info()` is
   the only way to get one: `try: raise Reject(requeue=True)` /
   `except Reject: einfo = ExceptionInfo()`. There is no dispatch to refactor.
   Cost: 209 → 108.
5. **Test files** (`_paths.is_test_path`) — 56 of the remaining 108. In a test a
   `raise` inside a `try` *is* the condition under test: it forces a transaction
   rollback, probes an optional import, drives a retry policy, or feeds
   `pytest.fail`. All 56 were read; none was a type dispatch, so the exemption
   costs no true positive on this corpus. It is scoped to this arm only — a field
   deserializer defined in a test-support module is still a real finding, and the
   sequential-guard arm keeps one. Cost: 108 → 52.

A lowercase `raise err` misread as a class name (24 findings) needed no separate
guard: requiring the handler to name the raised type removed all of them,
measured at zero additional suppressions.

The 52 survivors are the canonical raise-as-goto sites and are what the rule is
for — `django/views/static.py:116` and `:119` (`raise ValueError` to reach
`except (ValueError, OverflowError): return True`),
`django/db/models/options.py:74` (`if not isinstance(x, (tuple, list)): raise
TypeError` to reach `except TypeError`), `django/template/base.py:910`,
`django/db/models/fields/__init__.py:1805`, `airflow/timetables/_cron.py:77`,
`litellm/responses/sse_output_recovery.py:54`. Several are pinned as tests so the
ladder cannot widen into a no-op.
