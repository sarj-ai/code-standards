/**
 * The shared file-path predicates are consulted by 20-30 rule modules each, so a
 * one-line regex change in `_paths.ts` is a scope change for every one of them.
 * #180 made exactly that change — `vendor|vendored|external|third-party`,
 * `fixtures?`, a whole `stories/` tree — on the evidence of six false positives
 * in ONE rule, and nothing measured the other twenty-nine. `no-comment-cruft`
 * went silent on `src/services/external/`, `no-raw-env` on `src/fixture/`.
 *
 * The banner arm — the half that is universal — is at the bottom of this file,
 * where it landed with the subject-scoped widening.
 *
 * Not all of it was wrong. `vendor/`, `vendored/`, `third-party/`,
 * `__fixtures__/` and `__testfixtures__/` are names that make a claim true for
 * EVERY rule, so they stay shared. `external/`, the singular `fixture/` and a
 * `stories/` tree are names that do not, so they became gates. The line is drawn
 * by what the directory name asserts, not by which PR happened to need it.
 *
 * This file is the gate that stops that recurring. Two halves:
 *
 * 1. The DEFAULT behaviour of each predicate is pinned path-by-path. Widening a
 *    default is then a diff to this table, which is the review moment: the table
 *    says, in one place, what every consumer stops seeing.
 * 2. WHICH RULE MODULES pass extra gates is pinned too. A gate exists so one
 *    rule can be exempted from one tree without touching the others; an
 *    unrecorded new caller fails here.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "../../src/rules/_paths.js";

const RULES_DIR = fileURLToPath(new URL("../../src/rules", import.meta.url));

describe("isTestFile — shared default", () => {
  it.each([
    ["src/user.test.ts", true],
    ["src/user.spec.tsx", true],
    ["src/user-test.ts", true],
    ["src/user_test.ts", true],
    ["src/user.e2e.ts", true],
    ["src/user.integration.ts", true],
    ["src/tests/user.ts", true],
    ["src/test/user.ts", true],
    ["src/__tests__/user.ts", true],
    ["src/__mocks__/user.ts", true],
    ["src/fixtures/user.ts", true],
    ["e2e/user.ts", true],
    ["integration/user.ts", true],
    ["src/user.ts", false],
    ["src/testing/user.ts", false],
    ["src/latest/user.ts", false],
    // The #180 widenings. NOT defaults: `src/fixture/seed.ts` is a production
    // database seeder in several repos, and 30 rules should not go quiet on it.
    ["src/fixture/seed.ts", false],
    // These two ARE defaults: `__fixtures__` / `__testfixtures__` are the same
    // category as the `fixtures/` that was always here, spelled the way
    // jscodeshift and Storybook spell it.
    ["src/__fixtures__/user.ts", true],
    ["src/__testfixtures__/user.ts", true],
  ])("%s -> %s", (path, expected) => {
    expect(isTestFile(path)).toBe(expected);
  });

  it.each([
    ["src/fixture/seed.ts", true],
    ["src/user.ts", false],
  ])("fixtureTree gate: %s -> %s", (path, expected) => {
    expect(isTestFile(path, ["fixtureTree"])).toBe(expected);
  });

  it("normalises Windows separators", () => {
    expect(isTestFile(String.raw`C:\repo\src\__tests__\user.ts`)).toBe(true);
  });
});

describe("isStoryFile — shared default", () => {
  it.each([
    ["src/Button.stories.tsx", true],
    ["src/Button.stories.ts", true],
    ["src/stories/Button.tsx", false],
    ["src/stories_vue3-vite-default-ts/Button.ts", false],
    ["src/Button.tsx", false],
  ])("%s -> %s", (path, expected) => {
    expect(isStoryFile(path)).toBe(expected);
  });

  it.each([
    ["src/stories/Button.tsx", true],
    ["src/stories_vue3-vite-default-ts/Button.ts", true],
    ["stories/Button.tsx", true],
    ["src/Button.tsx", false],
  ])("storyTree gate: %s -> %s", (path, expected) => {
    expect(isStoryFile(path, ["storyTree"])).toBe(expected);
  });
});

describe("isGeneratedFile — shared default (path arm)", () => {
  it.each([
    ["src/generated/api.ts", true],
    ["src/openapi-gen/api.ts", true],
    ["src/graphql/types/api.ts", true],
    ["src/api.gen.ts", true],
    ["src/api.generated.ts", true],
    ["src/api.d.ts", true],
    ["src/api.types.ts", true],
    ["src/api.ts", false],
    // The #180 widenings. `src/services/external/` is first-party
    // outbound-integration code — the place a raw `process.env` read or an
    // untimed `fetch` matters most.
    ["src/services/external/client.ts", false],
    // These four ARE defaults: a directory called `vendor` is itself the claim
    // that the code belongs to an upstream, and it is true for every rule.
    // `astro/packages/astro/src/assets/utils/vendor/image-size/types/jpg.ts` is
    // a verbatim copy of the `image-size` package.
    ["src/vendor/mqtt.ts", true],
    ["src/vendored/mqtt.ts", true],
    ["src/third-party/mqtt.ts", true],
    ["src/third_party/mqtt.ts", true],
  ])("%s -> %s", (path, expected) => {
    expect(isGeneratedFile(path)).toBe(expected);
  });

  it.each([
    ["src/services/external/client.ts", true],
    ["src/api.ts", false],
  ])("externalTree gate: %s -> %s", (path, expected) => {
    expect(isGeneratedFile(path, "", ["externalTree"])).toBe(expected);
  });
});

describe("isScriptFile", () => {
  it.each([
    ["/repo/scripts/seed.ts", true],
    ["/repo/build.mjs", true],
    ["/repo/src/a.ts", false],
  ])("%s -> %s", (path, expected) => {
    expect(isScriptFile(path)).toBe(expected);
  });
});

/**
 * A gate is a per-rule exemption. Recording who holds one is what keeps it per-rule:
 * an unrecorded caller is a scope change that never got argued.
 *
 * The evidence for the one entry here is #180 — six false positives in
 * `no-type-member-comment-wall` over 33 OSS repos / 46,861 files, all in vendored
 * typings copies, docgen'd story trees and asserted test fixtures. That reasoning is
 * about member COMMENTS being output rather than commentary. It does not transfer to
 * `no-raw-env` or `require-fetch-timeout`, which is exactly why it lives here and
 * not in the defaults.
 */
