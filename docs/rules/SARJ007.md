# SARJ007 `no-fat-try-blocks` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_fat_try_blocks.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A fat `try` body obscures which statement is actually expected to raise and
widens the blast radius of the `except` handlers: unrelated failures get
caught (and often swallowed or mis-reported) by handlers written for a
different operation. Keep the `try` skinny — isolate the throwing
statement(s) and move the non-throwing setup and follow-up work outside.

Two refinements keep the count aligned with that intent and avoid the
false-positive patterns that dominated real-world suppressions:

* Only top-level statements that *can raise* are counted — a statement counts
  toward the limit only if its subtree contains a call or `await`. Pure
  assignments / name-rebinds (`self.x = y`, `a = b.c`) don't obscure a throwing
  statement and are free. Statements nested inside an `if` / `with` / loop
  count as the single compound statement that contains them. Nested `try`
  blocks are checked independently. `try*` (PEP 654) is held to the same limit.
* OBSERVABILITY STATEMENTS ARE FREE for the same reason pure assignments are.
  A statement whose calls are all instrumentation — a logger call, a Prometheus /
  statsd / OpenTelemetry recorder (`counter.labels(...).inc()`,
  `hist.observe(elapsed)`, `span.set_attribute(...)`), a monotonic clock read, or
  a value-shaping builtin used to format an argument (`len`, `round`, `type`) —
  does not obscure which statement the handler was written for: nobody catches a
  failed `logger.info`. It is also, being success-path bookkeeping, exactly what
  must stay INSIDE the `try` so it does not run on the except path — so the rule
  was asking for a change that cannot be made. A statement mixing a real call
  with logging still counts.

  Evidence from a first-party review regression (all suppressed at the reviewed
  head, none a defect): two sites in one cache-priming module — both suppressions
  read "success-only bookkeeping (elapsed/metrics/log) must stay inside try so it
  does not run on the except path"; of the 6 and 5 statements counted there, only
  2 and 1 were real operations (a prompt fetch and an LLM call), the rest were
  `time.monotonic()`, two `<metric>.labels(...).inc()/.observe()` recorders and a
  `logger.info`. Likewise a third site in a builder module (4 counted, the 4th a
  `logger.info`).
* `try` blocks that carry an `else` or `finally` clause are exempt. Those
  clauses are a deliberate success/cleanup contract that couples the body to
  the handler (a `finally` that tears down a resource, an `else`/`finally` that
  reads a status the body set) — statements can't be freely hoisted out without
  changing semantics, so the length check is counterproductive there.
* `try` blocks whose every `except` handler re-raises (bare `raise`, or
  `raise Wrapped from e`) are exempt. The fat-try smell is over-broad
  *swallowing*; when no handler swallows, the width is deliberate uniform
  error-context / metric wrapping and isolating one call would change which
  failures are reported. A handler that returns / continues / passes /
  logs-without-raise is swallowing and keeps the block in scope.

Instead of:
    try:
        payload = build_payload(order)
        response = client.send(payload)
        record = parse(response)
        store.save(record)
    except HTTPError:
        ...

Prefer:
    payload = build_payload(order)
    try:
        response = client.send(payload)
    except HTTPError:
        ...
    record = parse(response)
    store.save(record)

References:
- https://docs.python.org/3/tutorial/errors.html#handling-exceptions
- https://docs.python.org/3/library/ast.html#ast.Try

* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package under `python/sdk/src/` accounts for all of them.

## Implementation notes

### `_all_handlers_reraise`

When it does, the block is uniform error-context/metric wrapping, not
swallowing, so its width is intentional. A handler with any path that returns
/ continues / passes / falls through (including a conditional early return
before a tail `raise`) is swallowing and makes this False, so the block still
fires.

### `_stmt_exits`

Control can propagate an exception (`RAISE`), diverge without raising via
return/break/continue (`SWALLOW`), or complete normally and fall through to
the next statement (`FALL`).

### `_can_raise`

A statement can raise when its same-scope subtree contains a call or `await`.
Pure assignments / rebinds and inert `def` / `lambda` definitions (whose
bodies never execute here) are free.

So is a statement whose calls are ALL observability — logging, metrics,
tracing, a clock read. Those don't obscure which statement the handler was
written for (nobody catches a failed `logger.info`), and, being success-path
bookkeeping, they are precisely what must stay inside the `try` so it does not
run on the except path. Treating them as free is the same argument that
already makes pure assignments free. A statement that MIXES a real call with
logging still counts.

### `_is_observability_call`

No `except` handler is ever written *for* one of these: a logger call is
swallow-by-design (loguru/`logging` route their own failures to the handler's
error stream), a Prometheus/OTel recorder mutates an in-process counter, and a
monotonic clock read cannot raise. They are exactly the statements engineers
keep inside a `try` so they run only on the success path, which is why they
dominate the rule's suppressions.

### `_walk_same_scope`

Those bodies do not run when the enclosing `try` executes, so calls inside
them must not count as throwing. Decorators and default-argument expressions
still run at definition time, so their fields are walked normally.
