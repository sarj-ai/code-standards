# `no-unnecessary-use-client` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-unnecessary-use-client.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag `'use client'` files with no hooks or event handlers.

If a file is marked `'use client'` but contains no hook calls
(`useState`/`useEffect`/etc.), no JSX event handlers (`onClick`,
`onChange`, etc.), no browser globals, no client-only imports, and no
other client-side indicators (classes, re-exports), the directive is
likely unnecessary and the file could be a React Server Component —
improving cold-start, bundle size, and SEO.

False-positive watch: components that only use client-side context
(e.g. theme providers) without hooks or events still need `'use client'`.

TWO MORE CLIENT INDICATORS, ADDED AFTER A CORPUS SWEEP (2220 files across
zod / TanStack Query / react-router / swr / zustand, 2026-07 — 12 hits, all
false positives):

  1. **Rendering a component imported from a THIRD-PARTY package.** React
     documents `'use client'` at the top of a wrapper as the way to mark a
     dependency's components as client components, and this rule cannot see
     into `node_modules` to know whether the dependency needs it.
     `CLIENT_ONLY_PACKAGES_REGEX` was a hand-maintained approximation of the
     same idea and is necessarily incomplete — it did not know about
     `fumadocs-ui` (`zod/packages/docs/components/tabs.tsx:1`, which renders
     `<Primitive.Tabs>`), about `swr` itself
     (`swr/examples/suspense-global/global-swr-config.tsx:1`, a `<SWRConfig>`
     provider), or about `next/image` and `lucide-react`
     (`zod/packages/docs/components/themed-image.tsx:1`,
     `.../heading.tsx:1`). A component imported by a RELATIVE path lives in
     the same repo, is linted by this same rule, and still fires — so the
     narrowing costs nothing where the rule can actually see the answer.
  2. **Aliasing an import into a public export** —
     `import * as Devtools from './ReactQueryDevtools';
     export const ReactQueryDevtools = … Devtools.ReactQueryDevtools`
     (`query/packages/react-query-devtools/src/index.ts:1`, and `production.ts`).
     That is a re-export written the long way, and `export … from` was already
     treated as an indicator; the two spellings now agree.

ONE MORE INDICATOR FROM A FIRST-PARTY REVIEW REGRESSION:

  3. **Importing `next/dynamic`.** In the App Router, `dynamic(…, { ssr: false })`
     is a hard BUILD ERROR inside a Server Component — Next.js rejects it with
     "`ssr: false` is not allowed with `next/dynamic` in Server Components".
     A lazy-wrapper module therefore has NO legal form without the directive,
     so the rule was demanding something the framework forbids and the only
     available response was a disable comment. These wrappers also look
     maximally "unnecessary" to the old predicate: one `dynamic()` call, no
     hooks, no handlers, no browser globals.
     Two first-party lazy-wrapper modules are the shape: one defers the
     recharts bundle off a server-rendered dashboard page, the other defers
     the Lexical bundle off two server-rendered admin routes.

     HONEST SCOPE: both of those files also happen to be covered by indicator
     2, since each EXPORTS a const whose initializer reads the imported
     `dynamic`. Indicator 3 is therefore defense-in-depth, not the thing that
     currently silences them: it is what covers the same wrapper when the lazy
     component is module-internal (`const Editor = dynamic(…); export function
     Page() { return <Editor />; }`), where indicator 2 does not reach and the
     framework constraint is identical. The test suite pins exactly that shape.

All FOUR of that repo's `no-unnecessary-use-client` disables are consequently
stale rather than live false positives — including a selector-wrapper module
and its twin, which pass a hook adapter as a function prop and are already
exempt via indicator 2. The valid-case suite pins all of them so a future narrowing of
indicator 2 cannot silently reintroduce the reports.

References:
  - https://nextjs.org/docs/app/building-your-application/rendering/client-components
  - https://react.dev/reference/rsc/use-client (wrapping third-party components)
  - https://nextjs.org/docs/app/api-reference/functions/dynamic (`ssr: false`)