const GATE_HOLDERS: Readonly<Record<string, readonly string[]>> = {
  "no-type-member-comment-wall.ts": ["externalTree", "fixtureTree", "storyTree"],
};

describe("path gates are opt-in, per rule, and recorded", () => {
  const GATE_RE = /"(externalTree|fixtureTree|storyTree)"/g;

  const actual = new Map<string, string[]>();
  for (const entry of readdirSync(RULES_DIR)) {
    if (!entry.endsWith(".ts") || entry === "_paths.ts") {
      continue;
    }
    const found = [...readFileSync(join(RULES_DIR, entry), "utf8").matchAll(GATE_RE)].map((m) => m[1] ?? "");
    if (found.length > 0) {
      actual.set(entry, [...new Set(found)].sort());
    }
  }

  it("no rule module holds an unrecorded gate", () => {
    expect([...actual.keys()].sort()).toStrictEqual(Object.keys(GATE_HOLDERS).sort());
  });

  it("each recorded holder asks for exactly the gates recorded for it", () => {
    for (const [module, gates] of Object.entries(GATE_HOLDERS)) {
      expect(actual.get(module)).toStrictEqual([...gates].sort());
    }
  });
});

const HAND_WRITTEN = "/repo/src/thing.ts";

describe("isGeneratedFile — banner markers", () => {
  it.each([
    ["oazapfts", " * DO NOT MODIFY - This file has been generated using oazapfts.\n"],
    ["payload", "/* THIS FILE WAS GENERATED AUTOMATICALLY BY PAYLOAD. */\n"],
    ["nest graphql", " * THIS FILE WAS AUTOMATICALLY GENERATED (DO NOT MODIFY)\n"],
    ["medusa", "/** This file is auto-generated. Do not modify it manually. */\n"],
    ["twenty barrel", " * | | | Auto-generated file\n * | | | Any edits to this will be overridden\n"],
    ["storybook", " * This file has been automatically generated,\n"],
    ["legacy @generated", "// @generated by protoc\n"],
    ["legacy do-not-edit", "// DO NOT EDIT\n"],
  ])("recognises the %s banner", (_name, banner) => {
    expect(isGeneratedFile(HAND_WRITTEN, banner)).toBe(true);
  });

  // The obvious widening — bare `auto-?generated`, bare `generated from`, bare
  // `do not (modify|change)` — matched 175 extra files over 105,551, and most
  // were hand-written source using the phrase as PROSE or as an identifier.
  // Every string below is copied verbatim from one of them. Exempting these
  // files would silently disable twenty rules on ordinary code.
  it.each([
    ["identifier", "export type AutoGeneratedFields = 'createdAt' | 'updatedAt';\n"],
    ["prose adjective", "/** The verify token is auto-generated at integration creation. */\n"],
    ["behavioural warning", "// Note: do not change to 'threads', it will cause the failure\n"],
    ["angular router", " * Do not change this unless you are the Angular router.\n"],
    ["rule description", "description: 'Disallow type assertions that do not change the type',\n"],
    ["derivation prose", "/** If not provided, one is generated from the store ID. */\n"],
  ])("does not treat %s as a generator banner", (_name, text) => {
    expect(isGeneratedFile(HAND_WRITTEN, text)).toBe(false);
  });

  it("only reads the head of the file", () => {
    expect(isGeneratedFile(HAND_WRITTEN, "x\n".repeat(2000) + "@generated\n")).toBe(false);
  });
});
