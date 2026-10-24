# Readability and naming

Apply [protocol](../skills/audit-protocol/SKILL.md).

Require demonstrated ambiguity or comprehension cost. Replace stale prose/hidden
invariants with executable parity where useful; preserve snapshots, public
annotations and evaluation count.

Simplifications must preserve SQL NULL/anti-existence, HCL nested replacement/null
clearing and decoded YAML command boundaries.

For Terraform, prefer one typed input or a named branch over selection chains;
preserve lazy evaluation. Derive flags/counts from owned state when they cannot
vary independently. SARJ209 owns validation that repeats type or nullability;
retain domain constraints, cross-field checks and otherwise necessary null guards.

Terraform module boundaries follow resource ownership and lifecycle. A shared
filename prefix is a search hint. Nested directories are not loaded automatically;
extracting resources into a called child module changes their state addresses.
Prefer an existing cohesive owner over a new wrapper; keep composition flat and pass typed
inputs instead of making children reach into sibling internals. Keep root input
names and defaults compatible with existing tfvars, and configure providers at
the composition root. Root bootstrap resources and cross-module wiring may stay
there when no child owns their lifecycle.

Before extracting resources, trace callers, outputs, instance keys, dependency
edges, provider aliases and `path.module`/template paths. Preserve permissions,
conditions, replacement behavior and deletion protection. Commit declarative
`moved` blocks for every changed state address and retain migration history.
Compare native before/after plans through the supported stack pipeline: an
organization-only change must not create, replace, update or destroy resources.
Mock-provider tests check graph and address migration; live provider behavior and
effective access need provider-backed evidence. Avoid arbitrary line-count limits,
prefix-based folder mandates and resource-free-root rules as lint blockers;
require a demonstrated ownership or comprehension problem before adding layers.

React neither awaits event handlers nor sends their async failures to error
boundaries. Trace rejection ownership; existing feedback needs no extra wrapper,
and promise-returning props may transfer ownership.
