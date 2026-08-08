/**
 * @fileoverview _tailwind — shared className-position helpers, so the Tailwind rules visit string literals and template quasis alike.
 *
 */

export const tailwindBase = (token: string): string =>
  token.replace(/^(?:[a-z0-9-]+:)+/i, "").replace(/^!/, "");

/** Split a className string into its non-empty class tokens. */
export const classTokens = (value: string): readonly string[] =>
  value.split(/\s+/).filter(Boolean);
