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

/** A trailing word in this set makes the identifier metadata, not a credential. */
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

/** Descriptors excluded from timing checks but retained for logging checks. */
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

/** Category words identify credential discriminators rather than secret bytes. */
const CATEGORY_WORDS: ReadonlySet<string> = new Set(["type", "types", "kind", "kinds"]);


/** A leading predicate makes the identifier a boolean flag, not a credential. */
export const FLAG_PREFIXES: ReadonlySet<string> = new Set([
  "is",
  "has",
  "was",
  "are",
  "can",
  "should",
]);

/** Auth words distinguish access-gating hashes from integrity-only hashes. */
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

const CAMEL_RE = /[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+/g;
const SEGMENT_RE = /[^A-Za-z0-9]+/;

/** Return lowercase whole segments and their camel-case words. */
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

/** True when an identifier names raw secret material rather than metadata. */
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

/** True when an identifier names an access-gating secret. */
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
