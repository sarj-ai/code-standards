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

The upstream warning trial also covers `no-constructor-return`,
`no-unreachable-loop`, `no-lonely-if`,
`unicorn/no-lonely-if`, and `unicorn/prefer-block-statement-over-iife`.
ESLint's lonely-if rule collapses an `else` containing only an `if`; Unicorn's
version combines nested guards without an `else`. The IIFE rule excludes
function-specific behavior such as returns, `var`, `this`, and async execution.
Review constructor returns and one-iteration loops locally: replacing an
instance or selecting the first iterable item can be deliberate, so neither
rule automatically changes those contracts.

Do not blanket-enable every disabled rule: `no-inferrable-types` conflicts with
`isolatedDeclarations`; the pinned parameter-property assignment rule reports
necessary restorations and writes after parameter increments; and
`no-unneeded-ternary` can introduce a boolean conversion rejected by the typed
conversion rule. Reevaluate those exclusions against concrete regressions when
upstream changes.
Further exclusions have executable boundary evidence: `no-self-compare` can
compare separate getter or random results; `no-lone-blocks` misses necessary
TypeScript type scopes; `no-promise-executor-return` duplicates the typed
`strict-void-return` owner; `prefer-regex-literals` duplicates `no-invalid-regexp`
for statically invalid patterns; and Unicorn's resource-escape check flags permitted
nullish `using` bindings. Zod length/size simplifiers change observable validation
issues, and removing `.readonly()` from a Date schema changes freezing behavior.
Method-name-only rules must also preserve unrelated methods and shadowed globals.

The RegExp warning trial uses `no-missing-g-flag` for native
`matchAll`/`replaceAll` failures. Its autofix adds the flag only when the regex
is defined directly in the call argument, preserving shared regex state.

Defer `no-super-linear-backtracking` at the pinned upstream version: even
`report: "certain"` flags `/^\s*([\s\S]*)$/.exec(input)`, which accepts every
string without a rejecting suffix. Its suffix check is a heuristic, and the
rule exposes no option to exclude this false positive safely. Reevaluate after
an upstream fix.

Also defer `no-dupe-disjunctions`: even with speculative backtracking reports
disabled, it offers to remove the second alternative in `/^(?:(a)|a)\1$/`.
The original accepts both `a` and `aa` through different alternatives; the
suggested removal rejects `a`. Captures and backreferences invalidate the
native removal claim, so suggestion availability is not a safe admission filter.
Deferring these rules leaves duplicate alternatives and genuine repetition
hazards uncovered.

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
