/**
 * @fileoverview _secret-names — shared predicate for whether an identifier names secret material, rather than merely embedding a secret word.
 *
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
 * A trailing token that makes the identifier metadata *about* a secret — its
 * category, handle or label — rather than the credential: `tokenType`,
 * `tokenName`, `sessionId`, `credentialKind`. `type`/`id` are already dropped by
 * the shared innocuous set; `name`/`kind` are added here because logging them
 * can still matter (SARJ012) but they are never a timing surface.
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
 * A leading boolean-predicate word marks a flag, not the credential itself:
 * `isToken`, `hasSecret`, `has_secret`, `isTokenStrategy`. Consulted by the
 * SHARED `isSecretName`, so every consumer gets it: this is the exact mirror of
 * the trailing innocuous-word check that already lives there — a boolean
 * answering "does a secret exist?" leaks nothing whether the marker leads or
 * trails, and word ORDER should not decide whether a name counts as a
 * credential. Matched as a whole leading WORD via `leadingWord`, never as a
 * character prefix, so `hash_secret` (`hash` != `has`), `issuer_token`
 * (`issuer` != `is`) and `canary_token` (`canary` != `can`) keep firing.
 */
export const FLAG_PREFIXES: ReadonlySet<string> = new Set([
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

/** The first *word* of an identifier, from camelCase splitting. */
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
 *
 * Two symmetric metadata guards run before the secret-word scan: a TRAILING
 * innocuous word (`tokenCount`, `apiKeyId`) and a LEADING boolean-predicate word
 * (`hasSecret`, `is_token`). Both describe a name that is *about* a credential
 * rather than being one.
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
  const first = leadingWord(identifier);
  if (first !== undefined && FLAG_PREFIXES.has(first)) {
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
 */
export function isAuthSecretName(identifier: string): boolean {
  if (!isSecretName(identifier)) {
    return false;
  }
  const tokens = tokenize(identifier);
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
