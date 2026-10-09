import { ESLintUtils } from "@typescript-eslint/utils";
import { describe, expect, it } from "vitest";

import { verifyRuleExamples } from "../src/verify-rule-examples.js";
import { createRule, type RuleDocumentation } from "../src/rules/_docs.js";

const DOCUMENTATION: RuleDocumentation = {
  summary: "Reject debugger statements in an executable example.",
  rationale: "A debugger statement interrupts execution.",
  remediation: "Remove the debugger statement.",
  category: "correctness",
  autofix: "safe",
  examples: [
    { id: "matching", title: "Reports debugger", outcome: "match", expectedCount: 1, public: true,
      focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "debugger; export const value: number = 1;\n" }],
      fixedFiles: [{ path: "src/example.ts", source: "export const value: number = 1;\n" }] },
    { id: "non-matching", title: "Allows normal code", outcome: "no-match", expectedCount: 0, public: true,
      focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "export const value: number = 1;\n" }] },
    { id: "suppressed", title: "Honors suppression", outcome: "no-match", expectedCount: 0,
      focusPath: "src/example.ts", files: [{ path: "src/example.ts",
        source: "// eslint-disable-next-line @sarj/example-probe\ndebugger;\n" }] },
  ],
};

function probeRule(implemented: boolean, documentation: RuleDocumentation = DOCUMENTATION) {
  return createRule<[], "debugger">({
    name: "example-probe",
    documentation,
    meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [],
      fixable: "code", messages: { debugger: "Remove debugger." } },
    defaultOptions: [],
    create(context) {
      return implemented ? { DebuggerStatement(node) {
        context.report({ node, messageId: "debugger", fix: (fixer) => fixer.removeRange([node.range[0], node.range[1] + 1]) });
      } } : {};
    },
  });
}

describe("executable authored examples", () => {
  it("checks typed fixtures, private suppression cases and idempotent fixes", async () => {
    await expect(verifyRuleExamples(probeRule(true))).resolves.toBe(3);
  });
  it("rejects malformed private fixtures instead of accepting a zero-finding case", async () => {
    const rule = probeRule(true, { ...DOCUMENTATION, examples: [
      ...(DOCUMENTATION.examples ?? []),
      { id: "malformed", title: "Malformed source", outcome: "no-match", expectedCount: 0,
        focusPath: "src/broken.ts", files: [{ path: "src/broken.ts", source: "const = ;" }] },
    ] });
    await expect(verifyRuleExamples(rule)).rejects.toThrow("malformed: invalid fixture");
  });
  it("rejects a documented fixed output that the rule cannot produce", async () => {
    const rule = probeRule(true, { ...DOCUMENTATION, examples: (DOCUMENTATION.examples ?? []).map((example) =>
      example.outcome === "match" ? { ...example, fixedFiles: [{ path: example.focusPath, source: "export {};\n" }] } : example),
    });
    await expect(verifyRuleExamples(rule)).rejects.toThrow("unexpected fixed source");
  });
  it("fails an unimplemented detector despite complete public labels", async () => {
    await expect(verifyRuleExamples(probeRule(false))).rejects.toThrow("expected 1 findings, received 0");
  });
});

describe("dummy detector mutation proof", () => {
  it.each(["correct", "always-report", "always-clean", "unimplemented"] as const)(
    "%s is accepted only when both positive and negative examples hold", async (behavior) => {
      const rule = createRule<[], "found">({
        name: "dummy-detector",
        documentation: { ...DOCUMENTATION, autofix: "none", examples: [
          { id: "positive", title: "Reject debugger", outcome: "match", expectedCount: 1, public: true,
            focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "debugger;\n" }] },
          { id: "negative", title: "Allow normal code", outcome: "no-match", expectedCount: 0, public: true,
            focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "export {};\n" }] },
        ] },
        meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [], messages: { found: "Found." } },
        defaultOptions: [],
        create(context) {
          if (behavior === "unimplemented") throw new Error("Implement this detector");
          if (behavior === "always-clean") return {};
          if (behavior === "always-report") return { Program(node) { context.report({ node, messageId: "found" }); } };
          return { DebuggerStatement(node) { context.report({ node, messageId: "found" }); } };
        },
      });
      if (behavior === "correct") await expect(verifyRuleExamples(rule)).resolves.toBe(2);
      else await expect(verifyRuleExamples(rule)).rejects.toThrow();
    },
  );
  it("loads sibling fixtures and the authored tsconfig for typed rules", async () => {
    const rule = createRule<[], "found">({
      name: "typed-detector",
      documentation: { ...DOCUMENTATION, autofix: "none", examples: ["match", "no-match"].map((outcome) => ({
        id: outcome, title: outcome, outcome: outcome as "match" | "no-match", expectedCount: outcome === "match" ? 1 : 0,
        public: true, focusPath: "src/example.ts", files: [
          { path: "tsconfig.json", source: '{"compilerOptions":{"baseUrl":".","paths":{"@fixture":["src/value.ts"]}},"include":["src"]}' },
          { path: "src/value.ts", source: outcome === "match" ? "export const value: string = 'x';\n" : "export const value: number = 1;\n" },
          { path: "src/example.ts", source: 'import { value } from "@fixture";\nvalue;\n' },
        ],
      })) },
      meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [], messages: { found: "Found." } },
      defaultOptions: [],
      create(context) {
        const services = ESLintUtils.getParserServices(context);
        const checker = services.program.getTypeChecker();
        return { ExpressionStatement(node) {
          const type = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.expression));
          if (checker.typeToString(type) === "string") context.report({ node, messageId: "found" });
        } };
      },
    });
    await expect(verifyRuleExamples(rule)).resolves.toBe(2);
  });
});
