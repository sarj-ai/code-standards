# `no-client-side-data-fetching` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-client-side-data-fetching.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow data fetching inside `useEffect` / `useLayoutEffect`.

Anti-pattern:

  useEffect(() => { fetch('/data').then(setData); }, []);

Causes a client-side waterfall (render → effect → fetch → re-render),
forfeits server-side caching, and produces layout shift. In Next.js App
Router, prefer:
  - a React Server Component that fetches at render time, or
  - a Server Action invoked from a form / onClick handler, or
  - client-side caching libraries like SWR or React Query.

Detection covers:
  - `fetch(...)` (default + when explicit `method: "GET"`)
  - `axios.<method>(...)` for actual HTTP verbs only:
    get / post / put / delete / patch / request / head / options
    (i.e. NOT `axios.create` / `axios.defaults`)
  - `ky.<method>(...)` / `superagent.<method>(...)` (same verbs)
  - bare `axios(...)` / `ky(...)` calls (when treated as a GET)

Analytics / telemetry endpoints whose URL has a whole path segment of
`track` / `log` / `ping` / `event` / ... are intentionally exempt because
they aren't render-blocking data fetches. (Matched per-segment, so
`/api/login`, `/blog`, `/api/events`, `/catalog`, `/api/shipping` are NOT
exempt.)

References:
  - https://nextjs.org/docs/app/building-your-application/data-fetching
  - https://react.dev/reference/react/useEffect#fetching-data-with-effects
