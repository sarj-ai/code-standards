# `prefer-schema-for-api-payload` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Don't access `response.json()` / `JSON.parse()` fields without a
Zod parse first.

Pattern flagged:
  const data = await response.json();
  doSomething(data.foo);  // <-- unvalidated property access

  const body = JSON.parse(raw);
  doSomething(body.foo);  // <-- same `any` leak, different source

Encouraged:
  const data = MySchema.parse(await response.json());
  doSomething(data.foo);  // typed + validated

  const raw: unknown = JSON.parse(text);   // never flagged: nothing read off it
  const data = MySchema.parse(raw);

Heuristic:
  - Track variables initialized to `await someCall.json()` or `JSON.parse(x)`
    using ESLint's scope manager.
  - Untrack if reassigned to anything other than another raw payload source.
  - Untrack when passed to a user-defined type-guard predicate — a call whose
    callee name matches `/^is[A-Z]/`, or any call used in an `if`/`?:` test
    position (`if (guard(body)) { … body.foo … }`). Hand-written guards validate
    the payload just as a Zod `.parse()` does.
  - Flag MemberExpression reads and destructuring off tracked variables.
  - `.parse()` / `.safeParse()` chained directly on the json call are legit
    and never produce a tracked binding in the first place.

NOT FLAGGED (corpus sweep, 2220 files across zod / TanStack Query /
react-router / swr / zustand, 2026-07 — 86 raw hits, 50 of them these):
  - **Test files**, 46 hits. A test parses a payload it produced itself and
    immediately asserts on it:
    `react-router/integration/request-test.ts:120-121`
    (`loaderData = JSON.parse(await page.locator("#loader-data").innerHTML());
    expect(loaderData.method).toEqual("GET")`). Routing that through a schema
    would assert the schema instead of the subject, and the assertion IS the
    validation.
  - **Reads inside an assertion** (`expect(payload.method)`) — see
    `isInsideAssertion`. This catches hyphen-named suites such as
    `react-router/integration/request-test.ts` that no path predicate sees.
  - **JSON read off local disk**, 4 hits — see `isLocalFileRead`.

SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
hono plus six first-party repos, 2026-07): 1,013 hits, 45 read in a seeded
random sample — 22 true positives, 6 false positives, 17 arguable. Three
fixes, each measured on that corpus:

  - **The read IS the validation** — see `isValidationRead`.
  - **A `.json()` promise chain reported as a property access** — 60 / 1,013.
    The MemberExpression visitor saw `<rawPayload>.catch` and reported it,
    exempting only `.parse`/`.safeParse`; the `.catch` result was then NOT
    tracked, so the real unvalidated read one line down was MISSED and the
    report landed on the wrong node. `then`/`catch`/`finally` are now exempt
    properties AND propagate the raw-payload taint, which strictly MOVES the
    report to the true field read. Verified against
    `midday/packages/workbench/src/ui/lib/api.ts:73-74` and
    `papermark/ee/features/dataroom-freeze/components/freeze-settings.tsx:110-112`,
    both of which still fire, at the corrected line.
  - **A field read consumed solely by a validator** — see `GUARD_NAME_RE`.

DELIBERATELY NOT GUARDED: the error-envelope shape
(`if (!res.ok) { const { error } = await res.json() }`), ~12% of the volume in
three literal strings. Rendering an unvalidated `error.message` straight into
a toast is a real, if benign, defect and the house call is to keep reporting it.

References:
  - https://zod.dev/?id=parse
  - https://www.totaltypescript.com/parse-don-t-validate

## Evidence relocated from the source

### `: callee?.type === AST_NODE_TYPES.MemberExpression &&`

Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): `zod/scripts/check-versions.ts:13-14`
(`const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));
const packageJsonVersion = packageJson.version as string;` — and the very next
line is a `typeof` check), `zod/scripts/check-semver.ts:10-11`, and
`zod/packages/docs/app/llms-full.txt/route.ts:13-17`
(`JSON.parse(await fs.readFile(metaPath, "utf-8"))` over the docs' own
`meta.json`). A `response.json()` — the actual trust boundary — is unaffected.

### `callee = callee.object;`

Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): after the test-file exemption, 15 of the 45 remaining hits
were this — react-router names its Playwright suites `integration/request-test.ts`
(hyphen), which no `*.test.ts` path predicate can recognise, so the shape
check is what catches them.
`react-router/integration/request-test.ts:120-121`:
`loaderData = JSON.parse(await page.locator("#loader-data").innerHTML());
expect(loaderData.method).toEqual("GET");`

### `*/`

The validator verbs were added after the second sweep found the pattern the
`is`-only spelling missed:
`formbricks/apps/web/modules/ee/license-check/lib/license.ts:389` passes
`responseJson.data` to `validateLicenseDetails`, which at :271 is literally
`LicenseDetailsSchema.parse(data)` — the exact thing the rule is asking for,
behind a name the predicate could not see. Recall cost 0 of the 45 findings
read. The regex stays anchored and requires a capital after the verb, so
`validated(...)` and `parser(...)` are unaffected.

### `parent.type === AST_NODE_TYPES.TSTypeAssertion ||`

The rule already untracked on a guard CALL, but not on the inline narrowing
that is how most of this corpus actually validates. 4 of the 45 findings read
in the second sweep were this, e.g.
`trpc/packages/next/src/app-dir/server.ts:200-202`:
`const { cacheTag } = await req.json(); if (typeof cacheTag !== 'string')
return 400;` — a complete check on the one field the handler uses.

