/**
 * @fileoverview _tailwind — shared className-position helpers, so the Tailwind rules visit string literals and template quasis alike.
 *
 */

export const tailwindVariantPrefix = (token: string): string => {
  let bracketDepth = 0;
  let parenthesisDepth = 0;
  let escaped = false;
  let end = 0;
  for (let index = 0; index < token.length; index += 1) {
    const character = token[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character === "[") bracketDepth += 1;
    else if (character === "]") bracketDepth = Math.max(0, bracketDepth - 1);
    else if (character === "(") parenthesisDepth += 1;
    else if (character === ")") parenthesisDepth = Math.max(0, parenthesisDepth - 1);
    else if (character === ":" && bracketDepth === 0 && parenthesisDepth === 0) end = index + 1;
  }
  return token.slice(0, end);
};

export const tailwindBase = (token: string): string =>
  token.slice(tailwindVariantPrefix(token).length).replace(/^!/, "");

/** Split a className string into its non-empty class tokens. */
export const classTokens = (value: string): readonly string[] =>
  value.split(/\s+/).filter(Boolean);
