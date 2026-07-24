# @sarj/eslint-plugin

Custom ESLint rules for hypermodern TypeScript / React / Next.js projects.

```bash
pnpm add -D @sarj/eslint-plugin
```

```js
// eslint.config.mjs
import sarj from "@sarj/eslint-plugin";
export default [...sarj.configs.recommended];
```

Each rule's source under `lib/rules/` carries its own `meta.docs.description` + `meta.messages` — read the file for full rationale.

Presets: `recommended` (warn-first), `strict` (every rule at error), `style-guide` (formatting/naming subset).

## Options

### Declare your logger (`loggerNames` / `logFunctions`)

Four rules decide whether a call writes to a log sink: `no-log-only-catch`,
`no-sentinel-return-on-catch`, `no-secret-in-log`. Out of the box they recognise
a log method on a logger *receiver* (`console.error`, `logger.warn`,
`this.logger.info`). A structured logger is usually a free *function* taking a
meta object, which has no receiver — declare it once and all of them see it:

```js
const logging = { logFunctions: ["logEvent"], loggerNames: ["obs"] };

rules: {
  "@sarj/no-log-only-catch": ["error", logging],
  "@sarj/no-sentinel-return-on-catch": ["error", logging],
  "@sarj/no-secret-in-log": ["error", logging],
}
```

- `logFunctions` — free functions (or methods) that log: `logEvent("x", { err })`.
- `loggerNames` — extra logger *receiver* names, added to the built-in set.

This suppresses "swallows the error without logging it" on a correctly-logged
degraded return, and — importantly — makes `no-secret-in-log` inspect those
calls, which it could not do before: `logEvent("slack.auth", { botToken })` was
previously never examined.

### `zod-naming-convention`: `convention`

`"either"` (default) accepts both the `Z`-prefix (`ZUser`) and the `Schema`
suffix (`userSchema`) — the two conventions `require-zod-form-validation`
already recognises. Set `"prefix"` or `"suffix"` to pin one:

```js
"@sarj/zod-naming-convention": ["error", { convention: "suffix" }]
```

### `prefer-string-literal-union`: `ignoreFields`

Field names whose value set is owned by a vendor and genuinely open (a Slack
`event.subtype`, a Resend `bounceType`). Narrowing to a union you don't control
would be wrong, not better:

```js
"@sarj/prefer-string-literal-union": ["warn", { ignoreFields: ["subtype", "bounceType"] }]
```

### `no-enum`: `ignoreFiles`

Glob patterns whose files opt out (generated code already opts out by default).
