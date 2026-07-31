# SARJ034 `kwonly-same-type-params` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_kwonly_same_type_params.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`def transfer(source_id: str, target_id: str)` accepts `transfer(target, source)`
without a whisper from the type checker: two positional parameters with the same
primitive type are indistinguishable at the call site, and the resulting swap
bugs pass typecheck, pass review, and fail in production. Reviewers asked for a
keyword-only marker (`*`) in ~11 PRs, always with the same suggestion block:

    # flagged
    def transfer(source_id: str, target_id: str) -> None: ...

    # preferred — call sites must name the arguments
    def transfer(*, source_id: str, target_id: str) -> None: ...

Fires only when EVERY narrowing gate holds:

* the function has >= 2 positional parameters (excluding a leading `self`/`cls`)
  whose annotations are IDENTICAL and are a bare primitive (`str`, `int`,
  `float`, `bool`) — primitives carry no domain meaning, so the call site has
  nothing to disambiguate with. Same-typed domain objects
  (`a: Money, b: Money`) are left to review: arithmetic/comparison helpers over
  a domain type are often legitimately symmetric.

Never flags — these signatures cannot or should not change:

* dunder methods (`__init__`, `__eq__`, ... — protocol-pinned or pervasively
  called positionally),
* `visit_*` / `test_*` functions (visitor dispatch and pytest fixtures are
  framework-called with positional conventions),
* functions decorated `@override` / `@overload` / `@abstractmethod` (an
  override cannot unilaterally change the parent's signature; overload/abstract
  signatures are contracts),
* HTTP route handlers — any decorator of the shape
  `@<name>.get/post/put/patch/delete/head/options/websocket(...)` (`router`,
  `app`, `api`, ...): FastAPI binds handler parameters by NAME (path/query
  keys), so the positional shape is never called swap-prone by a human,
* CLI command handlers — `@click.*` / `@typer.*`, or `@<name>.command(...)` /
  `@<name>.group(...)`: click and typer bind handler parameters by NAME from
  the declared options/arguments and the human call site is a shell command
  line, not a Python call (3 corpus hits: `httpx/_main.py:452`,
  `black/src/blackd/__init__.py:96`,
  `black/scripts/diff_shades_gha_helper.py:167`),
* test files (`_paths.is_test_path`) — test fakes and helpers mirror the
  signatures of the code under test and cannot unilaterally change them,
