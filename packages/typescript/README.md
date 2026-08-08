# @sarj/eslint-plugin

Deterministic ESLint rules and presets for TypeScript, React, and modern Node.js
applications. The plugin complements ESLint's core and TypeScript ESLint rules;
it does not duplicate them.

## Use

Sarj repositories should let `sarj-standards setup` install the tested peer set
and generate the integration. Direct ESLint consumers can install the package
and select a preset:

```js
import sarj from "@sarj/eslint-plugin";

export default [
  sarj.configs.strict,
];

// For staged adoption:
// export default [sarj.configs.recommended];
```

Available presets are `recommended` for staged adoption and `strict` for the
full general policy. Application-only rules are exported separately because
they depend on an explicit runtime and library policy.

Use `sarj-standards show peers` for the tested ESLint and parser dependency set.
Do not combine independent `latest` versions and assume they are compatible.

## Rules and suppressions

Every rule is registered in `src/index.ts`; its source under `src/rules/` and
paired test under `tests/rules/` are the authoritative specification. Run
`sarj-standards show rules` for the current machine-readable catalog.

Prefer the smallest line-scoped `eslint-disable-next-line @sarj/rule-name`
suppression and explain why the exceptional code is intentional. Unknown or
retired rule names are configuration errors.

New rules must prove that upstream ESLint and TypeScript ESLint cannot express
the policy and must pass focused tests plus the repository corpus evaluation
described in the root contribution guide.

Renamed rules fail closed. Replace `jsdoc-restates-signature` with
`no-restated-jsdoc`, `no-async-callback-in-waitfor` with
`no-async-callback-in-wait-for`, `strict-test-assertions` with
`prefer-whole-object-assertion`, and `trailing-value-narration` with
`no-trailing-value-narration`.
