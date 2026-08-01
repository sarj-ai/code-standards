/**
 * @fileoverview _zod — the single source of truth for "does this name read as a Zod schema?".
 *
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_zod.md
 */

/** The `Z<Capital>` prefix convention: `ZUser`, `ZSubmitForm`. */
export const ZOD_PREFIX_RE = /^Z[A-Z]/;

/** The `XxxSchema` suffix convention: `userSchema`, `SubmitFormDataSchema`. */
export const ZOD_SUFFIX_RE = /Schema$/;

/** Either accepted convention. */
export const ZOD_SCHEMA_NAME_RE = /Schema$|^Z[A-Z]/;

/**
 * Whether an import specifier resolves to Zod — `zod`, `zod/v4`, `zod/mini`,
 * `@hono/zod-validator`-style re-exports. Shared by `prefer-zod-enum` and
 * `prefer-zod-infer` so the two cannot disagree about what "imports Zod" means.
 */
export function isZodModule(source: string): boolean {
  return /(^|[/@-])zod([/-]|$)/.test(source);
}
