# SARJ014 `prefer-timedelta-for-durations` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_timedelta_for_durations.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A parameter or field whose name carries a time unit (`timeout_seconds`,
`retry_interval_ms`, `ttl`, `backoff_minutes`, ...) but is annotated `int` or
`float` forces every call site to remember the unit and invites the
`_seconds` / `_ms` / `_minutes` naming-collision class of bugs. `datetime.timedelta`
makes the unit explicit at the call site and lets the type checker catch
mismatches.

    # flagged
    def schedule(self, timeout_seconds: int) -> None: ...
    class Settings(BaseModel):
        retry_interval_ms: float = 250.0
        api_timeout_s: NonNegativeFloat = 30.0   # constrained brands too

    # preferred
    def schedule(self, timeout: timedelta) -> None: ...
    class Settings(BaseModel):
        retry_interval: timedelta = timedelta(milliseconds=250)

Scope is deliberately narrow to keep false positives low: only annotated
function parameters and annotated assignments (`AnnAssign`, i.e. class/module
fields) are inspected, and only when the annotation resolves to a numeric type —
bare `int`/`float`, a pydantic constrained brand (`PositiveInt`,
`NonNegativeFloat`, ...), or any of those under `| None` / `Optional[...]` /
`Annotated[...]`. Plain local assignments are not flagged.

Deliberately NOT flagged:
- count-like names (`*_count`, `num_*`, `n_*`, `*_size`, `*_limit`),
- wall-clock components, which are positions not durations — only plural/abbrev
  unit names match (`*_minutes`, `*_secs`), so a bare `hour`/`minute`/`second` is
  left alone,
- percentages and rates (`*_percentage`, `*_pct`, `*_rate`, `*_ratio`),
- calendar units that `timedelta` cannot express cleanly (`*_months`, `*_years`),
- absolute instants (`*_timestamp`, `*_epoch`, `expires_at`, `*_at`),
- anything already annotated `timedelta`,
- fields declared directly on a pydantic-settings class (any base name ending in
  `Settings`, e.g. `BaseSettings` / `pydantic_settings.BaseSettings` / a
  `...Settings` subclass): these are populated from environment variables, whose
  bare-numeric wire values `timedelta` cannot parse, so a raw `int`/`float` is
  the only workable type at that boundary. Ordinary `BaseModel` domain fields are
  still flagged.
- test files (`_paths.is_test_path`): test fakes and helpers mirror the
  signatures of stdlib/third-party APIs under test (`Lock.acquire(timeout=-1)`,
  seconds-based subprocess helpers) and cannot change them — the trio sweep's
  false positives were all of this shape.
- `@overload` stubs. The overload set restates one implementation's signature N
  times, so reporting each is N-1 duplicates of the same finding; the
  implementation that follows is still flagged. Six of the famous-repo sweep's
  21 hits were this
  (`anyio/src/anyio/_core/_sockets.py:82`, `:97`, `:113`, `:129`, `:141` all
  restating `happy_eyeballs_delay` for `connect_tcp` at `:155`, plus
  `anyio/src/anyio/functools.py:282` restating `ttl` for `:303`).
- **CLI parameters** — a parameter of a function decorated with `click` /
  `typer` (`@click.option`, `@click.argument`, ...). Same boundary argument as
  pydantic-settings: the value is parsed out of `argv` by the framework
  (`type=float`), and `timedelta` is not a shape argv can carry
  (`httpx/httpx/_main.py:464`, `timeout: float` behind `@click.option("--timeout",
  type=float, default=5.0)`).
- **Same-name delegation wrappers** — a body that does nothing but forward the
  parameter to a callee of the same name (`async def sleep(delay: float): await
  trio.sleep(delay)`). The unit belongs to the wrapped API, not to the wrapper:
  `anyio/src/anyio/_backends/_trio.py:1115`,
  `anyio/src/anyio/_backends/_asyncio.py:2532`, and
  `anyio/src/anyio/_core/_eventloop.py:88` all mirror stdlib `sleep`. A body
  that computes with the parameter (`deadline = current_time() + delay`) is not
  a pass-through and still fires.
- **Same-name keyword forwarding** — a parameter whose every use in the enclosing
  function is either `<callee>(<name>=<name>)` or `self.<name> = <name>`, and
  which never appears in arithmetic, a comparison or a subscript. The name is a
  duration but the type is the wrapped API's: the value is handed to a third
  party that documents float/int seconds, so the author cannot switch it to
  `timedelta` without converting at a boundary the wrapper does not own. A body
  that *computes* with the parameter is not forwarding and still fires
  (`prefect/src/prefect/server/orchestration/rules.py:870` survives). A
  constructor that only stores the parameter verbatim is likewise not where the
  unit is chosen: the field's own annotation is a separate `AnnAssign` this rule
  still inspects.
