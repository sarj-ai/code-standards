# Dead and duplicate code

Audit removable and duplicated code using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Unreferenced modules, exports, branches, dependencies, feature flags, and compatibility paths.
- Near-duplicate business logic likely to drift when one copy changes.
- Wrappers, adapters, memoization, derived state, and helper layers that add no policy, safety, or meaningful reuse.
- Hand-rolled behavior already provided clearly by the standard library or an established dependency.

Account for reflection, plugin registration, framework conventions, public APIs, and generated entry points before declaring code dead. Prefer deletion over a new abstraction unless duplication is stable and meaningful.

For TypeScript, inspect the resolved ESLint configuration before adding a rule.
The shared preset inherits typescript-eslint's strict and stylistic typed rules,
including redundant/duplicate type constituents, unnecessary generic parameters,
type arguments, constraints, conversions, templates, and boolean comparisons.
`no-unnecessary-type-assertion` also checks literal const assertions. An enclosing
`as const` already preserves direct object values and tuple elements; retain that
outer assertion and remove repeated member assertions. The native
`no-restricted-syntax` selectors cover that direct nesting, which the typed rule
misses. Calls, returns, computed keys, spreads, and intervening `satisfies`
expressions remain outside those selectors because inference boundaries differ.

`no-extra-label` starts as a warning, alongside the inherited
`no-useless-assignment` warning. Keep necessary outer-loop labels and preserve
side effects when removing overwritten values.
Do not blanket-enable every disabled rule: `no-inferrable-types` conflicts with
`isolatedDeclarations`; the pinned parameter-property assignment rule reports
necessary restorations and writes after parameter increments; and
`no-unneeded-ternary` can introduce a boolean conversion rejected by the typed
conversion rule. Reevaluate those exclusions against concrete regressions when
upstream changes.

The opt-in `knip` capability reports native production-mode unused-file evidence
for an application declared with `application = true` under `[knip]` in the existing
manifest. Its initial adapter accepts one private
application with `entry` and `project` arrays containing production patterns
suffixed with `!` in `knip.json` or `.knip.json`. Keep aliases, framework routes, generated
entry points, and dynamic registrations complete in the native configuration;
Knip owns resolution. Workspaces, dynamic configuration, unresolved imports, or
configuration diagnostics are inconclusive. Public library APIs, declaration
files, generated files, and test support are outside this application finding.
Enabling the capability does not create or change consumer entry-point settings,
and a warning does not prove that deleting a file preserves the application.
