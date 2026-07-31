# `_tailwind` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared helpers for the Tailwind-className rules. className values
are reachable as plain string `Literal`s (attribute values, `cn()`/`clsx()`/
`cva()`/`tv()` args, and className-holding constants) and as the static quasis of
`TemplateLiteral`s — so the rules visit both node types and run these helpers.

## Evidence relocated from the source

### `module body`

Strip Tailwind variant prefixes (`hover:`, `dark:`, `focus-visible:`, …) and a
leading `!` important marker, leaving the bare utility (`bg-red-500`). Variants are
`[a-z0-9-]+:` runs at the start; bracketed arbitrary values never start a token, so
a `:` inside `[url(http://…)]` is not mistaken for a variant separator.

