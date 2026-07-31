# `no-raw-env` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-raw-env.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow direct `process.env` access. Force all env reads
through a Zod-validated env module so configuration is typed and validated
at startup.

The rule is about READING A CONFIGURATION VALUE in application code, and a
sweep of 2,186 real TypeScript files (zod / TanStack Query / react-router /
swr / zustand) produced 143 hits of which ~90% were not that. Four exemptions,
each measured against that corpus:

  - **Write target.** `process.env.X = "yes"` sets a variable for a child
    process; there is no value being read, so the validated-env module has
    nothing to say about it. 20 hits, e.g.
    react-router/packages/react-router-dev/vite/plugins/prerender.ts:250 and
    react-router/packages/react-router-dev/vite/plugin.ts:2451.
  - **Whole-environment pass-through.** `{ ...process.env, NO_COLOR: "1" }`
    forwards the inherited environment to a spawned process — again no
    configuration value is read. 9 hits, e.g.
    react-router/integration/helpers/create-fixture.ts:45.
  - **Test files** (shared `isTestFile`). A test that drives a CLI has to set
    and read the raw environment; there is no app env module in scope. 50
    hits, e.g.
    react-router/packages/create-react-router/__tests__/create-react-router-test.ts:1052.
  - **Scripts and build/test config** (shared `isScriptFile`, plus a
    `*.config.*` basename). A `vitest.config.mts` / `playwright.config.ts`
    configures the *build*, runs before the app exists, and cannot import the
    app's validated env. 47 hits, e.g. swr/test/e2e/playwright.config.ts:16
    and zod/scripts/check-versions.ts:5.

What survives is the shape the rule was written for: application code reading
a deployment setting, e.g. zod/packages/docs/loaders/stars.ts:1
(`const GITHUB_TOKEN = process.env.GITHUB_TOKEN!`).

SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
hono plus six first-party repos, 2026-07): 1,851 hits, 50 read in a seeded
random sample — 43 true positives, 2 false positives, 5 arguable. The rule is
essentially correct; the two false-positive classes both came from the rule
failing to recognise a value it can say nothing about:

  - **The validated env boundary itself, under a form the sniff missed** —
    55 / 1,851. `isValidatedEnvBoundary` demanded literally `z.object(` AND
    `.parse(`. Across boundary-named files in that corpus, 48 findings use
    `createEnv({...})` (`@t3-oss/env-nextjs`), 5 use `z.object` with
    `.safeParse`, and 2 use `.parse` with no `z.object`.
    `openstatus/apps/web/src/env.ts` alone was 24 findings: a textbook t3-env
    boundary whose `runtimeEnv:` map is REQUIRED by the library to spell
    `process.env.X` once per variable. Widening the sniff to any of the three
    markers costs no measurable recall — 23 boundary-NAMED files in the same
    corpus validate nothing at all and keep firing, correctly.
  - **Platform/runtime markers** — see `PLATFORM_MARKERS`.

## Evidence relocated from the source

### `}`

Evidence that a boundary-NAMED module actually validates: a Zod object
schema, a `createEnv({...})` call (`@t3-oss/env-nextjs` and friends, which
validate against the `server`/`client` schemas passed to them), or a
`.parse()` / `.safeParse()` anywhere in the file. Any ONE of the three is
enough — requiring `z.object` AND `.parse` together missed 55 of 1,851
findings, 48 of them the `createEnv` form.

### `parent.type === "MemberExpression" &&`

Markers the PLATFORM injects, not values the deployment configures: which
runtime the module was loaded into, whether this is a Vercel build, whether
this is CI. Same family as the already-exempt `NODE_ENV` — always present,
owned by the host, and nothing an app env schema can meaningfully validate or
default. 184 of the 1,851 second-sweep findings were this class, e.g.
`formbricks/apps/web/lib/posthog/server.ts:31`
(`process.env.NEXT_RUNTIME === "nodejs"`) and
`dub/apps/web/lib/middleware/utils/get-final-url.ts:84`
(`process.env.VERCEL === "1"`).

`VERCEL_URL` (52 findings) and `PORT` (19) are deliberately NOT here: both are
read to BUILD a base URL, which is a deployment value a repo may well want its
env schema to own. A test pins that exclusion.

