# `no-raw-fetch-outside-clients` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-raw-fetch-outside-clients.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Keep outbound HTTP behind a client module.

A bare `fetch()` in a route handler, server action or component opts out of
whatever the codebase's client layer provides — retry/backoff, timeouts,
status handling, auth headers, structured log breadcrumbs. It is also the
shape that cannot be stubbed in a test without monkey-patching global
`fetch`, so the call site quietly becomes untestable.

WHAT IT CATCHES
  fetch(url)                  // bare global
  globalThis.fetch(url)       // explicit global receiver
  window.fetch(url)

NOT FLAGGED
  - Files whose path matches one of the `allow` patterns. The defaults cover
    the conventions we have seen in practice — a `clients/` directory, a
    `*-client.ts` module, an `http-client.*` wrapper, an `api/` directory or
    `api.ts` / `*-api.ts` module — plus test files and codemod fixtures.
  - A method named `fetch` on some other receiver (`cache.fetch(k)`,
    `queryClient.fetch()`): only the global is HTTP.
  - A pre-signed upload/download URL transfer (`fetch(uploadUrl, ...)`,
    `fetch(file.downloadUrl)`). Those URLs are one-off storage handoffs,
    not calls to a first-party service API that belongs behind a client
    wrapper.
  - `new Request(...)` / `axios(...)` and friends. This rule is about the
    global `fetch`, not about every HTTP library.

CONFIGURATION
`allow` is a list of regular-expression sources matched against the absolute
filename, so a repo that keeps its client layer somewhere else can say so
rather than sprinkling disable comments:

  "@sarj/no-raw-fetch-outside-clients": ["error", {
    "allow": ["[\\\\/]lib[\\\\/]api[\\\\/]", "-gateway\\\\.ts$"]
  }]

Supplying `allow` REPLACES the default CLIENT-LAYER patterns. Test files are
no longer part of that list — they are recognised unconditionally by the
shared `isTestFile` predicate — so a repo that overrides `allow` keeps its
test tree exempt without having to remember the test patterns.

CORPUS SWEEP (2220 files, zod / TanStack Query / react-router / swr /
zustand, 2026-07): 96 raw hits. The defaults missed three path conventions
that ARE the client layer, so the reports landed on the very modules the rule
wants the `fetch` to live in:
  - `api.ts` / `api/` / `*-api.ts` — 15 hits, e.g.
    `query/examples/react/star-wars/src/api.ts:7`, a module that exists solely
    to own `getFilm`/`getPerson` HTTP calls. `api` is the same convention
    family as `clients/`, just the other common spelling.
  - Hyphenated test basenames (`*-test.ts` / `*-spec.ts`) — the default list
    only knew the dotted `*.test.ts` form, so react-router's entire suite
    (which names files `single-fetch-test.ts`) was unprotected.
  - `__testfixtures__/` — 8 hits from jscodeshift fixtures such as
    `query/packages/query-codemods/src/v5/remove-overloads/__testfixtures__/bug-reports.input.tsx`,
    which are input/output text for a codemod, not code that runs.

SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
hono plus six first-party repos, 2026-07): 1,019 hits, 50 read in a seeded
random sample — 24 true positives, 21 false positives, 5 arguable. At a 42%
false-positive rate this was the loudest rule of the five audited, and the
cause was the same one the first sweep found, just further along: the reports
were landing ON the client layer, under names the `allow` list did not know.

  - **Vendor wrapper modules** — 147 findings. `*Service.ts`, `services/`,
    `connectors/` (16), `providers/` (12), `integrations/` (16),
    `notifications/<vendor>/` (29), `adapters/`, `*-fetcher.ts`. Every fetch
    in them is an absolute-URL call to ONE third-party origin — they ARE the
    module the rule wants the fetch to live in. Citable:
    `cal.com/packages/app-store/office365calendar/lib/CalendarService.ts:265`,
    `openstatus/packages/notifications/telegram/src/index.ts:81`,
    `formbricks/apps/web/lib/googleSheet/service.ts:164`.
    Recall cost: 0 of the 50 sampled true positives lived in such a path —
    every one was a `.tsx` component/page/modal or a React hook.
  - **Test-path drift** — 36 findings. The rule hand-rolled its own test-path
    list instead of using the shared `isTestFile`, so it missed `playwright/`
    (19) and the `.e2e.ts` basename. The single loudest file corpus-wide was
    `cal.com/apps/web/playwright/oauth-provider.e2e.ts` (16 findings). The
    sibling rule `require-fetch-timeout` had always used `isTestFile`; this
    was pure drift between two rules that see the same call sites.
  - **Asset / passthrough handoff** — see `isConstructedArgumentHandoff`.

DELIBERATELY NOT GUARDED: restricting the rule to component/hook files. It
would cut the residual false-positive rate from ~25% to ~4%, but costs ~80
real positives in `.ts` background jobs (e.g.
`papermark/lib/trigger/convert-pdf-direct.ts:332`).

DELIBERATELY NOT ALLOWED: a `-provider.*` BASENAME, even though the
`providers/` DIRECTORY is. In the corpus that basename is usually a React
context or modal provider calling the app's own API —
`dub/apps/web/ui/modals/modal-provider.tsx:134` is exactly the true-positive
shape — and the two vendor files that carry it are already covered by
`integrations/`.

## Evidence relocated from the source

### `"[\\\\/]notifications[\\\\/]",`

Vendor wrapper conventions: a module that exists to own one third-party
origin's HTTP. See the SECOND SWEEP note in the file header.

### `return name !== null && PRESIGNED_URL_NAME_RE.test(name);`

A single CONSTRUCTED argument and no init is an asset load or an inbound
request being forwarded — there are no headers, no auth and no body for a
client wrapper to own, and in the proxy case the inbound request governs the
call. `require-fetch-timeout` skips the same shape for the same reason.
4 of the 1,019 second-sweep findings, e.g.
`documenso/apps/remix/app/routes/_share+/share.$slug.opengraph.tsx:33`
(three OG-image font loads) and `.../app/utils/get-asset-buffer.ts:15`.

`require-fetch-timeout`'s version of this guard skips ANY lone non-string
argument. That is deliberately NOT mirrored here: 36 findings are
`fetch(url)` with the URL in a variable, and most of those are ordinary
service calls the rule exists to catch.

