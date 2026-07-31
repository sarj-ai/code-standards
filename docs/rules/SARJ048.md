# SARJ048 `no-first-party-private-import` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_first_party_private_import.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Reaching past a module's public surface is a design finding when the module is
ours and an unavoidable fact of life when it is not. `from app.stores.order_store
import _row_to_order` says a first-party module has a helper someone needed and
did not export; the fix is to export it. `from livekit.agents.inference_runner
import _InferenceRunner` says a dependency moved an API private in a minor
release — livekit-agents 1.6.6 did exactly this to a first-party custom EOU
runner — and there is no edit that satisfies the lint short of vendoring the
library or
pinning it forever. A rule that cannot tell those apart is an instruction to
perform an impossible edit, which is how blanket suppressions get born.

This rule fires ONLY on the first case. Third-party privates are never flagged.

Ruff's `PLC2701 import-private-name` is the rule this replaces, and it does not
make the distinction. Its exemption is *same top-level package*, not
*first-party*: measured over one first-party repo's five packages it produced
80 findings, of
which 77 were first-party (real) and 3 were livekit reaches with no available
fix. Ruff has no configuration surface that separates them — the check is
purely lexical and never resolves an import to a location on disk. Pyright's
`reportPrivateUsage` fires on the same third-party import and likewise has no
first-party/third-party knob, so it still needs a per-line `# pyright: ignore`
at the reach site; this rule does not change that, it only stops ruff from
demanding a second, unfixable suppression on the same line.

Fires on:

* `from <first-party module> import _name` — a private symbol,
* `from <first-party package>._private_module import Name`, and
  `import <first-party package>._private_module` — a private *submodule*, which
  is just as much a non-public surface as a private symbol.

Deliberately NOT flagged:

* **anything third-party.** A module is first-party only when its top-level
  name resolves to a package directory inside the enclosing project (see
  `_first_party.py`); stdlib, site-packages and anything unresolvable are
  third-party. Unresolvable defaults to third-party on purpose: a missed
  finding is a smaller failure than an unfixable one.
* **relative imports** (`from . import _helper`, `from ._impl import Thing`) —
  a relative import cannot leave its own package by construction, and a
  package's own internals are its own business. This matches PLC2701.
* **same-top-level-package absolute imports** — `from app.models.registry
  import _wire_fallback_metric` written from inside the `app` package is the
  spelled-out form of the bullet above. Written from `app/tests/` — which is
  not inside the package — it fires, because a white-box test reaching into a
  module's internals from outside is the finding, not the exemption.
* **dunder names** (`__version__`, `__all__`) — conventional module metadata,
  not private internals.
* **a private TOP-LEVEL package name** — `from _infra.fakes import FakeStt`,
  a first-party shared test-support package. The underscore there is the
  package's own name, not a hidden corner of somebody else's module: there is no
  public spelling to switch to and no surface to widen. PLC2701 flags these
  (14 hits in one of that repo's packages alone) with no available fix. Private
  *sub*module segments still fire.
* `_`-prefixed *aliases* (`import json as _json`) — the alias is local shorthand
  and the imported name is public.

## Implementation notes

### `_private_segment`

The top-level name is deliberately excluded. `pkg._internals` is a module
`pkg` chose not to publish and could publish; a top-level package that is
simply *named* `_infra` — a first-party shared test-support package — has no
other spelling and no wider surface to widen, so flagging its import asks
for an edit that does not exist.
