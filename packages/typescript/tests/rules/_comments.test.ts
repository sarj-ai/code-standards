// vitest: shared-module-graph













import { describe, expect, it } from "vitest";

import {
  contentTokens,
  hasExternalReference,
  isProtected,
  normalizeToken,
  restates,
  restatesStatementHead,
  splitIdentifier,
  stem,
} from "../../src/rules/_comments.js";






const STATEMENT = "const userProfileCache = buildUserProfileCacheFromSession(session);";

describe("restatesStatementHead: the narration length budget", () => {


  it.each([
    ["Build the user profile cache session", 6, true],
    ["Build the user profile cache from session", 7, false],
  ] as const)("classifies %s at the narration budget", (comment, words, expected) => {
    expect(comment.split(" ")).toHaveLength(words);
    expect(restatesStatementHead(comment, STATEMENT)).toBe(expected);
  });







  it("needs at least one content word after the opening verb", () => {
    expect(restatesStatementHead("Build", STATEMENT)).toBe(false);
    expect(restatesStatementHead("Build the", STATEMENT)).toBe(false);
  });

  it("does not fire on a comment that opens with something other than a verb", () => {
    expect(restatesStatementHead("Session user profile cache", STATEMENT)).toBe(false);
  });

  it("does not fire when a content word is absent from the statement head", () => {
    expect(restatesStatementHead("Build the user profile tenant", STATEMENT)).toBe(false);
  });

  it("has nothing to compare against when there is no statement below", () => {
    expect(restatesStatementHead("Build the user profile cache", null)).toBe(false);
  });
});

describe("normalizeToken: the plural fold", () => {

  it("folds a trailing plural on a word longer than the minimum", () => {
    expect(normalizeToken("Users")).toBe("user");
  });



  it("leaves a word at the minimum length alone", () => {
    expect(normalizeToken("bits")).toBe("bits");
  });


  it("never folds a doubled s", () => {
    expect(normalizeToken("CLASS")).toBe("class");
  });
});

describe("stem: the inflection fold is symmetric", () => {



  it.each([
    ["create", "creat"],
    ["creates", "creat"],
    ["creating", "creat"],
  ])("stems %s to %s", (word, expected) => {
    expect(stem(word)).toBe(expected);
  });

  it("rebuilds the y that -ied / -ies replaced", () => {
    expect(stem("retried")).toBe("retry");
    expect(stem("retries")).toBe("retry");
  });



  it.each([
    { expected: "is", name: "two-letter word", word: "is" },
    { expected: "ads", name: "three-letter plural", word: "ads" },
    { expected: "tie", name: "short -ies word", word: "ties" },
  ])("leaves $name stable", ({ expected, word }) => {
    expect(stem(word)).toBe(expected);
  });
});

describe("splitIdentifier / contentTokens", () => {
  it.each([
    ["userProfileCache", ["user", "profile", "cache"]],
    ["HTTPServerError", ["http", "server", "error"]],
    ["snake_case_name", ["snake", "case", "name"]],
    ["SCREAMING_CASE", ["screaming", "case"]],
    ["v2Client", ["v", "2", "client"]],
  ])("splits %s", (identifier, parts) => {
    expect(splitIdentifier(identifier)).toEqual(parts);
  });

  it("drops stopwords but keeps the words that identify the code", () => {
    expect(contentTokens("Return the userId for this session")).toEqual([
      "return",
      "user",
      "id",
      "session",
    ]);
  });
});

describe("restates: exact or stemmed, never prefix", () => {
  it("matches through the stem fold", () => {
    expect(restates(["create", "user"], new Set(["creates", "user"]))).toBe(true);
  });




  it("does not match a token that is merely a prefix of a code token", () => {
    expect(restates(["service"], new Set(["locationservice"]))).toBe(false);
  });
});

describe("isProtected: the exemption floor", () => {
  it.each([
    ["S1 external reference", "see PROJ-249 for the rollout plan"],
    ["S2 version pin", "safe as of v2.4 of the driver"],
    ["S3 number with a unit", "keep the batch under 500ms"],
    ["S4 causal connective", "sorted first because the index is partial"],
    ["S5 negation of the obvious", "must not be memoized"],
    ["S6 upstream quirk", "workaround for the upstream double-encode"],
    ["S7 invariant", "this must run before any writer takes the lock"],
    ["S8 security reasoning", "compared in constant-time to avoid a timing attack"],
    ["S9 vendor with ascribed behaviour", "Stripe silently truncates metadata values"],
  ])("protects %s", (_signal, body) => {
    expect(isProtected(body)).toBe(true);
  });



  it("does not protect a bare restatement", () => {
    expect(isProtected("increment the counter")).toBe(false);
  });

  it("does not treat the exemption floor as a classifier for useful comments", () => {
    expect(isProtected("the cache key includes the tenant slug")).toBe(false);
  });



  it("does not protect a vendor name with no behaviour ascribed to it", () => {
    expect(isProtected("Create the prompt for Gemini")).toBe(false);
  });
});

describe("hasExternalReference: signal S1 on its own", () => {
  it.each([
    "tracked in PROJ-249",
    "see https://example.com/spec",
    "per RFC 6265",
    "specified by PEP 654",
    "mitigates CVE-2025-1234",
    "regression from #1234",
    "owned by @standards.example.com",
  ])("finds a reference in %s", (body) => {
    expect(hasExternalReference(body)).toBe(true);
  });



  it.each(["encoded as UTF-8", "hashed with SHA-256", "wrapped in AES-256"])(
    "does not read %s as a ticket key",
    (body) => {
      expect(hasExternalReference(body)).toBe(false);
    },
  );

  it("does not treat an unowned admission as a reference", () => {
    expect(hasExternalReference("hacky, fix later")).toBe(false);
  });
});
