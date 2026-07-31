# SARJ032 `prefer-match-assert-never` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_match_assert_never.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Dispatch over a closed set of variants that quietly does nothing for "anything
else" is the highest-volume exhaustiveness bug in review feedback: a new variant
is added, no branch handles it, and the code silently no-ops instead of failing
loudly. `typing.assert_never` (or a `raise`) in the fallthrough turns the missed
variant into a pyright error / instant crash. The TS linter enforces the same
invariant via require-assert-never.

Two deterministic detectors, mirroring SARJ003's corroboration discipline (no
type inference is available, so each detector demands structural proof that the
dispatch is over a CLOSED set — corpus validation showed that without this
gate, matches over open-set data such as external API strings and free-form
payload shapes dominate and are deliberate fall-throughs, not bugs):

1. **Silent `case _:` in a closed-set `match`.** A `match` with at least two
   real, unguarded `case` arms that are all either

   * enum-member values of ONE owner class (`case Kind.A:` / `case Kind.A |
     Kind.B:`) — dotted members of a single class are a closed set someone
     owns. The owner name must be bound by a module-scope `class` statement in
     this file or by a `from x import Kind` binding: those are the shapes that
     name a class. Attribute access on a name bound by `import constants`
     (a module of loose constants) or on a plain variable (`cfg.A`) is NOT
     member access on a closed set and never qualifies, or
   * class patterns over classes **defined at module scope of this module**
     (`case Created():`) — the SARJ003 local-union gate. Classes defined
     inside some function elsewhere in the file are invisible here and do not
     make an unrelated match closed,

   whose final `case _:` (bare wildcard, no guard, no capture name) body is
   exactly `pass`, bare `return`, or `return None`. String/number literal
   cases, mapping/sequence patterns, and imported class patterns never qualify:
   they routinely match open-set data where ignoring the rest is the intended
   behavior. `case _: return False` and other value-returning defaults are also
   not flagged — a predicate's default answer is a legitimate result.

   One further corpus-validated exemption: when EVERY real arm's body is purely
   assignments (`x = ...` refinement), the match is the default-then-refine
   idiom — defaults are set before the match and the silent wildcard means
   "keep the defaults", which is defined behavior, not a swallowed variant. The
   detector fires only when at least one arm *does* something (a call, return,
   raise), because that is what a missed variant silently skips.

        # flagged
        match kind:
            case Kind.A: ...
            case Kind.B: ...
            case _:
                pass          # new Kind member silently ignored

        # preferred
            case _:
                assert_never(kind)

2. **`if/elif` chain over a local enum with a silent `else`.** Every arm
   compares the SAME variable via `==` (or `in` over a tuple/list/set) against
   members of the SAME class, that class is **defined at module scope of this
   module** with an `Enum`-family base (`Enum`, `StrEnum`, `IntEnum`, `Flag`,
   `IntFlag`, `ReprEnum`), and the terminal `else` is exactly `pass` / bare
   `return` / `return None`. For an imported name the rule cannot prove it is
   an enum (it could be a constants holder), so imported classes are never
   flagged. A chain whose head is NOT an enum comparison (e.g. a null-check
   first: `if x is None: ... elif x == Status.A: ...`) does not shield the
   enum sub-chain that starts at the first enum arm — that sub-chain is
   checked on its own. The default-then-refine exemption applies here exactly
   as in detector 1: when EVERY arm body is purely assignments, the silent
   `else` means "keep the pre-set defaults" and is not flagged.

        # flagged
        class Status(StrEnum):
            OPEN = "open"
            CLOSED = "closed"

        if status == Status.OPEN:
            ...
        elif status == Status.CLOSED:
            ...
        else:
            return None       # new Status member silently ignored

