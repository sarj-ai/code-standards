# `prefer-semantic-colors` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-semantic-colors.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Enforce design-system semantic color tokens over raw Tailwind
palette classes and hardcoded color values.

Scoped to genuine className positions to avoid false positives on non-class
strings (Tailwind `safelist`, `toHaveClass(...)` test assertions, prose, color
maps): JSX `className`, the args of `cn()`/`clsx()`/`cva()`/`tv()`/`cx()`/
`twMerge()` (recursing into cva variant objects), and `*class*`-named
variables/object properties. Plus inline color literals on JSX `style`/`fill`/
`stroke`.

Flags:
  - raw palette classes: `text-red-500`, `bg-slate-200/50`
  - arbitrary color values: `bg-[#fff]`, `text-[rgb(...)]`, `ring-[oklch(...)]`
  - inline color literals: `style={{ color: "#111827" }}`, `fill="#000"`

Allowed: semantic tokens (`bg-primary`, `text-muted-foreground`, `bg-chart-1`),
`white`/`black` (the `bg-black/50` overlay idiom rarely has a token), `var(--…)`,
`currentColor`, and non-color arbitraries (`w-[437px]`, `grid-cols-[auto_1fr]`).

SVG drawing data is exempt on `fill`/`stroke`/`color` attributes: any value inside
a `<mask>`/`<clipPath>`/`<defs>`/`<pattern>`/`<linearGradient>`/`<radialGradient>`
(masking breaks without literal `#fff`/`#000`), the neutral literals
(`#fff`/`#000`/`transparent`/`none`/`currentColor`/`inherit`), and `*.stories.*`
files (Storybook fixtures) never fire. Real component styling — `className` and
inline `style={{ … }}` objects — still fires on hardcoded colors.

No autofix — use a semantic token, or for charts / standalone pages / 3rd-party
config add `// eslint-disable-next-line @sarj/prefer-semantic-colors -- <reason>`.

MEASURED (2026-07, 25,508 deduped TS/TSX files across 6 first-party repos and
11 OSS repos). 20,846 findings — by a wide margin the loudest rule in the
plugin. 50 were sampled at two independent seeds and read against source:
**39 true positives, 4 false, 7 arguable — an 8.0% false-positive rate**,
corroborated by a whole-population census of the same classes (8.5%). The
loudness is genuine drift, not noise: `border-neutral-200` occurs 1,167 times
and `text-neutral-500` 943.

Four guards were added, together suppressing ~1,825 findings (-8.8%) at
approximately zero recall cost; each is documented at its definition with the
class size that justified it. The 14% "arguable" residual is chart/data-viz
series colors (393 findings in chart-named paths) and success/warning states
that shadcn's default token set does not define — both are house-style calls
the fileoverview already answers with "add a disable comment and a reason",
and both were deliberately left firing.

## The `requireSemanticTokens` gate — fixed 2026-07-31

The shipped strict config sets `requireSemanticTokens: true`, which routes
through `hasSemanticTokenSystem`. The gate was previously recorded here as a
known defect attributed to naming convention AND directory depth. Re-measured,
**the binding constraint is vocabulary alone**: a `tailwind.config.*` was found
and then REJECTED unless its CONTENTS happened to use shadcn's token names, so
the option was asking "does this project use shadcn?" while documented to ask
"does this project have design tokens?".

`medusa/packages/admin/dashboard/tailwind.config.cjs` is decisive. It exists, it
is in `DETECTION_FILES`, it sits 5 directories above the components that fail
the rule — well inside `MAX_UPWARD_DEPTH = 8` — and it was rejected because
Medusa names its tokens `bg-ui-button-neutral` / `text-ui-fg-subtle`.

A `tailwind.config.*` is a token vocabulary by construction; the whole point of
the file is to name colours. Its mere existence is now sufficient, as
`components.json` already was, and `SEMANTIC_TOKEN_RE` additionally recognises
Tailwind v4's `@theme` block for CSS-first projects that have no config file at
all.

Measured over 11,143 `.tsx` files in 63 OSS repositories:

| | findings |
| --- | --- |
| ungated | 735 |
| gated, as shipped | 433 |
| gated, after this change | **609** |

`ts/medusa` goes 0 → 34 and `ts/ui` 433 → 575. The ungated number is unchanged
at 735 in both builds, which is the check that this touched only the gate.

`ts/twenty` (93 ungated) and `ts/outline` (2) remain zero under the gate, and
that is CORRECT rather than a residual defect: `find` over both repositories
returns no `tailwind.config.*`, no `components.json` and no token stylesheet
anywhere, because neither is a Tailwind project — twenty styles with Emotion,
outline with styled-components. Asking them to use a semantic token names
nothing that exists. The `MAX_UPWARD_DEPTH` half of the original diagnosis was
not reproducible on this corpus and was left alone.

## Evidence relocated from the source

### `CLASS_NAME_RE`

The step must be an actual Tailwind palette step. `\d{2,3}` also matched the
1-12 step scales that Radix-style themes use for *semantic* steps, which is
the opposite of what this rule wants: measured over 20,846 findings, 777
(3.7%) were `text-gray-11` / `text-gray-12` shapes where the step resolves to
a theme-aware CSS variable defined once per light/dark block. The rule was
also inconsistent about it — sibling steps `gray-9` and `grayA-3` in the very
same files never fired, because one digit does not match `\d{2,3}`.
Tailwind's default palette has no steps outside this set, so narrowing costs
zero recall; a literal hex aliased as `--color-gray-700` still fires.

### `"tailwind.config.ts",`

A color function wrapping a CSS variable IS a semantic token reference. The
fileoverview above has always claimed `var(--…)` is allowed; it was not, once
wrapped — and wrapping is the only way a Tailwind v3 theme ever writes it
(`hsl(var(--primary))`). 63 findings of the 20,846 measured were this shape,
every one against code already doing what the rule asks:
`unkey/web/apps/dashboard/components/logs/chart/index.tsx:306`
(`fill="hsl(var(--chart-selection))"`), plus `hsl(var(--primary))` in
documenso and `rgb(var(--content-error))` in dub. This is a straight bug
against the documented contract, so the guard costs no recall.

### `"rect",`

`isInsideSvg` walks ancestors for an `<svg>`-ish element, which misses
artwork under an aliased wrapper: `isSvgLikeElementName` matches `/svg$/i`,
so a component named `<SVGIcon>` is recognised but one named `<…Icon>` is
not, and its `<circle fill="#1877F2">` children fire —
`midday/packages/ui/src/components/icons.tsx:802` is a brand blue on a
`<circle>`. Keying off the element the attribute sits on, rather than off
its ancestry, is both narrower and robust to whatever the wrapper is called.

### `if`

Measured: 985 of the 20,846 findings (4.7%) sit in such templates — e.g.
`dub/packages/email/src/templates/domain-expired.tsx:59` (`text-neutral-800`
inside `<Tailwind>`), `cal.com/packages/emails/src/components/Info.tsx:39`,
`midday/packages/invoice/src/templates/pdf/components/paid-watermark.tsx:33`.
Recall cost is ~0 real defects: token drift cannot occur where tokens cannot
resolve.

### `cached`

The effect was order-dependent and total: linting one file reported normally,
while linting a glob containing that same file reported nothing, because some
other file poisoned the cache first. Measured across 6,774 files of real
TypeScript this rule produced ZERO findings — silently disabled everywhere
despite shipping as "error". It is the only rule in the plugin with a
module-level directory cache, which is why nothing else showed the symptom.

### `name`

Inline style objects: style={{ color: "#111827", backgroundColor: "#fff" }}

