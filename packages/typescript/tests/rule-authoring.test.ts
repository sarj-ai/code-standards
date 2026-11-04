import { ESLint } from "eslint";
import { fileURLToPath } from "node:url";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";

const AUTHORING_ESLINT = new ESLint({
  cwd: fileURLToPath(new URL("..", import.meta.url)),
  overrideConfig: [tseslint.configs.disableTypeChecked],
});

const VALID_RULE = `
import { createRule } from "./_docs.js";
export default createRule<[], "problem">({
  name: "example",
  meta: { type: "problem", schema: [], messages: { problem: "Problem found." } },
  defaultOptions: [],
  create(context) {
    return { Identifier(node) { context.report({ node, messageId: "problem" }); } };
  },
});
`;

describe("upstream ESLint rule-authoring policy", () => {
  it("accepts the existing createRule wrapper", async () => {
    const [result] = await AUTHORING_ESLINT.lintText(VALID_RULE, {
      filePath: "src/rules/example.ts",
    });

    expect(
      result?.messages.filter((message) =>
        message.ruleId?.startsWith("eslint-plugin/"),
      ),
    ).toEqual([]);
  });

  it.each([
    [
      "missing schema",
      VALID_RULE.replace("schema: [], ", ""),
      "require-meta-schema",
    ],
    [
      "missing type",
      VALID_RULE.replace('type: "problem", ', ""),
      "require-meta-type",
    ],
    [
      "missing native option defaults",
      VALID_RULE.replace(
        "schema: []",
        'schema: [{ type: "object", additionalProperties: false }]',
      ),
      "require-meta-default-options",
    ],
    [
      "unknown message id",
      VALID_RULE.replace('messageId: "problem"', 'messageId: "absent"'),
      "no-missing-message-ids",
    ],
    [
      "undeclared autofix",
      VALID_RULE.replace(
        'messageId: "problem"',
        'messageId: "problem", fix(fixer) { return fixer.remove(node); }',
      ),
      "require-meta-fixable",
    ],
    [
      "undeclared suggestions",
      VALID_RULE.replace(
        'messageId: "problem"',
        'messageId: "problem", suggest: [{ messageId: "problem", fix(fixer) { return fixer.remove(node); } }]',
      ),
      "require-meta-has-suggestions",
    ],
  ])(
    "rejects %s through the real wrapper",
    async (_label, source, expectedRule) => {
      const [result] = await AUTHORING_ESLINT.lintText(source, {
        filePath: "src/rules/example.ts",
      });

      expect(result?.messages.map((message) => message.ruleId)).toContain(
        `eslint-plugin/${expectedRule}`,
      );
    },
  );

  it("keeps authoring-only rules out of consumer source", async () => {
    const [result] = await AUTHORING_ESLINT.lintText(
      VALID_RULE.replace("schema: [], ", ""),
      {
        filePath: "scripts/example.ts",
      },
    );

    expect(
      result?.messages.filter((message) =>
        message.ruleId?.startsWith("eslint-plugin/"),
      ),
    ).toEqual([]);
  });
});
