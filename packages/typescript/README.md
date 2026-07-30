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

46 rules. Each rule's source under `src/rules/` carries its own `@fileoverview` rationale plus `meta.docs.description` + `meta.messages` — read the file for the full reasoning, including the false positives it deliberately does not fire on.

Presets: `recommended` (warn-first), `strict` (every rule at error), `style-guide` (formatting/naming subset).

## New in 2.14.0 — `no-tautological-expect`

The TS half of SARJ057. An `expect(...)` whose operands are all literals has
already decided its outcome before the test runs — `expect(true).toBe(true)`
passes if you delete the module under test.

Python has caught the assertion-*free* test since 0.15.0 (`SARJ043
zero-assertion-test`) and had no TypeScript counterpart, which is exactly how
`expect(true).toBe(true); // placeholder` survived in an internal suite named for
the behaviour it was supposed to check: the file *has* an assertion, so nothing
was looking at it.

| Rule | What it catches | Preset |
|---|---|---|
| `no-tautological-expect` | `expect(<literal>).toBe/toEqual/toStrictEqual(<textually identical literal>)`, and `expect(<literal>).toBeDefined()/toBeTruthy()/toBeNull()/…` — a zero-argument matcher on a literal receiver. | warn / error |

**The narrowness is the rule.** The obvious generalisation — "flag a comparison
of a thing with itself" — measures ~95% false positives:
`expect(hash([o])).toEqual(hash([o]))` is a *determinism* test,
`expect(memo(x)).toBe(memo(x))` a *memoization* test, `expect(a).toEqual(a)` on a
value with custom equality a *reflexivity* test. All three can genuinely fail. So
an identifier, member-expression or call operand is never enough: both sides must
be literals, and textually identical ones. A modified chain (`.not`, `.resolves`,
`.rejects`), a spread, an interpolated template literal, and two *different*
literals are all left alone.

Measured before shipping: **3 hits across 5,819 `.ts`/`.tsx` files** (1,003 of
them test files, where the rule is active) — six internal repos plus `got`,
`hono`, `swr` and `trpc`. 3 true positives, **0 false positives**; every hit is
an abandoned placeholder.

## New in 2.13.0 — the anti-comment-verbosity family

From a 37,918-comment, nine-repo measurement study. All three are
deletion-class, so each was validated against zod / swr / zustand / TanStack
Query as well as the maintained repos. Read the `@fileoverview` in each rule for
the hit counts and the false-positive class every guard was built from.

| Rule | What it catches | Preset |
|---|---|---|
| `no-restated-comment` | A single-line comment whose every content word already appears on the statement below it. Defers to `no-comment-cruft` for the verb-led shape, so a comment is never reported twice. | warn / error |
| `jsdoc-restates-signature` | A JSDoc block whose description and `@param`/`@returns` only re-spell the signature. Offers a delete SUGGESTION, never an auto-`--fix`. | warn / error |
| `trailing-value-narration` | `staleTime: 5 * 60 * 1000, // 5 minutes` — the unit belongs in the name, where it cannot drift. | warn / error |

## New in 2.9.0

Both distilled from two years of PR-review comments across ~1,065 PRs.

| Rule | What it catches | Preset |
|---|---|---|
| `no-zod-native-enum` | `z.nativeEnum(...)` and `z.enum(SomeTsEnum)` — the schema-layer back door around `no-enum`. Autofixes an inline string-literal object to `z.enum([...])`. | warn / error |
| `prefer-zod-enum` | `z.union([z.literal("a"), z.literal("b")])` — autofixes closed string choices to the shorter, equivalent `z.enum(["a", "b"])`. | warn / error |
| `prefer-module-level-constant` | A literal-only `const` collection (array, object, `Set`, `Map`, `Object.freeze`) or non-global regex declared inside a function body, never mutated and never escaping — hoist it to module scope. Options: `minElements` (default 3), `checkRegex`, `ignoreTestFiles`. | warn / error |
| `prefer-non-nullable-collection` | An array type explicitly combined with `null`/`undefined`, creating two equivalent empty states. | warn / error |

## Options

### Declare your logger (`loggerNames` / `logFunctions`)

Three rules decide whether a call writes to a log sink: `no-log-only-catch`,
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

## Configurable rules

Most rules take no options. These three do, because they encode a codebase's
architecture rather than a language fact — the defaults describe one convention
and every repo gets to name its own.

