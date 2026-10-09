import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import restrictedLoad from "../src/rules/no-restricted-library-load.js";
import statelessStorage from "../src/rules/no-storage-in-stateless-modules.js";
import zodOutput from "../src/rules/prefer-zod-parse-output-type.js";
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


describe("declarative example setup", () => {
  it("runs opt-in public examples while retaining empty production defaults", async () => {
    expect(restrictedLoad.defaultOptions).toEqual([{ libraries: [] }]);
    expect(statelessStorage.defaultOptions).toEqual([{}]);
    await expect(verifyRuleExamples(restrictedLoad)).resolves.toBe(2);
    await expect(verifyRuleExamples(statelessStorage)).resolves.toBe(2);
  });
  it("uses the exact explicitly installed Zod declarations", async () => {
    await expect(verifyRuleExamples(zodOutput, { installedDependencyRoot: new URL("../", import.meta.url).pathname })).resolves.toBe(2);
  });
  it("fails clearly without an explicit installed dependency root", async () => {
    await expect(verifyRuleExamples(zodOutput)).rejects.toThrow("explicit installed dependency root is required");
  });
  it("rejects installed dependency version drift", async () => {
    const rule = { ...zodOutput, documentation: { ...zodOutput.documentation, examples: zodOutput.documentation.examples.map(example => ({ ...example, installedDependencies: [{ module: "zod", version: "0.0.0" }] })) } };
    await expect(verifyRuleExamples(rule, { installedDependencyRoot: new URL("../", import.meta.url).pathname })).rejects.toThrow("identity/version mismatch");
  });
  it("rejects a missing installed dependency", async () => {
    const rule = { ...zodOutput, documentation: { ...zodOutput.documentation, examples: zodOutput.documentation.examples.map(example => ({ ...example, installedDependencies: [{ module: "sarj-example-missing", version: "0.0.0" }] })) } };
    await expect(verifyRuleExamples(rule, { installedDependencyRoot: new URL("../", import.meta.url).pathname })).rejects.toThrow("ENOENT");
  });
  it("preserves the positive oracle with an explicitly empty policy", async () => {
    const rule = { ...restrictedLoad, documentation: { ...restrictedLoad.documentation, examples: restrictedLoad.documentation.examples.map(example => ({ ...example, ruleOptions: [] })) } };
    await expect(verifyRuleExamples(rule)).rejects.toThrow("expected 1 findings, received 0");
  });
  it("lets native ESLint reject malformed per-example options", async () => {
    const rule = { ...restrictedLoad, documentation: { ...restrictedLoad.documentation, examples: restrictedLoad.documentation.examples.map(example => ({ ...example, ruleOptions: [{ unsupported: true }] })) } };
    await expect(verifyRuleExamples(rule)).rejects.toThrow("additional properties");
  });
});


it("does not replace an explicit empty dependency root with ambient packages", async () => {
  const root = await mkdtemp(join(tmpdir(), "sarj-installed-example-"));
  try {
    await expect(verifyRuleExamples(zodOutput, { installedDependencyRoot: root })).rejects.toThrow("ENOENT");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
