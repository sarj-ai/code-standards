import { describe, expect, it } from "vitest";

import { rules } from "../src/index.js";
import {
  createRule,
  documentationWarnings,
  publicDocumentation,
  type RuleDocumentation,
} from "../src/rules/_docs.js";

const SUMMARY = "Report the representative construct.";

function documentedRule(documentation: RuleDocumentation) {
  return createRule<readonly [], "message">({
    name: "representative-rule",
    documentation,
    meta: {
      type: "problem",
      docs: { description: SUMMARY },
      schema: [],
      messages: { message: "Representative diagnostic." },
    },
    defaultOptions: [],
    create: () => ({}),
  });
}

function documentation(examples: RuleDocumentation["examples"]): RuleDocumentation {
  return {
    summary: SUMMARY,
    rationale: "The construct creates a deterministic maintenance problem.",
    remediation: "Use the smaller supported construct.",
    category: "maintainability",
    examples,
  };
}

describe("source-owned TypeScript rule metadata", () => {
  it("attaches a deeply frozen, non-enumerable native spec", () => {
    const rule = documentedRule(documentation([]));

    expect(rule.documentation).toMatchObject({
      engine: "eslint",
      key: "eslint:representative-rule",
      ruleId: "representative-rule",
      messageIds: ["message"],
      optionsSchema: null,
    });
    expect(Object.isFrozen(rule.documentation)).toBe(true);
    expect(Object.isFrozen(rule.documentation?.examples)).toBe(true);
    expect(Object.keys(rule)).not.toContain("documentation");
  });

  it("keeps examples private unless publication is explicit", () => {
    const rule = documentedRule(documentation([
      {
        id: "private-case",
        title: "A test-only edge case",
        outcome: "match",
        files: [{ path: "src/input.ts", source: "const value = 1;" }],
        focusPath: "src/input.ts",
        expectedCount: 1,
      },
    ]));

    expect(rule.documentation?.examples).toHaveLength(1);
    expect(rule.documentation?.publicExamples).toEqual([]);
  });

  it("publishes only allowlisted fields from explicitly public examples", () => {
    const rule = documentedRule(documentation([
      {
        id: "private-case",
        title: "A test-only edge case",
        outcome: "match",
        files: [{ path: "src/private.ts", source: "const secret = 1;" }],
        focusPath: "src/private.ts",
        expectedCount: 1,
      },
      {
        id: "rejected-case",
        title: "A reviewed rejection",
        outcome: "match",
        files: [{ path: "src/input.ts", source: "const value = 1;" }],
        focusPath: "src/input.ts",
        expectedCount: 1,
        public: true,
      },
      {
        id: "accepted-case",
        title: "A reviewed acceptance",
        outcome: "no-match",
        files: [{ path: "src/input.ts", source: "const value = 2;" }],
        focusPath: "src/input.ts",
        expectedCount: 0,
        public: true,
      },
    ]));

    const [published] = publicDocumentation({ "representative-rule": rule });
    const serialized = JSON.stringify(published);

    expect(published?.examples.map((example) => example.id)).toEqual([
      "rejected-case",
      "accepted-case",
    ]);
    expect(serialized).not.toContain("private-case");
    expect(serialized).not.toContain("secret");
    expect(serialized).not.toContain('"public"');
    expect(published?.examples.every((example) => example.fixedFiles !== undefined)).toBe(true);
  });

  it("supports safe relative multi-file projects", () => {
    const rule = documentedRule(documentation([
      {
        id: "multi-file-case",
        title: "A project-level relationship",
        outcome: "match",
        files: [
          { path: "src/input.ts", source: "export const value = 1;" },
          { path: "src/consumer.ts", source: 'import { value } from "./input.js";' },
        ],
        focusPath: "src/consumer.ts",
        expectedCount: 1,
      },
    ]));

    expect(rule.documentation?.examples[0]?.files).toHaveLength(2);
  });

  it.each(["../secret.ts", "/tmp/input.ts", "C:\\tmp\\input.ts"])(
    "rejects unsafe example path %s",
    (path) => {
      expect(() => documentedRule(documentation([
        {
          id: "unsafe-path",
          title: "An unsafe virtual path",
          outcome: "match",
          files: [{ path, source: "const value = 1;" }],
          focusPath: path,
          expectedCount: 1,
        },
      ]))).toThrow("safe relative path");
    },
  );

  it("requires both outcomes before any examples become public", () => {
    expect(() => documentedRule(documentation([
      {
        id: "only-positive",
        title: "An incomplete public example set",
        outcome: "match",
        files: [{ path: "src/input.ts", source: "const value = 1;" }],
        focusPath: "src/input.ts",
        expectedCount: 1,
        public: true,
      },
    ]))).toThrow("matching and non-matching");
  });
});

describe("warning-first rollout", () => {
  it("requires source-owned documentation for every published rule", () => {
    expect(documentationWarnings(rules)).toEqual([]);
  });
});
