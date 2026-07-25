/**
 * @fileoverview Shared predicate for deciding whether an identifier names secret
 * material. TS port of Python's `_secret_names.py`, used by `no-secret-in-log`
 * (SARJ012) and `prefer-constant-time-secret-compare` (SARJ011) so the two rules
 * never diverge on what counts as a secret.
 *
 * A naive implementation matches a secret word as a bare *substring*, which
 * misfires on a large false-positive class observed in real audits:
 *
 * - LLM usage counters that merely embed `token`: `tokenCount`, `promptTokens`,
 *   `completionTokens`, `totalTokens`, `maxTokens`, `tokenize`, `tokenizer`,
 *   `tokenBudget`.
 * - Row-id / handle names: `apiKeyId`, `*KeyId` — the id of a key row, not the
 *   key material.
 * - Boolean feature / presence / state flags: `passwordEnabled`, `tokenPresent`,
 *   `passwordSet`, `passwordConfigured` — a boolean answering "is it there / was
 *   it set", not the credential itself. A `type` discriminator is the same:
 *   `tokenType` is `"Bearer"`, `credentialType` is a class name.
 * - Innocent words embedding a secret word: `secretary` (embeds `secret`),
 *   `keyboardEvent` (embeds `key`).
 *
 * Two rules fix this:
 *
 * 1. Match a secret word only as a WHOLE token (after snake_case / camelCase
 *    splitting), never a substring. This alone clears `tokenize`, `tokenizer`,
 *    `secretary`, and every *pluralized* `tokens` counter (plural `tokens` is not
 *    the singular secret word `token`).
 * 2. Disqualify an identifier whose TRAILING token is a counter / row-id / flag
 *    marker (`count`, `budget`, `id`, `enabled`, ...) even when a secret word is
 *    also present — this clears `tokenCount`, `apiKeyId`, `passwordEnabled`,
 *    while still catching a credential that merely leads with such a word
 *    (`validToken`, `presentToken` are secrets, not flags).
 *
 * `isAuthSecretName` narrows further for SARJ011: a *timing-attack* surface is
 * only an authenticator whose bytes gate access, so category discriminators,
 * boolean flags, and integrity-only content hashes are stripped there while
 * `no-secret-in-log` keeps its broader reach.
 */

export const SECRET_WORDS: ReadonlySet<string> = new Set([
  "token",
  "secret",
  "password",
  "passwd",
  "jwt",
  "secrets",
  "passwords",
  "credential",
  "credentials",
  "authorization",
  "signature",
  "hmac",
  "digest",
  "hash",
  "apikey",
  "bearer",
]);

/**
 * Tokens that mark a counter, row-id, feature flag, or boolean presence/state
 * marker. As the TRAILING token they mean the identifier is metadata *about* a
 * secret, not the secret itself, so it is not a leak / timing surface even when a
 * secret word is also present: `tokenPresent`, `passwordSet`, and
 * `passwordConfigured` are booleans, not credentials. Leading such a word does
 * not disqualify — `validToken` / `presentToken` are credentials.
 */
export const INNOCUOUS_WORDS: ReadonlySet<string> = new Set([
  "count",
  "counts",
  "budget",
  "limit",
  "limits",
  "id",
  "ids",
  "enabled",
  "disabled",
  "flag",
  "flags",
  "present",
  "set",
  "unset",
  "configured",
  "missing",
  "required",
  "valid",
  "invalid",
  "exists",
  "type",
  "types",
]);

/**
 * Trailing token that makes the identifier metadata *about* a secret (its
 * category / handle / label), not the credential: `tokenType`, `tokenName`,
 * `sessionId`, `credentialKind`. `type`/`id` are already dropped by the shared
 * innocuous set; `name`/`kind` are added here because logging them can still
 * matter (SARJ012) but they are never a timing surface.
 */
const DESCRIPTOR_WORDS: ReadonlySet<string> = new Set([
  "type",
  "types",
  "name",
  "names",
  "id",
  "ids",
  "kind",
  "kinds",
]);

/**
 * A `type`/`kind` token anywhere marks an enum/category discriminator, not a
 * credential: `TOKEN_TYPE_SYSTEM`, `credentialType`, `grantKind`.
 */
const CATEGORY_WORDS: ReadonlySet<string> = new Set(["type", "types", "kind", "kinds"]);

/**
 * A leading boolean-predicate token marks a flag, not the credential itself:
 * `isToken`, `hasSecret`, `isTokenStrategy`.
 */
const FLAG_PREFIXES: ReadonlySet<string> = new Set([
  "is",
  "has",
  "was",
  "are",
  "can",
  "should",
]);

