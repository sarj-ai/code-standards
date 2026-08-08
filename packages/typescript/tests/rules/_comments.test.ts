/**
 * `_comments.ts` is consumed by five rules and had no tests of its own.
 *
 * A shared helper's behaviour is only ever *incidentally* observed through its
 * consumers, and incidental observation does not pin constants: `no-comment-cruft`,
 * `no-restated-comment`, `jsdoc-restates-signature`, `trailing-value-narration`
 * and `no-type-member-comment-wall` between them left `NARRATION_MAX_WORDS`
 * survivable at both 3 and 60 — a comment-length budget that could be cut in half
 * or multiplied tenfold with the whole suite green. Each numeric threshold below
 * is therefore pinned from BOTH directions: one case that fails if the number
 * goes down, one that fails if it goes up.
 */

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

/**
 * One statement for the whole narration group, so the only variable between the
 * cases is the comment's word count. Its head — everything before the first
 * `(` — supplies the tokens `user`, `profile`, `cache` and `session`.
 */
const STATEMENT = "const userProfileCache = buildUserProfileCacheFromSession(session);";

describe("restatesStatementHead: the narration length budget", () => {
  // Kills NARRATION_MAX_WORDS 6 -> anything smaller (6 -> 3 was a live
  // survivor): a six-word narration is still narration.
  it.each([
    ["Build the user profile cache session", 6, true],
    ["Build the user profile cache from session", 7, false],
  ] as const)("classifies %s at the narration budget", (comment, words, expected) => {
    expect(comment.split(" ")).toHaveLength(words);
    expect(restatesStatementHead(comment, STATEMENT)).toBe(expected);
  });

  // Kills NARRATION_MAX_WORDS 6 -> anything larger (6 -> 60 was a live
  // survivor). Past the budget a comment is prose, and prose is not judged by
  // whether its words appear in the line below — that is the whole reason the
  // budget exists.
  // Kills NARRATION_MIN_CONTENT 1 -> 0: a bare verb says nothing about WHICH
  // code it describes, so there is nothing to have restated.
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
  // Kills TOKEN_PLURAL_MIN 4 -> larger: five letters is long enough to fold.
  it("folds a trailing plural on a word longer than the minimum", () => {
    expect(normalizeToken("Users")).toBe("user");
  });

  // Kills TOKEN_PLURAL_MIN 4 -> smaller: at the minimum the word is left alone,
  // because short words ending in `s` are usually not plurals.
  it("leaves a word at the minimum length alone", () => {
    expect(normalizeToken("bits")).toBe("bits");
  });

  // `ss` is not a plural marker; folding it would turn `class` into `clas`.
  it("never folds a doubled s", () => {
    expect(normalizeToken("CLASS")).toBe("class");
  });
});

describe("stem: the inflection fold is symmetric", () => {
  // The trailing-`e` strip is what makes `create` / `creates` / `creating`
  // collapse to one stem; without it the -ing and -s forms reduce to `creat`
  // while the base stays `create`, and a restatement reads as novel.
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

  // The length floor stops the fold eating short words whole: three characters
  // must survive the suffix, and three must survive the trailing-`e` strip.
  it("leaves a word too short to survive the suffix alone", () => {
    expect(stem("is")).toBe("is");
    expect(stem("ads")).toBe("ads");
    expect(stem("ties")).toBe("tie");
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

  // The prefix match is what sank PR #98 at a ~60% false-positive rate:
  // `service` matched `locationService` and every comment looked like a
  // restatement. One token outside the code is enough to keep the comment.
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

  // The floor has to have a floor: a comment that restates the code carries
  // none of the nine signals, or the rules it gates would never fire at all.
  it("does not protect a bare restatement", () => {
    expect(isProtected("increment the counter")).toBe(false);
  });

  it("does not treat the exemption floor as a classifier for useful comments", () => {
    expect(isProtected("the cache key includes the tenant slug")).toBe(false);
  });

  // A vendor name as the mere OBJECT of a narration verb is not ascribed
  // behaviour. That distinction is what holds the leak rate near 1%.
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

  // The acronym exclusions exist because `UTF-8` and `SHA-256` have a ticket
  // key's exact shape. Without them every encoding note reads as owned work.
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
