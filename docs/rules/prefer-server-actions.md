# `prefer-server-actions` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-server-actions.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Prefer Next.js Server Actions over /api/* mutations.

Flags mutations against internal `/api/*` URLs (POST/PUT/DELETE/PATCH) via
`fetch`, axios-style helpers, or direct axios/request calls. GET requests
and external URLs are ignored. Tests, scripts, and Next.js route handlers
are skipped because Server Actions don't apply there.

The member branch (`api.post('/api/x')`) intentionally skips calls that pass
a function argument (e.g. `router.post('/api/x', handler)`) so Express-style
route *definitions* aren't mistaken for client-side mutations.

NON-REACT FRAMEWORKS ARE SKIPPED. "Use a Server Action" is not advice an
Angular, Vue, Svelte or Solid module can act on — the feature does not exist
outside React/Next. Corpus sweep (2220 files across zod / TanStack Query /
react-router / swr / zustand, 2026-07): 9 hits, of which 3 were Angular
services —
`query/examples/angular/auto-refetching/src/app/services/tasks.service.ts:38`
(`lastValueFrom(this.#http.post('/api/tasks', task))`, an `HttpClient`
injection) — and 4 were jscodeshift input/output fixtures under
`__testfixtures__/`, which are text a codemod transforms rather than code that
runs. Both are now skipped; the 2 genuine React hits still fire.

References:
  - https://nextjs.org/docs/app/building-your-application/data-fetching/server-actions-and-mutations

## Evidence relocated from the source

### `getScope`

Import sources that prove the module belongs to a framework where Server
Actions do not exist. See @fileoverview for the corpus evidence.

