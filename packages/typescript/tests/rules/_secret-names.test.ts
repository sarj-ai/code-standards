/**
 * `_secret-names.ts` decides what counts as a credential for every secret-aware
 * rule, and had no tests of its own.
 *
 * The word sets ARE the behaviour, and a set consumed through rules is only
 * incidentally observed: `CATEGORY_WORDS` could be emptied outright with the
 * whole suite green, which would make `isAuthSecretName` claim that
 * `tokenType` — a discriminator, not a credential — is a timing-attack surface.
 * Every set below is pinned by a case that fails if a member is removed and a
 * case that fails if the set is emptied or widened.
 */

import { describe, expect, it } from "vitest";

import {
  hasApiKey,
  isAuthSecretName,
  isSecretName,
  leadingWord,
  tokenize,
} from "../../src/rules/_secret-names.js";

describe("tokenize / leadingWord", () => {
  // Each whole snake/kebab SEGMENT is emitted before its camel parts. That is
  // what rescues a pathological `ToKeN`, which camel-splitting shreds into
  // `to`/`ke`/`n` — and it is why `tokens[0]` is not the first word.
  it.each([
    ["apiKey", ["apikey", "api", "key"]],
    ["API_KEY", ["api", "api", "key", "key"]],
    ["api-key", ["api", "api", "key", "key"]],
    ["isTokenStrategy", ["istokenstrategy", "is", "token", "strategy"]],
    ["ToKeN", ["token", "to", "ke", "n"]],
  ])("splits %s", (identifier, tokens) => {
    expect(tokenize(identifier)).toEqual(tokens);
  });

  // The leading word is matched as a WORD, never as a character prefix — which
  // is what keeps `hash_secret` (`hash` != `has`) and `issuer_token`
  // (`issuer` != `is`) out of the flag class.
  it.each([
    ["isToken", "is"],
    ["hasSecret", "has"],
    ["hash_secret", "hash"],
    ["issuer_token", "issuer"],
  ])("reads the leading word of %s as %s", (identifier, word) => {
    expect(leadingWord(identifier)).toBe(word);
  });
});

describe("isSecretName", () => {
  it.each(["apiKey", "authToken", "SESSION_SECRET", "client_secret"])("flags %s", (identifier) => {
    expect(isSecretName(identifier, new Set())).toBe(true);
  });

  // A leading boolean predicate marks a FLAG, not the credential: `isToken`
  // answers "does a token exist", and its value leaks nothing.
  it.each(["isToken", "hasSecret", "has_api_key"])("does not flag the boolean %s", (identifier) => {
    expect(isSecretName(identifier, new Set())).toBe(false);
  });

  // The upper bound on that guard: word, not prefix.
  it.each(["hash_secret", "issuer_token", "canary_token"])(
    "still flags %s, whose leading word merely starts like a predicate",
    (identifier) => {
      expect(isSecretName(identifier, new Set())).toBe(true);
    },
  );

  it("honours the caller's innocuous trailing words", () => {
    expect(isSecretName("tokenCount", new Set(["count"]))).toBe(false);
    expect(isSecretName("tokenCount", new Set())).toBe(true);
  });
});

describe("hasApiKey: `key` counts only IMMEDIATELY after `api`", () => {
  // Adjacency is the whole predicate: `key` on its own is `sortKey` /
  // `keyboard`, and `api` on its own is `apiUrl`.
  it.each([
    [["api", "key"], true],
    [["public", "api", "key"], true],
    [["api", "secret", "key"], false],
    [["access", "key"], false],
    [["sort", "key"], false],
    [["key", "board"], false],
  ])("reads %s as %s", (tokens, expected) => {
    expect(hasApiKey(tokens)).toBe(expected);
  });
});

describe("isAuthSecretName narrows isSecretName to timing-attack surfaces", () => {
  it.each(["apiKey", "authToken", "sessionSecret"])("flags %s", (identifier) => {
    expect(isAuthSecretName(identifier)).toBe(true);
  });

  // Kills CATEGORY_WORDS being emptied, and each of its members being dropped.
  // A discriminator naming WHICH KIND of credential is in play is not itself a
  // credential — comparing it in variable time recovers nothing an attacker can
  // use. The names below put the category word in the MIDDLE on purpose: as the
  // trailing token it is already excluded by `DESCRIPTOR_WORDS` and by the
  // shared innocuous set, so a trailing-token fixture proves nothing about
  // `CATEGORY_WORDS` and leaves it deletable.
  it.each([
    ["type", "TOKEN_TYPE_SYSTEM"],
    ["types", "secret_types_registry"],
    ["kind", "secretKindRegistry"],
    ["kinds", "credential_kinds_map"],
  ])("does not flag %s in the middle of %s", (_word, identifier) => {
    expect(isSecretName(identifier)).toBe(true);
    expect(isAuthSecretName(identifier)).toBe(false);
  });

  // The upper bound on that exclusion: the category word has to be a token of
  // its own, and a name that merely contains those letters still counts.
  it("still flags a credential whose name merely contains those letters", () => {
    expect(isAuthSecretName("typedApiKey")).toBe(true);
  });

  // Anything `isSecretName` rejects is rejected here too, by construction.
  it("never widens past isSecretName", () => {
    expect(isSecretName("isToken", new Set())).toBe(false);
    expect(isAuthSecretName("isToken")).toBe(false);
  });
});
