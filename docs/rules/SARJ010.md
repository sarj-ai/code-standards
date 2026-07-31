# SARJ010 `no-unreachable-after-terminal` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_unreachable_after_terminal.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A terminal statement (`return`, `raise`, `break`, `continue`) ends control
flow for the enclosing block. Any statement that immediately follows it in the
same statement list can never execute — it is dead code, almost always a
logic error (e.g. a `return` placed before cleanup, or a stray statement after
a `break`).

This is a near-pure structural check: for every statement-list field on every
node (the `body`/`orelse`/`finalbody` lists of Module, FunctionDef, If, For,
While, With, Try, ExceptHandler, etc.), if a terminal appears before the last
element of that list, the statement immediately after it is unreachable.

A terminal only ends control flow where Python actually allows it, so the check
tracks context: `return` counts only inside a function, and `break`/`continue`
only inside a loop (a loop's `else:` clause is outside the loop for that
purpose, matching Python's own binding). `raise` is terminal anywhere. A
module-scope `return` is a `SyntaxError` — the file could never execute at all —
so treating the statements after it as "dead" says nothing true about the code.
A 2,657-file third-party sweep produced 10 findings and 5 of them were exactly
that shape (black's formatter fixtures under `tests/data/cases/`, which hold
statement fragments lifted out of their functions).

## Implementation notes

### `_child_context`

A function body opens a function scope and closes any enclosing loop (a
`break` inside a nested `def` does not bind to the outer loop); a class body
closes both. A loop's `body` is inside the loop, but its `orelse` is not —
`break` in a `for ... else:` binds to the *enclosing* loop, matching Python.

### `_is_terminal`

`raise` is terminal anywhere. `return` is only legal — and therefore only
terminal — inside a function, and `break`/`continue` only inside a loop.
Outside those contexts the statement is a `SyntaxError` that no interpreter
would ever run, so nothing after it is meaningfully dead.
