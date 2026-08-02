/** Contract tests for the secret-name vocabulary shared by security rules. */

import { describe, expect, it } from "vitest";

import {
  hasApiKey,
  isAuthSecretName,
  isSecretName,
  leadingWord,
  tokenize,
} from "../../src/rules/_secret-names.js";

describe("tokenize / leadingWord", () => {
  it.each([
    ["apiKey", ["apikey", "api", "key"]],
    ["API_KEY", ["api", "api", "key", "key"]],
    ["api-key", ["api", "api", "key", "key"]],
    ["isTokenStrategy", ["istokenstrategy", "is", "token", "strategy"]],
    ["ToKeN", ["token", "to", "ke", "n"]],
  ])("splits %s", (identifier, tokens) => {
    expect(tokenize(identifier)).toEqual(tokens);
  });

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

  it.each(["isToken", "hasSecret", "has_api_key"])("does not flag the boolean %s", (identifier) => {
    expect(isSecretName(identifier, new Set())).toBe(false);
  });

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

  it.each([
    ["type", "TOKEN_TYPE_SYSTEM"],
    ["types", "secret_types_registry"],
    ["kind", "secretKindRegistry"],
    ["kinds", "credential_kinds_map"],
  ])("does not flag %s in the middle of %s", (_word, identifier) => {
    expect(isSecretName(identifier)).toBe(true);
    expect(isAuthSecretName(identifier)).toBe(false);
  });

  it("still flags a credential whose name merely contains those letters", () => {
    expect(isAuthSecretName("typedApiKey")).toBe(true);
  });

  it("never widens past isSecretName", () => {
    expect(isSecretName("isToken", new Set())).toBe(false);
    expect(isAuthSecretName("isToken")).toBe(false);
  });
});