* generated files (`_paths.is_generated`) — the signature mirrors
  whatever the generator emits (found via trio's `_generated_io_kqueue.py`),
* functions whose name is referenced as a VALUE anywhere in the module
  (passed to a registry, returned, stored) — the signature is a callback
  protocol shared with other implementations and cannot change unilaterally
  (found via attrs' `fmt_setter` family and sphinx `app.connect` handlers),
* the implementation of `@overload`-decorated stubs — a same-named sibling
  in the same scope carries `@overload`, so the impl's positional shape is
  pinned by the declared overloads (found via trio's `getsockopt`),
* signatures whose same-typed params differ only by a numeric suffix
  (`value_1: float, value_2: float`) — the numbering declares the function
  symmetric, so argument order genuinely does not matter (found via
  pydantic's `almost_equal_floats`),
* methods that provably override a base-class method — the body calls
  `super().<same name>(...)`. An override cannot narrow the inherited calling
  convention without breaking every caller that holds the base type
  (`httpx/_models.py:1257`, `_CookieCompatRequest.add_unredirected_header`),
* methods implementing a duck-typed stdlib protocol (`seek`, `read`, `write`,
  `add_unredirected_header`, `recv`, `setsockopt`, ...). The stdlib itself is
  the caller and calls them POSITIONALLY — `io` calls `f.seek(0, 2)`,
  `http.cookiejar` calls `req.add_unredirected_header("Cookie", v)` — so
  inserting `*` is not a style change, it is a `TypeError` at runtime (5
  corpus hits: `requests/cookies.py:89` and `:95`, `httpx/_models.py:1257`,
  `anyio/streams/file.py:97`, `rich/progress.py:270`),
* parameters named `__x` (leading double underscore, no trailing) — PEP 484
  spells positional-only parameters that way, so they cannot be made
  keyword-only at all (`rich/_null_file.py:24`, `NullFile.seek`),
* same-typed groups drawn entirely from a conventional ordered vocabulary —
  `x`/`y`/`z`, `width`/`height`, `red`/`green`/`blue`, `start`/`stop`/`step`,
  `row`/`column`, `top`/`right`/`bottom`/`left`, `year`/`month`/`day`,
  `hour`/`minute`/`second`. Position IS the notation for these: nobody reads
  `Control.move(2, 5)` as ambiguous, and `move(*, x=2, y=5)` is worse (11
  corpus hits, e.g. `rich/control.py:79`, `rich/segment.py:462`,
  `rich/color.py:409` `from_rgb`, `anyio/itertools.py:271` `count`),
  The vocabularies are closed sets of domain notation, NOT a general
  short-name escape: single-letter placeholders stay flagged
  (`def _newer(a: str, b: str)`, `blib2to3/pgen2/driver.py:287`), because
  there the call site genuinely cannot tell the two apart.
* parameters that are already keyword-only (behind `*`) or positional-only
  (before `/`, a deliberate positional API). Note this is per-parameter, not
  per-signature: `def f(a: str, b: str, *, c: int)` is still flagged, because
  `a`/`b` sit BEFORE the marker and remain swap-prone. A `*args` variadic
  likewise does not shield same-type params in front of it.

Parameters with defaults still count (documented judgment call: a default does
not make the call site any less swappable).

Symmetric functions (`def add(x: int, y: int)`) where order genuinely does not
matter are suppressed with `# sarj-noqa: SARJ034 — <reason>`.

## 2026-07 false-positive audit

Over the 12-repo corpus: **1,405 findings**, 148 of them first-party. Two
independent seeded samples of 50 read against source put the false-positive rate
at **10%**. Three guards landed, taking the rule to **1,349**; a fourth was built,
measured and declined.

* **Letter-suffix symmetry** — same-typed params differing only by a
  single-letter suffix (`policy_id_a: str, policy_id_b: str`). `_a`/`_b` labels
  the two sides of a commutative helper (`compare_versions`) exactly as `_1`/`_2`
  does, and the numeric arm alone left those firing. **42 of 1,405 (3.0%), no true
  positive lost.** Bounded to ONE shared stem plus one letter behind an
  underscore, so `source_id`/`target_id` — different stems — is untouched.
* **Test-support trees one directory name away from `tests/`.** `is_test_path`
  recognises exactly the segments `tests` and `test`, so a shared test-helper
  package named `tests_common/`, `test_utils/` or `system_tests/` was being linted
  as production code although the existing test exemption is meant to cover it.
  Matched as a whole DIRECTORY segment against `^tests?_.+$|^.+_tests?$` —
  segment-anchored so it cannot reach a module named `testing_commands.py`, which
  contributes 3 legitimate findings. **8 of 1,405 (0.6%), no true positive lost.**
  Kept local to this rule rather than folded into `_paths.is_test_path`, which
  several rules with different charters share.
* **Numbered migration files** — a `migrations/` directory plus an `NNNN_`
  filename prefix. A migration is an append-only historical artifact: it has
  already run everywhere, its signature is pinned by the recorded history, and the
  only edit a lint finding can produce there is a new migration. **6 of 1,405, no
  true positive lost.**

### DECLINED: a nested-closure guard

A nested closure with a short parameter list whose only call sites are a few lines
below it accounts for **7 findings**. Not guarded: "the scope is small" is an
argument about how likely the swap is, not evidence that the signature was never
swap-prone, and a predicate that broad **has no upper bound**.

### Measured and deliberately NOT changed

Recorded so it is not re-litigated:

* dunder methods: **0 of 1,405**. The exemption is already load-bearing upstream
  of the count; there is nothing left to guard.
* `*args`-passthrough signatures: **0 of 1,405**.
* `start`/`end`, `first`/`last`, `min`/`max`, `host`/`port`: **0 findings each**.
  These pairs cannot fire, because a group also needs a risky identifier token
  (`_RISKY_NAME_PART_RE`) to clear `_is_high_value_group` — so adding them to
  `_CONVENTIONAL_ORDER_GROUPS` would move no finding at all.
* the `bool` arm is the single largest population at **369 of 1,405**, and reading
  it returned 4 true positives, 3 arguable and **0 false positives**. It stays.

## Implementation notes

### `_overload_stub_names`

The undecorated implementation of an overloaded function shares its name
with the stubs; its positional shape is pinned by the declared overloads.

### `_value_referenced_names`

A function whose name appears as a bare value — passed to a registry,
returned, stored in a collection — implements a callback protocol whose
positional shape is shared with other implementations; it cannot go
keyword-only unilaterally.

### `_is_symmetric_numbering`

`value_1`/`value_2` (or `x1`/`x2`) declare a symmetric function — argument
order genuinely does not matter, so the group is not swap-prone.

### `_is_conventional_order`

`x`/`y`, `width`/`height`, `red`/`green`/`blue`, `start`/`stop`/`step`:
position IS the notation, so the call site is not ambiguous and inserting
`*` makes it noisier, not safer.

### `_is_high_value_group`

Booleans are always high-risk because positional `True, False` carries no
call-site meaning. Other primitives fire only when the parameter names carry
production-domain identifiers or directed relationships (`source_id`,
`target_id`, `old_key`, `new_key`, `input_path`, `output_path`). This keeps
math / algorithm APIs such as `power(base, exponent)` and `f(a, b)` out of
the default rule while preserving the bug class the rule was written for.

### `_swap_prone_annotation`

A leading `self`/`cls` is excluded. Only bare-`Name` primitive annotations
participate — `str | None`, `Literal[...]`, and domain types never group.
Only `args.args` (positional-or-keyword) parameters count: keyword-only
parameters (behind `*`) cannot be swapped positionally, and positional-only
parameters (before `/`) are a deliberate positional API. A `*`/`*args`/`/`
marker therefore exempts exactly the parameters it protects — never the
same-type pair sitting in front of it.

A parameter named `__x` is positional-only by the PEP 484 spelling and so
cannot be made keyword-only at all; it never groups.

A group whose parameter names differ only by a numeric suffix
(`value_1`/`value_2`) or are drawn entirely from a conventional ordered
vocabulary (`x`/`y`, `width`/`height`) is not swap-prone and never groups.

### `_is_route_decorator`

Matches `<Name>.<http method>` — optionally called — for any receiver name
(`router`, `app`, `api`, ...). FastAPI binds handler parameters by name, so
a route handler's positional shape is not swap-prone at any call site.

### `_calls_super_same_name`

That call is proof the method overrides an inherited one: its calling
convention belongs to the base class, and narrowing it to keyword-only
breaks every caller holding the base type.

### `_is_cli_command_decorator`

Matches `@click.*` / `@typer.*` (any attribute: `command`, `option`,
`argument`, ...) and `@<name>.command(...)` / `@<name>.group(...)` for a
click group or typer app. Both frameworks bind handler parameters by NAME
from the declared options, and the human-facing call site is a shell
command line — the positional shape is never typed by a caller.
