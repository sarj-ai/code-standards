/**
 * @fileoverview zod — shared Zod schema recognition and explicit field policy facts.
 *
 */

/** Legacy schema-name recognition used by migration-tolerant consumers; not the canonical naming policy. */
export const ZOD_PREFIX_RE = /^Z[A-Z]/;

/** Legacy schema-name recognition used where identifying schemas matters more than enforcing their spelling. */
export const ZOD_SUFFIX_RE = /Schema$/;

/** Broad legacy recognition. `require-pascal-case-zod-schema-name` owns canonical declaration names. */
export const ZOD_SCHEMA_NAME_RE = /Schema$|^Z[A-Z]/;

/** Explicit numeric field policy shared with its owning rule to avoid duplicate diagnostics. */
export const SCHEMA_INTEGER_FIELD_MINIMUMS: ReadonlyMap<string, number> = new Map([
  ["limit", 1],
  ["version", 0],
]);

export function isZodModule(source: string): boolean {
  return source === "zod" || source.startsWith("zod/");
}
