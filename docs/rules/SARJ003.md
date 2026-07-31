# SARJ003 `no-isinstance-union-chain` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_isinstance_union_chain.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A chain of `if isinstance(x, A): ... elif isinstance(x, B): ... else: raise` where every
`A`, `B`, ... is a class **defined in this same module** and the chain terminates
exhaustively is dispatch over a locally-owned discriminated union. `match`/`case` with
`assert_never` in the fallthrough is strictly better: pyright reports an error the moment a
new variant is added and a branch is missed — a plain `isinstance` chain silently falls
through.

    # flagged
    class ApiKeySubject: ...
    class JwtSubject: ...

    if isinstance(subject, ApiKeySubject):
        ...
    elif isinstance(subject, JwtSubject):
        ...
    else:
        assert_never(subject)

    # preferred
    match subject:
        case ApiKeySubject():
            ...
        case JwtSubject():
            ...
        case _:
            assert_never(subject)

The rule fires ONLY when both gates hold, because only then is a mechanical rewrite to an
exhaustive `match` both correct and beneficial:

1. **Local-union gate.** Every `isinstance` arm tests a bare `ast.Name` that resolves to an
   `ast.ClassDef` in this module — not an imported name, not a dotted `pkg.Cls`, not a
   builtin/stdlib type. Probing open-set types the module does not own
   (`property`, `cached_property`, `Path`, `Decimal`, `dataclasses.Field`, ...) is a
   legitimate runtime check, not closed-union dispatch, and is never flagged.
2. **Exhaustiveness gate.** The chain ends in a terminal `else`/final branch that raises,
   returns, asserts, or calls an `assert_never`-style helper. An *open* chain — no `else`,
   or a permissive `else` that silently falls through — is not equivalent to an exhaustive
   `match` and must not be flagged, since converting it would change behavior.

This is still a heuristic (a locally-defined class could be re-exported, an imported class
could be the real union member). Suppress a deliberate boundary chain with
`# sarj-noqa: SARJ003 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.assert_never
- https://typing.python.org/en/latest/spec/narrowing.html#assert-never-and-exhaustiveness-checking

## Implementation notes

### `_isinstance_single_type`

Tuple-form `isinstance(x, (A, B))` returns a Tuple type_node, which the caller
rejects (not an `ast.Name`).

### `_is_exhaustive_terminal`

An open chain (no `else`) or a permissive `else` that just does work and continues is
NOT equivalent to an exhaustive `match`, so it does not qualify.

### `_qualifying_chain_length`

Requires every arm to be `isinstance(<same target>, <local ClassDef name>)` and the
chain to end in an exhaustive terminal `else` (raise / return / assert / assert_never).
