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
  spelled-out form of the bullet above.
* **a private module SEGMENT of our own distribution, when every imported name
  is public** — `from django.utils._os import safe_join`. The private thing is a
  module the distribution's own source imports the same way, and the symbol taken
  out of it is that module's working surface; there is no second, public spelling
  to switch to. Same-distribution is decided by the packaging manifest
  (`_first_party.same_distribution`), NOT by the top-level package directory,
  because the directory proxy excludes the distribution's own test tree — where
  the same authors write the same line under the same version number. A private
  segment reached from ANOTHER distribution still fires, which keeps
  `prefect_dbt` → `prefect._internal` and an airflow provider →
  `airflow.sdk._shared`. Import a private NAME out of that module and it fires
  too, same distribution or not. Measured below.
* **a private submodule no `.py` in the tree declares.** "Export it under a
  public name" needs a file to edit. 9 findings on the corpus, in three shapes: a
  compiled extension behind a `.pyi` stub (5 — `from pydantic_core._pydantic_core
  import ...`, the Rust binary `pydantic-core` ships, reached across the
  distribution boundary at `pydantic/pydantic/version.py:39` and from that
  package's own tests); a build-time generated module (1 —
  `prefect/src/integrations/prefect-databricks/tests/test_credentials.py:61`
  importing `prefect_databricks._version`, which the build back end writes); and a
  version-fallback import in an `except ImportError` branch naming a layout this
  checkout does not have (3 —
  `prefect/src/integrations/prefect-azure/prefect_azure/bundles/execute.py:21` and
  its aws/gcp twins). This is the module's documented under-flagging bias applied
  one level down: unresolvable resolves to third-party, so an unresolvable
  submodule resolves to not-ours.
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

## 2026-07 false-positive audit

Measured on a 19-repo corpus (seven first-party repos plus django, celery,
airflow, litellm, prefect, saleor, zulip, fastapi, pydantic, rich, httpx,
requests, deduped by content hash): **6,285 findings**. A seeded random sample of
50 read against source put the false-positive rate at **56%**. The guards take
the rule to **2,724** (-3,561, 56.7%).

**The dominant class — 28 of the 50 sampled — was the same-distribution private
segment.** The guard removes **3,552 of 6,285**, led by `litellm._types`,
`litellm._experimental`, `prefect._internal` and `airflow._shared`. **97.6% of
that population sat in test trees**, which is exactly the hole the old
same-top-level-package boundary left: the verdict used to flip on the importer's
directory alone, so `from django.utils._os import safe_join` was exempt at
`django/django/views/static.py:12` and flagged, character for character, at
`django/tests/utils_tests/test_os_utils.py:9`. Replacing the directory proxy with
the packaging manifest closes it, because a distribution's test tree resolves to
the same manifest as its source tree.

**Recall cost: 2 of 50 first-party findings** — both a workspace member's own
tests importing a public name out of a private module of that same member, which
is the guarded class exactly.

The unresolvable-submodule guard is the other 9.

### For the registry owner: this rule is now almost entirely about tests

What is left after those guards is 2,724 findings, and nearly all of one shape: a
test importing a genuinely private NAME out of the module it tests. That is in
scope by design — the fix, export it, is available to the same authors — but it
is now essentially the whole rule and **all 48 of its remaining first-party
findings**, which makes it a house-style question rather than a resolution
question. Worth flagging to whoever owns the registry: **SARJ023 skips test paths
outright while this rule fires almost exclusively inside them**, so the registry
currently holds both positions at once. This rule does not settle that
unilaterally.

## Implementation notes

### `_private_segment`

The top-level name is deliberately excluded. `pkg._internals` is a module
`pkg` chose not to publish and could publish; a top-level package that is
simply *named* `_infra` — a first-party shared test-support package — has no
other spelling and no wider surface to widen, so flagging its import asks
for an edit that does not exist.
