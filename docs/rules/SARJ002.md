# SARJ002 `inefficient-string-concat-in-loop` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_inefficient_string_concat_in_loop.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Growing a string with `s += <str>` or `s = s + <str>` inside a loop is O(n²)
in CPython because strings are immutable — each step allocates a new string and
copies the previous one. Append to a list and `"".join(parts)` at the end for
O(n).

The rule fires only on genuine single-string accumulation. It deliberately does
NOT treat a `str()/repr()/format()` coercion, a `.join()` / `.format()` /
`.strftime()` call, or an `os.path.join(...)`-style call as accumulation — those
are either the prescribed remedy or a bounded per-iteration transform, not the
O(n²) defect. Per-slot writes (`parts[i] = ...`) and idempotent rebinding
(`x = f(x)`) are likewise excluded.

A target that is freshly (re)bound earlier in the same loop body — `desc = ...`
then `desc += suffix`, or a tuple unpack `obj, path = q.popleft()` then
`path += ...` — is loop-local: it starts empty each iteration, so the growth is
bounded, not cross-iteration accumulation. Only a target initialised BEFORE the
loop is a true O(n²) accumulator, so a preceding non-accumulating rebind of the
target inside the loop suppresses the diagnostic.

A target whose intermediate values are CONSUMED per iteration is a probe, not
an accumulator — `"".join` at the end cannot replace it. Two consumption
shapes are exempt (both minimized from pydantic's unique-name generation):

* the enclosing `while` test reads the target
  (`while name in taken: name += "_"`), or
* the loop body reads the target outside its own accumulation statement
  (`globals.setdefault(reference_name, model)` then `reference_name += "_"`).

A pure accumulator is only ever written inside the loop, so it keeps firing.

References:
- https://docs.python.org/3/library/stdtypes.html#str.join
- https://wiki.python.org/moin/PythonSpeed/PerformanceTips

* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package under `python/sdk/src/` accounts for all of them.

## Implementation notes

### `_looks_like_string`

Deliberately conservative: a bare call (`str(x)`, `",".join(...)`,
`os.path.join(...)`) is NOT treated as a string — those shapes also appear in
benign one-shot reassignment and are not the accumulation defect.

### `_string_typed_locals`

Used as the string-typed signal for bare-`Name` accumulation (`buf += line`):
a numeric accumulator (`total = 0`) is absent, so `total += x` stays clean.

### `_iter_binding_targets`

Subscript leaves (`acc[i] = ...`) are per-slot writes, not a rebind of the
accumulator itself, so they are skipped.

### `_loop_local_reassignments`

Only rebinds that are NOT self-accumulation (`s = s + x`) count — those are the
defect itself, not a fresh reset. Nested loops / functions / classes are their
own scope and are excluded.

### `_loop_read_names`

An `s += x` stores (no Load of `s`); an `s = s + x` self-read is excluded.
Any other Load — a call argument, a subscript key, a comparison — consumes
the intermediate value, which marks the target as a probe. Nested
function/lambda bodies are excluded (they run in their own scope).

### `_ConcatVisitor._is_loop_local_target`

A target rebound (not self-accumulated) before the concat inside the same
innermost loop body starts empty each pass, so its growth is bounded.

### `_ConcatVisitor._is_probe_target`

A target read by an enclosing while test, or read inside a loop body
outside its own accumulation, is a probe (unique-name generation):
every intermediate value matters, so `join` cannot replace the growth.
