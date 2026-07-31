# SARJ023 `stepdown` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_stepdown.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A file should read top-to-bottom like a newspaper: public API first, then the
private helpers it uses. This rule encodes only the fully unambiguous core of
that convention.

The rule is deliberately restricted to helpers with EXACTLY ONE same-scope
caller. For a single-caller helper there is one canonical stepdown position —
immediately below its sole caller — so a violation ("helper sits above its only
caller") has a single, non-arbitrary fix and the reorder is a clear readability
win. Helpers with two or more callers are OUT OF SCOPE: a shared helper has no
canonical "below which caller?" answer (stepping below one caller reads wrong
relative to the others), and the verdict would flip whenever a caller moves.
That multi-caller arbitrariness is exactly the disputed-churn class this
redesign removes.

Fires on:
1. **Module-level helper above its one caller** — a private top-level function
   (`_name`) referenced at call time by EXACTLY ONE top-level function/class,
   and defined above that caller.
2. **Class-level private method above its one caller** — a private, non-dunder
   method referenced via `self._name` / `cls._name` by EXACTLY ONE sibling
   method, and defined above it.

Never fires on:
- Public defs and private top-level classes (declarations, not helpers).
- Unused helpers (no same-scope caller).
- Helpers with two or more same-scope callers (no canonical stepdown target).
- Helpers whose sole caller is a CLASS. A class is a scope, not a call site:
  the real caller is a method inside it, and no module-level position sits
  "directly below" that method — the helper would land after the class's
  closing line, which for a large class is hundreds of lines past the
  reference (`fastapi/routing.py:214`, `_wrap_gen_lifespan_context`, whose
  only "caller" is `APIRouter` spanning lines 2219-6405). Collapsing a whole
  class into one caller also hides genuine multi-caller ambiguity —
  `pydantic/_internal/_generate_schema.py:286` is referenced from three
  different `GenerateSchema` methods yet counted once, exactly the arbitrary
  "below which caller?" case this rule excludes elsewhere. Classes still
  COUNT as callers, so a helper shared by a class and a function stays
  suppressed as multi-caller (31 corpus hits removed, e.g.
  `httpx/_models.py:67`, `rich/console.py:505`, `requests/adapters.py:85`).
- Mutual / indirect / two-node recursion — cycles have no valid stepdown order.
- Names that are position-pinned by an import-time / class-creation-time
  reference: module-level statements, decorator lists, default arguments,
  annotations, class-body attribute values. Moving those breaks runtime.
- Names referenced inside `if TYPE_CHECKING:` blocks (pinned, not call sites).
- Names defined more than once in the scope (`@overload`, `@x.setter`,
  conditional defs), reassigned at module/class scope, or locally rebound
  inside the calling function itself — the reference there resolves to the
  local, so that function is not counted as a caller. A local binding in some
  OTHER (non-calling) function does not suppress the helper.
- Methods decorated `@property` / `@cached_property` (read as attributes) and
  `@abstractmethod` (interface contracts conventionally sit together).
- Methods reached through inheritance: a private method is not flagged when an
  in-module ancestor or descendant class references it via
  `self` / `cls` / `super()`. Same-class caller counting alone would report a
  false "only caller"; the actual caller may live in a sub/superclass (SQLAlchemy
  `_code_str`). Siblings are excluded — an identically-named sibling method is a
  different method. Callers in classes outside the module remain invisible to
  syntactic analysis.
* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package accounts for all of them.

## Implementation notes

### `_name_loads`

A lambda body is deferred — it runs only when the lambda is later invoked,
not at the point the lambda literal is created — so names inside it are not
import-time pins. Lambda argument defaults DO evaluate at creation time and
are kept.

### `_runtime_nodes`

Skips decorator lists / defaults / annotations of the given defs' nested
defs only where they run at definition time relative to the enclosing
scope; inside an already-deferred body, nested decorators and defaults DO
run at call time and are included. Annotations and `if TYPE_CHECKING:`
bodies are never included.

### `_deferred_body`

For a function that is its body; for a class it is the bodies of its
(recursively nested) methods — class-body statements run at class-creation
time and are handled as pinning references instead.

### `_family_external_refs`

A private method can be called through inheritance — a subclass's
`self._m()` / `super()._m()`, or a base method's `self._m()` that dispatches
to a descendant's override. Counting only same-class call sites therefore
undercounts callers and produces false "only caller" claims (SQLAlchemy
`_code_str`). For each class this walks its in-module ancestors and
descendants (by base-name matching) and returns the self/cls/super method
references those relatives make. A method named here has a caller reachable
through dispatch from outside its own class body and must not be flagged as
single-caller. Siblings share an ancestor but not dispatch, so they are
excluded — a sibling's identically-named private method is a different
method, and lumping them would wrongly suppress genuine single-caller
helpers.