- **annotations that already admit `timedelta`** — `timeout: float | timedelta`
  fires only because the union walk returns on its first numeric member, yet the
  API already accepts exactly what the rule is asking for, so the defect cannot
  be present. The reductio is
  `airflow/task-sdk/src/airflow/sdk/bases/sensor.py:145`,
  `def _coerce_poke_interval(poke_interval: float | timedelta) -> timedelta` —
  the function whose entire job is the conversion the rule demands (also
  `airflow/providers/google/cloud/hooks/cloud_storage_transfer_service.py:480`).

## 2026-07 false-positive audit

Measured on a 19-repo corpus (seven first-party repos plus django, celery,
airflow, litellm, prefect, saleor, zulip, fastapi, pydantic, rich, httpx,
requests, deduped by content hash): **2,791 findings**, 202 of them first-party.
A seeded random sample of 50 read against source put the false-positive rate at
**50%**. The two guards below take the rule to **1,308** and first-party 202 →
**188**.

* **Same-name keyword forwarding** — the dominant class, **20 of the 50 sampled**.
  Removes **1,467 of 2,791 (53%)** at a cost of **13 of 202 first-party findings
  (6.4%)**. That cost was accepted deliberately over two narrower predicates that
  cost no first-party recall at all — `timeout` beside sibling parameters `retry`
  AND `metadata` (635 findings), and `waiter_*` beside a sibling `waiter_max_*`
  (81) — because both are shape-matching against two specific third-party SDKs
  and neither generalises to the next wrapper. The `google.api_core` triple
  (`retry: Retry | _MethodDefault, timeout: float | None, metadata: Sequence`)
  forwarded verbatim into a gapic client is the single biggest shape —
  `airflow/providers/google/cloud/hooks/analytics_admin.py:73`,
  `.../hooks/managed_kafka.py:445`, `.../hooks/alloy_db.py:398`,
  `.../operators/dlp.py:2830`, `.../operators/tasks.py:204`,
  `.../operators/stackdriver.py:101` — with `waiter_delay` into botocore's
  `WaiterConfig` (`airflow/providers/amazon/aws/operators/glue.py:696`,
  `.../emr.py:1655`) and `poll_timeout` into `confluent_kafka.Consumer.consume`
  (`airflow/providers/apache/kafka/operators/consume.py:167`) next.
* **`timedelta` already in the union** — **19 of 2,791**, 1 of them first-party.
  **Recall cost is zero by construction**: a signature that already takes a
  `timedelta` cannot be forcing its callers to count seconds.

Two classes are deliberately left to `# sarj-noqa` rather than guarded, because
both are real judgement calls rather than impossible edits:

* wire-format DTO fields, where an integer count of seconds is what the protocol
  puts on the wire (`expires_in: int` in an OAuth2 token response is RFC 6749's
  spelling; `delay_seconds: int` in
  `prefect/src/prefect/server/schemas/responses.py:88` is a public REST response
  schema), and
* numeric and statistical helpers whose parameter feeds arithmetic rather than a
  clock (`prefect/src/prefect/utilities/math.py:6`,
  `poisson_interval(average_interval: float)` feeding `math.log`).

Suppress an intentional raw-numeric duration with `# sarj-noqa: SARJ014 — <reason>`.

References:
- https://docs.python.org/3/library/datetime.html#timedelta-objects

* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package accounts for all of them.

## Implementation notes

### `_numeric_annotation`

Handles bare `int`/`float`, pydantic constrained brands (`PositiveInt`,
`NonNegativeFloat`, ...), `x | None`, `Optional[x]`, and `Annotated[x, ...]`.

### `_settings_field_ids`

A class is treated as pydantic-settings when it derives from a `...Settings`
base — either directly (`BaseSettings`, `pydantic_settings.BaseSettings`, a
project `...Settings` class) or transitively through an intermediate base
defined in the same module (e.g. `class _Base(BaseSettings)` →
`class Foo(_Base)`). Such fields come from environment variables, whose
bare-numeric wire form `timedelta` cannot parse, so they are exempt.

### `_is_forwarded_to_same_name`

`async def sleep(delay: float) -> None: await trio.sleep(delay)` is a
pass-through: the unit is the wrapped API's, and this signature exists to
mirror it.

### `_has_cli_decorator`

Its parameters are parsed out of `argv` by the framework, which knows how to
build an `int`/`float` and not a `timedelta`.
