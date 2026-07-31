/**
 * @fileoverview The single source of truth for "does this name read as a Zod
 * schema?". Shared by `zod-naming-convention` (which ENFORCES a convention) and
 * `require-zod-form-validation` (which RECOGNISES a schema receiver), because
 * the two disagreeing is a bug: a plugin that accepts `SubmitFormSchema` as a
 * validator in one rule must not call the same symbol non-conforming in another.
 *
 * Two conventions are recognised, and both are correct:
 *   - PREFIX (`ZUser`) — lets a schema and its inferred type share a base name
 *     (`type User = z.infer<typeof ZUser>`) without collision.
 *   - SUFFIX (`userSchema`, `SubmitFormDataSchema`) — the dominant convention in
 *     the wider Zod ecosystem and in most existing codebases.
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
