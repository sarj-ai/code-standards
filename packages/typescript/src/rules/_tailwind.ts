/**
 * @fileoverview _tailwind — shared className-position helpers, so the Tailwind rules visit string literals and template quasis alike.
 *
 */

/**
 * Strip Tailwind variant prefixes (`hover:`, `dark:`, `focus-visible:`, …) and a
 * leading `!` important marker, leaving the bare utility. Variants are
 * `[a-z0-9-]+:` runs at the start; a bracketed arbitrary value never starts a
 * token, so the `:` inside `[url(http://…)]` is not a variant separator.
 */
export const tailwindBase = (token: string): string =>
  token.replace(/^(?:[a-z0-9-]+:)+/i, "").replace(/^!/, "");

/** Split a className string into its non-empty class tokens. */
export const classTokens = (value: string): readonly string[] =>
  value.split(/\s+/).filter(Boolean);