| Rule | Option | Default | Effect |
|---|---|---|---|
| `no-raw-fetch-outside-clients` | `allow` | client/test path patterns | Files exempt from the "no bare `fetch`" rule |
| `no-dynamic-sql` | `methods` | `["prepare", "exec", "query"]` | Statement-taking methods to inspect |
| `no-storage-in-stateless-modules` | `modules` | `[]` (rule off) | Directories declared stateless |
| `no-storage-in-stateless-modules` | `methods` | `["prepare", "put", "getWithMetadata"]` | Storage methods to flag |

Every option value is a **regular-expression source matched against the absolute
filename**, not a glob — so it can express both path separators. Supplying an
option **replaces** the default rather than extending it.

`no-storage-in-stateless-modules` is a **no-op until `modules` is set**. The
method names alone (`put`, `prepare`) carry no type information, so the rule is
only meaningful once it is pointed at the directories a team has actually
declared stateless.

```js
// eslint.config.mjs
import sarj from "@sarj/eslint-plugin";

export default [
  ...sarj.configs.strict,
  {
    rules: {
      // This repo keeps its HTTP layer in `lib/api/`, not `clients/`.
      "@sarj/no-raw-fetch-outside-clients": [
        "error",
        { allow: ["[\\\\/]lib[\\\\/]api[\\\\/]", "\\.test\\.", "\\.spec\\."] },
      ],
      // Declare which modules must stay stateless.
      "@sarj/no-storage-in-stateless-modules": [
        "error",
        { modules: ["[\\\\/]engineer-digest[\\\\/]"] },
      ],
    },
  },
];
```

Tiering: `no-dynamic-sql` is in both presets (an injection guard with a low
false-positive rate, relevant to any repo touching SQL). The two architectural
rules are **`strict`-only**, since they need per-repo configuration to say
anything useful.

## Ported from `sarj_python_lint`

Several rules are ports of the Python linter's SARJ rules, retuned for TypeScript. The false-positive tuning documented in the Python docstrings is ported with them — that tuning is the valuable part.

| TypeScript rule | Python | What it prevents |
| --- | --- | --- |
| `prefer-constant-time-secret-compare` | SARJ011 | Byte-by-byte secret recovery through the timing of a short-circuiting `===` on a token / signature / HMAC. On Workers the fix is `crypto.subtle.timingSafeEqual` over equal-length digests. |
| `no-secret-in-log` | SARJ012 | Credentials persisted into log sinks. |
| `store-insert-requires-on-conflict` | SARJ018 | Duplicate rows — or unique-constraint failures that re-trigger the handler — when a cron re-runs or a queue message is redelivered. |
| `no-select-star` | SARJ021 | An implicit row contract that changes silently when a column is added or reordered. |
| `no-offset-pagination` | SARJ025 | O(N)-per-page scans, and rows repeated or skipped when the offset window shifts under concurrent inserts. |
| `no-repeated-string-literal` | SARJ024 | Copies of a structured literal (SQL, column lists, prompt templates) drifting apart when only one is edited. |
| `no-positional-tuple-return` | SARJ026 | Call sites re-inventing — and disagreeing on — the field names of a positional tuple return. |
| `no-sleep-in-test-body` | SARJ031 | Tests that assert on wall-clock time and flake under CI load. |
| `no-fat-try-blocks` | SARJ007 | Over-broad `catch` handlers swallowing unrelated failures. |
| `no-cors-wildcard-with-credentials` | SARJ008 | Credentialed cross-origin requests from any origin. |
| `single-public-export` | SARJ022 | Modules with no single obvious entry point. |
| `prefer-string-literal-union` | SARJ006 | An open `string` where a closed set is intended. |

Shared helpers live in `src/rules/_*.ts` (`_secret_names.ts`, `_sql.ts`, `_logging.ts`, `_paths.ts`, `_tailwind.ts`) so related rules cannot diverge on what counts as a secret, a SQL statement, a logging call, or a test file.

Deliberately **not** ported: `no-unreachable-after-terminal` (SARJ010) is already covered by `allowUnreachableCode: false` in `@sarj/tsconfig` plus ESLint core `no-unreachable`; `no-aggregation-in-store-query` (SARJ020) assumes a Postgres-OLTP / columnar-mirror split that D1 does not have; `no-query-with-many-joins` (SARJ019), `stepdown` (SARJ023), `prefer-class-row`, `prefer-struct-over-namedtuple`, `prefer-timedelta-for-durations`, and `no-fstring-in-log` have no TypeScript defect class or target API; `prefer-str-enum` is covered by `prefer-string-literal-union` + `no-enum`.
