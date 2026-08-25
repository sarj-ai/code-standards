/**
 * @fileoverview _zod — the single source of truth for "does this name read as a Zod schema?".
 *
 */

/** Legacy schema-name recognition used by migration-tolerant consumers; not the canonical naming policy. */
export const ZOD_PREFIX_RE = /^Z[A-Z]/;

/** Legacy schema-name recognition used where identifying schemas matters more than enforcing their spelling. */
export const ZOD_SUFFIX_RE = /Schema$/;

/** Broad legacy recognition. `require-pascal-case-zod-schema-name` owns canonical declaration names. */
export const ZOD_SCHEMA_NAME_RE = /Schema$|^Z[A-Z]/;

export function isZodModule(source: string): boolean {
  return /(^|[/@-])zod([/-]|$)/.test(source);
}
