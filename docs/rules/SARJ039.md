# SARJ039 `prefer-module-level-constant` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_module_level_constant.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Python port of the TypeScript rule `prefer-module-level-constant`. A lookup
table, allow-list, membership `frozenset` or validation regex written at the top
of a function is rebuilt on every single call. Three costs, in increasing order
of severity:

1. Allocation — every call re-walks the display and re-allocates the list /
   dict / set / tuple, and `re.compile` re-parses the pattern (the module-level
   `re` cache is bounded and evicted wholesale, so it is not a substitute).
2. Discoverability — a domain constant buried in a function body is invisible
   to the next reader and cannot be imported, tested, or reused, so it gets
   duplicated in the next function that needs it. That is the defect class: the
   duplicated copies drift apart.
3. Review churn — this was the single most frequent recurring review comment in
   the mined PR corpus, in Python and TypeScript alike.

Fires on a local binding (`x = ...` / `x: T = ...`) inside a `def` / `async def`
whose value is one of:

* a list / dict / set / tuple display, or `frozenset([...])`, with at least
  `_MIN_ELEMENTS` top-level entries and where EVERY leaf (dict values and keys
  included) is an `ast.Constant` — or a signed numeric constant, or a nested
  display of the same, up to `_MAX_LITERAL_DEPTH`; or
* `re.compile("<literal>")`, optionally with constant flags
  (`re.I`, `re.I | re.M`, a plain int).

"Every leaf is a constant" is the load-bearing gate, not a stylistic
preference. A `Name`, `Attribute`, `Call`, comprehension or f-string leaf means
the value can capture a parameter or observe call-time state, so hoisting it
would be a `NameError` or a behaviour change. Gating on constants kills that
entire false-positive class — including the common
`allowed = [user_id, "admin"]` shape — outright.

Escape / mutation analysis is deliberately STRICT, and stricter than the
TypeScript original. A module-level Python constant is import-time-shared
mutable state living for the life of the process: a wrong hoist is a
cross-request data-corruption bug, not a style regression. So the rule bails
unless EVERY reference to the binding inside the enclosing function is a
provably non-mutating, non-escaping read.

Deliberately NOT flagged:

* **Rebound names.** The name must be bound exactly ONCE in the function. Any
  second binding bails: re-assignment, `x += [...]`, a walrus rebind, `del x`,
  a `global` / `nonlocal` declaration, a `for` target, `with ... as x`,
  `except ... as x`, a comprehension or `match` capture target, an `import as`,
  a same-named nested `def` / `class`, or a parameter of the same name.
* **Mutated collections.** Any method call on the binding that is not on the
  explicit safe list (`get`, `keys`, `values`, `items`, `copy`, `index`,
  `count`) is treated as mutating — default-DENY, so `.append` / `.extend` /
  `.insert` / `.remove` / `.pop` / `.clear` / `.sort` / `.reverse` / `.update` /
  `.add` / `.discard` / `.setdefault` / `.popitem` / `.__setitem__` are covered
  along with anything a future stdlib grows. A subscript STORE (`x[k] = v`),
  `del x[k]`, or an attribute store (`x.attr = v`) likewise bails. A compiled
  regex gets its own safe-method list (`match`, `search`, `fullmatch`,
  `findall`, `finditer`, `split`, `sub`, `subn`) since `re.Pattern` is immutable.
* **Escaping values the caller may mutate.** `return x`, `yield x`, passing `x`
  bare as a positional or keyword argument to a call that is not a known
  non-retaining consumer, `self.x = x`, `d[k] = x`, embedding it in a
  `[x]` / `{...}` display, aliasing it (`y = x`), a `*x` / `**x` spread, or
  capturing it in a nested `def` / `lambda` / `class` body. Once the value
  leaves the function this rule cannot see what happens to it.
* **Safe consumers still fire** — `len(x)`, `sorted(x)`, `set`/`frozenset`/
  `list`/`tuple`/`dict`, `any`, `all`, `min`, `max`, `sum`, `enumerate`,
  `reversed`, `iter`, `json.dumps`, the non-mutating methods above, `x` as a
  `for`/comprehension iterable, `k in x`, a subscript LOAD (`x[0]`), a
  comparison, and f-string interpolation. Note `sorted(x)` and `list(x)` COPY,
  so they are reads, while `x.sort()` mutates in place and bails.
* **Tiny displays** (`< _MIN_ELEMENTS` entries) read better next to their use.
* **Test files and generated files** (`_paths.is_test_path` /
  `_paths.is_generated`): fixture tables belong next to the assertion
  that explains them, and generated code mirrors its generator.
* **Bindings the function never reads** and **functions that call `locals()` /
  `vars()`**. Both are the same hole in the escape analysis: a local can leave
  the frame reflectively, without ever appearing as a `Name` load. The famous-repo
  sweep found three (`rich/rich/scope.py:82`, `:83` — `list_of_things` /
  `dict_of_things` rendered by `render_scope(locals(), ...)`; `rich/examples/log.py:54`
  — `foo = (1, 2, 3)` read only by Console's `log_locals=True` frame inspection).
  A binding with zero reads has no use site to justify the hoist anyway, and
  hoisting it changes what `locals()` returns.

One real difference from the TypeScript original: that rule must never hoist a
`/g` or `/y` regex, because a JavaScript RegExp object carries `lastIndex`
across calls to `.test()` / `.exec()`, so a shared instance resumes mid-string
on the next call. A Python compiled pattern carries no per-object scan state —
position is an argument to `.match()` / `.search()`, and `re.finditer` returns a
fresh iterator — so there is no equivalent carve-out here and every constant
`re.compile` is reported.

There is no autofix: hoisting has to pick an insertion point and may collide
with an existing module-scope name, and a wrong automated hoist is worse than
the warning.

A deliberate per-call rebuild (a fresh mutable default the rule cannot see
through, say) is suppressed with `# sarj-noqa: SARJ039 — <reason>`.

## Implementation notes

### `_is_safe_method_call`

A bare `x.attr` read that is not called hands the bound method out, and an
attribute store mutates, so both are unsafe.

### `_rebinds_name`

Covers the binding forms that carry the name as a plain string:
`except ... as x`, `global` / `nonlocal`, a nested `def` / `class`, an
`import as`, and `match` captures.

### `_is_safely_hoistable`

Default-deny: the binding must be bound exactly once, must be read at least
once, and every other reference must be recognised as safe, so an unfamiliar
usage suppresses the report rather than risking a hoist that shares mutable
state across calls.

### `_is_constant_only`

No name, no attribute, no call, no comprehension, no f-string, no spread. A
constant-only value cannot capture a parameter, cannot observe call-time
state, and cannot have side effects, which is exactly what makes the hoist
provably safe.

### `_is_constant_flags`

Accepts an int literal, an `re.<FLAG>` attribute, and `|` combinations of
those — the only flag shapes real code uses.

### `_reads_frame_locals`

Every local then escapes without appearing as a `Name` load — `rich`'s
`render_scope(locals(), ...)` renders the very tables this rule would hoist
out of the frame — so no binding in such a function is safe to move.

### `_scope_of`

A node is "nested" when it lives inside an inner `def` / `lambda` / `class`,
i.e. in a scope that can outlive or re-enter the enclosing call.
