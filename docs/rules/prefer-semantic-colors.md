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

KNOWN GATE DEFECT, not fixed here. The shipped strict config sets
`requireSemanticTokens: true`, which routes through `hasSemanticTokenSystem`
below. Replaying that gate over all 20,846 findings splits them 9,968 fire /
10,878 suppressed — but the split tracks naming convention and directory
depth rather than whether a design system exists. One OSS monorepo with a
complete token system is suppressed ENTIRELY, for two independent reasons:
`SEMANTIC_TOKEN_RE` only knows shadcn's vocabulary (that repo names its
tokens `content-default` / `bg-default`), and `MAX_UPWARD_DEPTH = 8` cannot
reach the package root from a 9-deep app-router path. Tailwind v4 CSS-first
setups have no `tailwind.config.*` for `DETECTION_FILES` to find at all. So
at the shipped config, whether this rule runs on a file is partly a function
of how deep it sits. Widening the vocabulary, adding v4 `@theme` detection
and raising the depth budget is a separate change with its own measurement.

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

