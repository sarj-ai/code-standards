/**
 * @fileoverview _zod — the single source of truth for "does this name read as a Zod schema?".
 *
 */

/** The `Z<Capital>` prefix convention: `ZUser`, `ZSubmitForm`. */
export const ZOD_PREFIX_RE = /^Z[A-Z]/;

/** The `XxxSchema` suffix convention: `userSchema`, `SubmitFormDataSchema`. */
export const ZOD_SUFFIX_RE = /Schema$/;

/** Either accepted convention. */
export const ZOD_SCHEMA_NAME_RE = /Schema$|^Z[A-Z]/;

export function isZodModule(source: string): boolean {
  return /(^|[/@-])zod([/-]|$)/.test(source);
}
