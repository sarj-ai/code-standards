# `require-fetch-timeout` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/require-fetch-timeout.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Require an abort `signal` on global `fetch()` calls. A fetch
without a timeout hangs forever when the upstream stalls, tying up the
request (or worker) with it. Pass `AbortSignal.timeout(ms)` — or a signal
from an `AbortController` — in the init object.

Scope is deliberately narrow to keep false positives near zero:
  - Only calls that resolve to the *global* `fetch` are checked: bare
    `fetch(...)` (unless a local binding — import, parameter, variable —
    shadows it) plus the explicit global spellings `globalThis.fetch(...)`,
    `window.fetch(...)`, and `self.fetch(...)`. Other member calls like
    Cloudflare Workers service bindings (`env.MY_SERVICE.fetch(...)`) or
    custom clients (`client.fetch(...)`) are skipped.
  - A call is flagged only when the init argument is absent, or is an
    object literal that provably lacks `signal` (no spread, no `signal`
    key). Anything dynamic (an identifier, a call result, a spread) is
    assumed to carry a signal.
  - Single-argument calls whose argument is not a string/template literal
    are skipped: `fetch(request)` / `fetch(c.req.raw.clone())` are proxy
    passthroughs (Workers idiom) where the inbound Request governs the
    lifetime and attaching a fresh signal is impossible or wrong.
  - Test files and one-off tooling (`scripts/**`, `*.mjs`) are skipped —
    dev scripts die with the terminal, so hang-hardening is noise there.
  - Codemod fixtures under `__testfixtures__/` are skipped. Corpus sweep
    (2220 files across zod / TanStack Query / react-router / swr / zustand,
    2026-07): 8 of 79 hits came from a single jscodeshift input/output pair,
    `query/packages/query-codemods/src/v5/remove-overloads/__testfixtures__/bug-reports.input.tsx`
    and its `.output.tsx` twin. Those files are the BEFORE and AFTER text a
    codemod test diffs; editing them to add a signal would break the test they
    exist to drive, and the code never runs. The shared `isTestFile` predicate
    knows `fixtures/` but not jscodeshift's `__testfixtures__/` spelling.

Wrapper modules that centralize timeout handling can be exempted via the
`allowIn` glob-pattern option.
