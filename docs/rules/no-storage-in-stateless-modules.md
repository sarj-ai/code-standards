# `no-storage-in-stateless-modules` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-storage-in-stateless-modules.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Keep modules that are stateless by design free of private
storage.

Some features are stateless deliberately: they derive everything they need
from reads against the systems of record (Slack, Linear, GitHub, a CRM) plus
markers in the artefacts they themselves produced. The reason is operational
— such a feature can be re-run and back-filled freely, whereas a private
table or key/value namespace immediately diverges from what a human can
actually see and audit in the system of record. Adding a store to one of
these modules silently deletes that property, and nothing else in the
toolchain notices.

WHAT IT CATCHES, inside the configured modules only
  db.prepare(sql)              // a SQL statement
  kv.put(key, value)           // a key/value write
  kv.getWithMetadata(key)      // a key/value read

OPT-IN BY DESIGN
`modules` defaults to an EMPTY list, which makes the rule a no-op. That is
deliberate: the method names alone (`put`, `prepare`) carry no type
information, so the rule is only meaningful — and only quiet enough to live
in a shared preset — when it is pointed at the specific directories a team
has declared stateless.

  "@sarj/no-storage-in-stateless-modules": ["error", {
    "modules": ["[\\\\/]engineer-digest[\\\\/]", "[\\\\/]digest[\\\\/]"]
  }]

`modules` entries are regular-expression sources matched against the absolute
filename. `methods` overrides the storage method names if a driver names
things differently.

NOT FLAGGED
  - Anything outside the configured modules.
  - `.put()` with fewer than two arguments — a one-argument `put` is more
    often a builder or queue helper than a key/value write.

If a feature genuinely cannot be expressed statelessly, that is a design
conversation, not a disable comment.