/**
 * Words that make an identifier a secret *only* via an integrity/content hash
 * (`contentHash`, `metadataHash`, `rowHash`) rather than an authenticator. A name
 * that ALSO carries one of these keeps firing (`passwordHash`, `tokenHash`,
 * `computedHmac`, `signature`): those gate access, a plain digest of content does
 * not.
 */
const AUTH_WORDS: ReadonlySet<string> = new Set([
  "token",
  "secret",
  "secrets",
  "password",
  "passwd",
  "passwords",
  "jwt",
  "credential",
  "credentials",
  "authorization",
  "signature",
  "hmac",
  "apikey",
  "bearer",
]);

/**
 * camelCase / PascalCase / ALLCAPS / digit-run splitter, applied to each
 * snake/kebab segment. `APIKey` -> ["API", "Key"], `authToken` -> ["auth", "Token"].
 */
const CAMEL_RE = /[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+/g;
const SEGMENT_RE = /[^A-Za-z0-9]+/;

/**
 * Ordered lowercase tokens from snake_case + camelCase decomposition. Also
 * yields each whole snake/kebab segment lowercased, so a pathological mixed-case
 * single word like `ToKeN` (which camel-splitting shreds into `to`/`ke`/`n`)
 * still surfaces its intended `token` form.
 */
export function tokenize(identifier: string): string[] {
  const tokens: string[] = [];
  for (const segment of identifier.split(SEGMENT_RE)) {
    if (!segment) {
      continue;
    }
    tokens.push(segment.toLowerCase());
    for (const part of segment.match(CAMEL_RE) ?? []) {
      tokens.push(part.toLowerCase());
    }
  }
  return tokens;
}

/**
 * The first *word* of an identifier, from camelCase splitting.
 *
 * `tokenize` deliberately emits each whole snake/kebab segment before its camel
 * parts, so `tokens[0]` for the camelCase `hasSecret` is the useless `hassecret`
 * rather than `has`. Python's rule reads `tokens[0]` directly and gets away with
 * it because Python identifiers are snake_case; TypeScript's are not, so the
 * leading-word check has to split the first segment explicitly or every
 * `isToken` / `hasSecret` flag would be mistaken for a credential.
 */
export function leadingWord(identifier: string): string | undefined {
  for (const segment of identifier.split(SEGMENT_RE)) {
    if (segment) {
      return (segment.match(CAMEL_RE) ?? [segment])[0]?.toLowerCase();
    }
  }
  return undefined;
}

/** True if an `api` token is immediately followed by a `key` token (`api_key`). */
export function hasApiKey(tokens: readonly string[]): boolean {
  for (let i = 0; i + 1 < tokens.length; i++) {
    if (tokens[i] === "api" && tokens[i + 1] === "key") {
      return true;
    }
  }
  return false;
}

/**
 * True if `identifier` names raw secret material (a credential, not metadata).
 * `innocuous` defaults to the shared metadata set; callers that need a wider
 * exemption list (e.g. `no-secret-in-log`) pass their own superset.
 */
export function isSecretName(
  identifier: string,
  innocuous: ReadonlySet<string> = INNOCUOUS_WORDS,
): boolean {
  const tokens = tokenize(identifier);
  const last = tokens.at(-1);
  if (last !== undefined && innocuous.has(last)) {
    return false;
  }
  if (tokens.some((tok) => SECRET_WORDS.has(tok))) {
    return true;
  }
  return hasApiKey(tokens);
}

/**
 * True if `identifier` names an *authenticator* — an access-gating secret whose
 * bytes an attacker could recover by timing a byte-wise comparison.
 *
 * Narrows `isSecretName` for SARJ011: strips category/handle descriptors,
 * `type`/`kind` discriminators, boolean flags, and integrity-only hashes, none of
 * which are a timing-attack surface even though logging them may still matter.
 */
export function isAuthSecretName(identifier: string): boolean {
  if (!isSecretName(identifier)) {
    return false;
  }
  const tokens = tokenize(identifier);
  const first = leadingWord(identifier);
  if (first !== undefined && FLAG_PREFIXES.has(first)) {
    return false;
  }
  const last = tokens.at(-1);
  if (last !== undefined && DESCRIPTOR_WORDS.has(last)) {
    return false;
  }
  if (tokens.some((tok) => CATEGORY_WORDS.has(tok))) {
    return false;
  }
  if (tokens.some((tok) => AUTH_WORDS.has(tok))) {
    return true;
  }
  return hasApiKey(tokens);
}
