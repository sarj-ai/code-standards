# SARJ001 `no-sequential-await` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_sequential_await.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Sequential `await` in a for-loop serializes I/O that could be parallelized
with `asyncio.gather([f(x) for x in xs])`. The performance gap is often 10-100x
for network-bound work (HTTP, DB queries, LLM calls).

Deliberately narrow, to flag the textbook antipattern and almost nothing else —
an over-broad version drowned real signal under suppressions. The rule fires
only for:

* a `for` loop whose body is **straight-line** (no `if`/`try`/`with`/`return`/
  `break`/`continue`/`raise`/nested loop — those signal conditional or ordered
  logic, not a parallel map) and awaits a call that **uses the loop variable**
  (so each iteration is a distinct, independent call); or
* a comprehension / generator expression with an `await` in its element or a
  per-element `if` (those have no ordered side effects).

It does NOT fire for: `while` loops (pagination, polling, queue drains — length
unknown, inherently sequential), a loop's once-evaluated iterable
(`for x in await fetch()`), `async for`, test modules (intentional ordering),
a `for` body containing control flow, or modules that import `trio`/`anyio` —
those runtimes have no `asyncio.gather`; their structured-concurrency style
makes a sequential-await loop the deliberate norm (channel sends, ordered
finalization), so the suggested fix does not exist there. Those were the
false-positive sources.

Two further exemptions, both minimized from a 2,657-file third-party sweep:

* **A loop-carried result** — `value = await function(value, element)` — is a
  fold, not a map: iteration N+1 consumes iteration N's result, so there is
  nothing to run concurrently and `gather` cannot express it (anyio's
  `functools.reduce`). Only an `Assign` whose own target is read inside the
  awaited expression qualifies; `results.append(await f(x))` is still a map and
  still fires.
* **Structured-concurrency primitives used without an absolute import** —
  `CancelScope`, `create_task_group`, `start_soon`, `open_nursery`,
  `checkpoint`, `fail_after`, `move_on_after`. trio's and anyio's *own* modules
  reach their runtime through relative imports (`from .. import
  create_task_group`), so the import check above cannot see it and every
  ordered `await listener.aclose()` in their cleanup paths was flagged with a
  fix (`asyncio.gather`) that does not exist in that codebase. `asyncio` has no
  such names, so an asyncio module is unaffected.

References:
- https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently

## Implementation notes

### `_SequentialAwaitVisitor`

Maintains a stack of enclosing loops within the current function. The stack
resets at function boundaries so a loop in an outer function never claims an
`await` in a nested one. Each loop is flagged at most once. A loop's
once-evaluated iterable is excluded (see module comment).

### `_yield_exempt_awaits`

`for x in xs: yield await fetch(x)` streams results one at a time; the yield
imposes an inherent order, so it is not a gatherable map. Awaits reachable
from a `yield` value (without crossing a nested scope) are exempt.

A `Yield` node requires the `yield` keyword in the text, so the substring
test gates the traversal without narrowing what qualifies.

### `_loop_carried_awaits`

`value = await function(value, element)` is a fold: the awaited call reads
the very name the assignment rebinds, so iteration N+1 cannot start before
N finishes and `gather` cannot express it.

### `_same_scope_awaits`

A loop's per-iteration work is only the code that runs in the loop's own
executable scope. An `await` inside a nested `async def`/`lambda` runs when
*that* callable is invoked, not per loop iteration, so it must not make the
loop look like a gatherable map.

### `_uses_structured_concurrency`

trio's and anyio's own modules import their runtime relatively, so the
import check cannot see it; the primitives they use are the visible proof.

A name can only be referenced if it is spelled in the text, so the substring
test gates the traversal without narrowing what qualifies.

### `_imports_non_asyncio_runtime`

`asyncio.gather` does not exist under those runtimes, and their structured
concurrency makes sequential awaits in a loop the deliberate norm.

Naming either runtime in the text is a precondition for importing it, so the
substring test gates the traversal without narrowing what qualifies.
