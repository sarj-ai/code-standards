/**
 * Shared defaults exempt path categories that are safe for every consumer.
 * Ambiguous directory names require explicit, recorded per-rule gates.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "../../src/rules/_paths.js";

const RULES_DIR = fileURLToPath(new URL("../../src/rules", import.meta.url));

describe("isTestFile — shared default", () => {
  it.each([
    ["dot test basename", "src/user.test.ts", true],
    ["dot spec basename", "src/user.spec.tsx", true],
    ["dash test basename", "src/user-test.ts", true],
    ["underscore test basename", "src/user_test.ts", true],
    ["E2E basename", "src/user.e2e.ts", true],
    ["integration basename", "src/user.integration.ts", true],
    ["tests directory", "src/tests/user.ts", true],
    ["test directory", "src/test/user.ts", true],
    ["double-underscore tests", "src/__tests__/user.ts", true],
    ["mock directory", "src/__mocks__/user.ts", true],
    ["fixtures directory", "src/fixtures/user.ts", true],
    ["double-underscore fixtures", "src/__fixtures__/user.ts", true],
    ["test fixtures", "src/__testfixtures__/user.ts", true],
    ["top-level E2E", "e2e/user.ts", true],
    ["top-level integration", "integration/user.ts", true],
    ["production source", "src/user.ts", false],
    ["testing name fragment", "src/testing/user.ts", false],
    ["test suffix fragment", "src/latest/user.ts", false],
    ["singular fixture without gate", "src/fixture/seed.ts", false],
  ])("recognises %s: %s -> %s", (_name, path, expected) => {
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
    ["TSX story basename", "src/Button.stories.tsx", true],
    ["TS story basename", "src/Button.stories.ts", true],
    ["story tree without gate", "src/stories/Button.tsx", false],
    ["suffixed story tree without gate", "src/stories_vue3-vite-default-ts/Button.ts", false],
    ["production component", "src/Button.tsx", false],
  ])("recognises %s: %s -> %s", (_name, path, expected) => {
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
    ["generated directory", "src/generated/api.ts", true],
    ["double-underscore generated directory", "src/__generated__/api.ts", true],
    ["root double-underscore generated directory", "__generated__/api.ts", true],
    ["Windows root generated directory", "generated\\api.ts", true],
    ["case-insensitive generated directory", "src/Generated/api.ts", true],
    ["OpenAPI output directory", "src/openapi-gen/api.ts", true],
    ["GraphQL types directory", "src/graphql/types/api.ts", true],
    ["gen suffix", "src/api.gen.ts", true],
    ["generated suffix", "src/api.generated.ts", true],
    ["declaration suffix", "src/api.d.ts", true],
    ["hand-written types suffix", "src/api.types.ts", false],
    ["vendor directory", "src/vendor/mqtt.ts", true],
    ["vendored directory", "src/vendored/mqtt.ts", true],
    ["dash third-party directory", "src/third-party/mqtt.ts", true],
    ["underscore third-party directory", "src/third_party/mqtt.ts", true],
    ["production source", "src/api.ts", false],
    ["first-party external tree without gate", "src/services/external/client.ts", false],
  ])("recognises %s: %s -> %s", (_name, path, expected) => {
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

  it("recognises Windows script directories", () => {
    expect(isScriptFile(String.raw`C:\repo\scripts\seed.ts`)).toBe(true);
  });
});

/** A gate is a per-rule exemption, so every caller must be recorded here. */
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
    ["generated by", "// Generated by protoc\n"],
    ["generated with", "// Generated with openapi-generator\n"],
    ["generated GraphQL types", "// Generated GraphQL types\n"],
    ["do not modify this file", "// Do not modify this file manually\n"],
    ["do not change this file", "// Do not change this file directly\n"],
  ])("recognises the %s banner", (_name, banner) => {
    expect(isGeneratedFile(HAND_WRITTEN, banner)).toBe(true);
  });

  // Bare generated/change phrases can describe values or behavior in ordinary source.
  it.each([
    ["identifier", "export type AutoGeneratedFields = 'createdAt' | 'updatedAt';\n"],
    ["prose adjective", "/** The verify token is auto-generated at integration creation. */\n"],
    ["behavioural warning", "// Note: do not change to 'threads', it will cause the failure\n"],
    ["angular router", " * Do not change this unless you are the Angular router.\n"],
    ["rule description", "description: 'Disallow type assertions that do not change the type',\n"],
    ["derivation prose", "/** If not provided, one is generated from the store ID. */\n"],
    ["AI attribution", "// Generated by Claude\n"],
    ["AI attribution variant", "// Generated by ChatGPT\n"],
    ["AI attribution with", "// Generated with ChatGPT\n"],
    ["AI generated directive", "// @generated with Claude\n"],
    ["OpenAI attribution", "// Generated by OpenAI\n"],
    ["Copilot attribution", "// Generated by GitHub Copilot\n"],
    ["GPT attribution", "// Generated by GPT-4o\n"],
    ["AI attribution using", "// Generated using ChatGPT\n// DO NOT EDIT\n"],
    ["AI attribution compact GPT", "// Generated via GPT4\n// DO NOT EDIT\n"],
    ["AI plus do-not-edit", "// Generated by Claude\n// DO NOT EDIT\n"],
    ["ordinary edit guidance", "// Do not edit cache entries in place.\n"],
    ["runtime generation prose", "// This token is generated by the API at runtime.\n"],
    ["server report prose", "// The report was generated by the server.\n"],
    ["template fixture", "const fixture = `\n// Generated by protoc\n`;\n"],
    ["marker after code", "const value = 1;\n// Generated by protoc\n"],
  ])("does not treat %s as a generator banner", (_name, text) => {
    expect(isGeneratedFile(HAND_WRITTEN, text)).toBe(false);
  });

  it("only reads the head of the file", () => {
    expect(isGeneratedFile(HAND_WRITTEN, "x\n".repeat(2000) + "@generated\n")).toBe(false);
  });

  it("lets deterministic codegen evidence win over separate AI-authored documentation", () => {
    const source = "// Code generated by protoc. DO NOT EDIT.\n// Documentation authored with Claude.\n";
    expect(isGeneratedFile(HAND_WRITTEN, source)).toBe(true);
  });

  it("allows a shebang before a deterministic generator banner", () => {
    expect(isGeneratedFile(HAND_WRITTEN, "#!/usr/bin/env node\n// Code generated by protoc. DO NOT EDIT.\n")).toBe(true);
  });
});
it("does not treat an ordinary user-facing string as a generated-file banner", () => {
  expect(isGeneratedFile("src/editor.ts", "export const warning = 'Do not edit manually';\n")).toBe(false);
});