3. **Handler dict that does not cover the enum.** A `dict` literal whose keys
   are all members of ONE enum defined at module scope of this module, whose
   values all look like handlers (a name, an attribute, or a lambda — never a
   literal), and which names FEWER members than the enum declares. This is the
   lookup-table spelling of the same bug: `HANDLERS[kind]` raises `KeyError` on
   the missed member if you are lucky and `HANDLERS.get(kind)` silently returns
   `None` if you are not, and neither pyright nor a `match` statement is there
   to notice. The message names the shortfall so the missing members are
   obvious.

        # flagged — Kind has three members, the map has two
        class Kind(StrEnum):
            A = "a"
            B = "b"
            C = "c"

        HANDLERS = {Kind.A: handle_a, Kind.B: handle_b}

   Deliberately NOT flagged here: a map whose values are literals (that is a
   lookup table of data — a partial one is routinely intentional, e.g. "only
   these two members have a display colour"); a map that spreads `**other`
   (its real key set is not visible); a map whose name is later `.update(...)`d
   or assigned into by subscript anywhere in the file (it is built in pieces on
   purpose); and any map over an imported enum, since the rule cannot see how
   many members that enum has and guessing would invent findings.

A deliberate ignore-the-rest dispatch (e.g. classifying external ids where the
provider can add values at any time) is suppressed with
`# sarj-noqa: SARJ032 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.assert_never
- https://typing.python.org/en/latest/spec/narrowing.html#assert-never-and-exhaustiveness-checking

## Implementation notes

### `_enum_comparison`

Every compared value must be a member attribute of the SAME local enum class.

### `_silent_enum_chain`

Each nested `elif` that genuinely continues the chain (same target, same
enum) is recorded in `consumed_elifs` so the caller does not re-check it as
a chain head of its own. An `elif` that does NOT continue the chain (or any
`elif` behind a non-matching head) is deliberately left unconsumed: the
sub-chain starting there is a dispatch in its own right and gets its own
check — a null-check head must not shield the enum chain behind it.

### `_all_one_owner_member_arms`

The owner must be a name that can actually bind a class here: defined by a
module-scope `class` statement or bound by `from x import Cls`. A plain
variable or a name bound by `import constants` (a module object) never
counts.

### `_is_silent_body`

Only `pass`, bare `return`, and `return None` qualify. A value-returning
default (`return False`, `return ""`) is a legitimate answer, and any other
statement (log call, raise, assignment) is deliberate handling.

### `_silent_closed_set_wildcard`

Requires >= 2 real unguarded closed-set arms before it, a bare unguarded
uncaptured wildcard, and a wildcard body that is exactly `pass` / bare
`return` / `return None`.

### `_importfrom_bound_names`

A `from`-imported name is the shape that binds a class directly, so
`Kind.MEMBER` on such a name can be member access on a closed set. Names
bound by plain `import module` are module objects — attribute access on
them (`constants.CREATED`) reaches loose module-level constants, never an
owned member set — so they are deliberately NOT collected.

### `_is_handler_value`

A literal value makes the dict a data table, where a partial mapping is
routinely deliberate; a name, attribute or lambda makes it a dispatch table.

### `_incomplete_dispatch_map`

Requires a single `Name` target, a `dict` literal value with no `**` spread,
at least `_MIN_ARMS` keys that are ALL members of one module-scope enum, all
values handler-shaped (name / attribute / lambda), and a name that is never
grown elsewhere in the module.

### `_grown_dict_names`

`HANDLERS.update(...)`, `HANDLERS.setdefault(k, v)` and `HANDLERS[k] = v`
all mean the literal is a starting point rather than the whole map, so its
key count says nothing about coverage.

### `_enum_member_names`

A member is a plain `NAME = <value>` assignment in the class body. Methods,
annotations without a value (`x: int`), and private/dunder names are not
members. Members sharing one constant value are ALIASES of a single member
(`AKA = "open"` beside `OPEN = "open"`), so they are counted once —
over-counting members would invent a shortfall that does not exist.

### `_module_scope_classdefs`

Deliberately does NOT descend into function bodies: a class defined inside
some unrelated function is not visible where a `match` elsewhere in the
file dispatches, so it must not make that match look closed-set.
