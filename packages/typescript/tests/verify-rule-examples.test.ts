import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { format } from "prettier";
import { describe, expect, it } from "vitest";

import { RULES, type DocumentedRule } from "../src/catalog.js";
import { ruleSpec, type DiagnosticExpectation, type RuleDocumentation, type RuleExample } from "../src/documentation.js";
import { defineRule, type ESTree, type SarjRule } from "../src/types.js";
import { verifyRuleExamples } from "../src/verify-rule-examples.js";

const PACKAGE_ROOT = new URL("../", import.meta.url).pathname;
const SUMMARY = "Reject debugger statements in an executable example.";
const MATCHING: RuleExample = {
  id: "matching", title: "Reports debugger", outcome: "match", expectedCount: 1, public: true,
  focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "debugger; export const value: number = 1;\n" }],
  fixedFiles: [{ path: "src/example.ts", source: " export const value: number = 1;\n" }],
};
const NON_MATCHING: RuleExample = {
  id: "non-matching", title: "Allows normal code", outcome: "no-match", expectedCount: 0, public: true,
  focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "export const value: number = 1;\n" }],
};
const DOCUMENTATION: RuleDocumentation = {
  summary: SUMMARY,
  rationale: "A debugger statement interrupts execution.",
  remediation: "Remove the debugger statement.",
  category: "correctness",
  autofix: "safe",
  examples: [MATCHING, NON_MATCHING],
};

function documented(rule: SarjRule, examples: readonly RuleExample[] = [MATCHING, NON_MATCHING]): DocumentedRule {
  return { ...rule, documentation: ruleSpec("example-probe", rule.meta ?? {}, { ...DOCUMENTATION, examples }) };
}

function probe(report: (context: Parameters<SarjRule["createOnce"]>[0], node: ESTree.DebuggerStatement) => void): SarjRule {
  return defineRule({
    meta: { type: "problem", fixable: "code", hasSuggestions: true, docs: { description: SUMMARY }, schema: [],
      messages: { debugger: "Remove debugger.", remove: "Remove it." } },
    createOnce(context) {
      return { DebuggerStatement(node: ESTree.DebuggerStatement) { report(context, node); } };
    },
  });
}

const FIXING = probe((context, node) => {
  context.report({ node, messageId: "debugger", fix: (fixer) => fixer.remove(node) });
});

describe("executable authored examples", () => {
  it("runs matching and non-matching examples and checks the clean, exact fix", async () => {
    await expect(verifyRuleExamples(documented(FIXING))).resolves.toBe(2);
  });

  it.each([
    ["always reports", probe((context, node) => { context.report({ node, messageId: "debugger" }); }), "non-matching", { ...NON_MATCHING, files: [{ path: "src/example.ts", source: "debugger;\n" }] }],
    ["never reports", probe(() => undefined), "matching", MATCHING],
  ] as const)("rejects a detector that %s", async (_behavior, rule, failing, example) => {
    const examples = failing === "matching" ? [example, NON_MATCHING] : [{ ...MATCHING, fixedFiles: [] }, example];
    await expect(verifyRuleExamples(documented(rule, examples))).rejects.toThrow(`${failing}: Should have`);
  });

  it("rejects a detector that throws", async () => {
    const rule = defineRule({ meta: FIXING.meta ?? {}, createOnce() { throw new Error("Implement this detector"); } });
    await expect(verifyRuleExamples(documented(rule))).rejects.toThrow("Implement this detector");
  });

  it("rejects malformed private fixtures instead of accepting a zero-finding case", async () => {
    const malformed: RuleExample = { id: "malformed", title: "Malformed source", outcome: "no-match", expectedCount: 0,
      focusPath: "src/broken.ts", files: [{ path: "src/broken.ts", source: "const = ;" }] };
    await expect(verifyRuleExamples(documented(FIXING, [MATCHING, NON_MATCHING, malformed]))).rejects.toThrow("malformed: invalid fixture");
  });

  it("rejects malformed sibling source even when the focus file parses", async () => {
    const examples = [MATCHING, NON_MATCHING].map((example) => ({ ...example, files: [...example.files, { path: "src/sibling.ts", source: "export const = ;" }] }));
    await expect(verifyRuleExamples(documented(FIXING, examples))).rejects.toThrow("matching: invalid fixture src/sibling.ts");
  });

  it("rejects a documented fixed output that the rule cannot produce", async () => {
    const examples = [{ ...MATCHING, fixedFiles: [{ path: MATCHING.focusPath, source: "export {};\n" }] }, NON_MATCHING];
    await expect(verifyRuleExamples(documented(FIXING, examples))).rejects.toThrow("matching: unexpected fixed source");
    await expect(verifyRuleExamples(documented(FIXING, examples), { formatFixedSource: (file) => format(file.source, { parser: "typescript" }) }))
      .rejects.toThrow("matching: unexpected fixed source");
  });

  it("keeps raw authored fixes exact while comparing an explicitly formatted fixed source", async () => {
    const examples = [{ ...MATCHING, fixedFiles: [{ path: MATCHING.focusPath, source: "export const value: number = 1;\n" }] }, NON_MATCHING];
    await expect(verifyRuleExamples(documented(FIXING, examples))).rejects.toThrow("unexpected fixed source");
    await expect(verifyRuleExamples(documented(FIXING, examples), { formatFixedSource: async (file, example) => {
      expect(example.public).toBe(true);
      expect(file.source).toBe(" export const value: number = 1;\n");
      return format(file.source, { parser: "typescript" });
    } })).resolves.toBe(2);
  });

  it("refuses a fix that keeps reporting before calling the supplied formatter", async () => {
    let formats = 0;
    const persistent = probe((context, node) => {
      context.report({ node, messageId: "debugger", fix: (fixer) => fixer.insertTextBefore(node, "debugger;") });
    });
    await expect(verifyRuleExamples(documented(persistent), { formatFixedSource: () => {
      formats += 1;
      return "";
    } })).rejects.toThrow("matching: Should have no errors");
    expect(formats).toBe(0);
  });
});

describe("opt-in exact diagnostic expectations", () => {
  const EXPECTED: DiagnosticExpectation = {
    messageId: "debugger", message: "Remove debugger.", location: { line: 1, column: 1, end: { line: 1, column: 10 } },
    automaticFix: true, suggestions: [{ messageId: "remove", output: " export const value: number = 1;\n" }],
  };
  const SUGGESTING = probe((context, node) => {
    context.report({ node, messageId: "debugger", fix: (fixer) => fixer.remove(node), suggest: [{ messageId: "remove", fix: (fixer) => fixer.remove(node) }] });
  });
  const expecting = (expected: DiagnosticExpectation): readonly RuleExample[] => [{ ...MATCHING, expectedDiagnostics: [expected] }, NON_MATCHING];

  it("checks identity, message, location, fix delivery and suggestions", async () => {
    await expect(verifyRuleExamples(documented(SUGGESTING, expecting(EXPECTED)))).resolves.toBe(2);
  });

  it.each([
    ["message ID", { ...EXPECTED, messageId: "remove" }],
    ["message", { ...EXPECTED, message: "Remove the debugger." }],
    ["location", { ...EXPECTED, location: { line: 1, column: 2 } }],
    ["automatic fix", { ...EXPECTED, automaticFix: false }],
    ["suggestion output", { ...EXPECTED, suggestions: [{ messageId: "remove", output: "export {};\n" }] }],
    ["missing suggestion", { ...EXPECTED, suggestions: [] }],
  ] as const)("rejects a wrong %s", async (_field, expected) => {
    await expect(verifyRuleExamples(documented(SUGGESTING, expecting(expected)))).rejects.toThrow("matching:");
  });
});

describe("declarative example setup", () => {
  const restrictedLoad = RULES["no-restricted-library-load"];
  const zodOutput = RULES["prefer-zod-parse-output-type"];
  const withExamples = (rule: DocumentedRule, change: (example: RuleExample) => RuleExample): DocumentedRule =>
    ({ ...rule, documentation: { ...rule.documentation, examples: rule.documentation.examples.map(change) } });

  it("runs opt-in public examples while retaining empty production defaults", async () => {
    expect(restrictedLoad.meta?.defaultOptions).toEqual([{ libraries: [] }]);
    await expect(verifyRuleExamples(restrictedLoad)).resolves.toBe(4);
  });

  it("preserves the positive oracle with an explicitly empty policy", async () => {
    await expect(verifyRuleExamples(withExamples(restrictedLoad, (example) => ({ ...example, ruleOptions: [] }))))
      .rejects.toThrow("runtime-load: Should have 1 error but had 0");
  });

  it("uses the exact explicitly installed Zod declarations", async () => {
    await expect(verifyRuleExamples(zodOutput, { installedDependencyRoot: PACKAGE_ROOT })).resolves.toBe(3);
  });

  it("fails clearly without an explicit installed dependency root", async () => {
    await expect(verifyRuleExamples(zodOutput)).rejects.toThrow("explicit installed dependency root is required");
  });

  it("rejects installed dependency version drift", async () => {
    const rule = withExamples(zodOutput, (example) => ({ ...example, installedDependencies: [{ module: "zod", version: "0.0.0" }] }));
    await expect(verifyRuleExamples(rule, { installedDependencyRoot: PACKAGE_ROOT })).rejects.toThrow("identity/version mismatch");
  });

  it("rejects a missing installed dependency", async () => {
    const rule = withExamples(zodOutput, (example) => ({ ...example, installedDependencies: [{ module: "sarj-example-missing", version: "0.0.0" }] }));
    await expect(verifyRuleExamples(rule, { installedDependencyRoot: PACKAGE_ROOT })).rejects.toThrow("ENOENT");
  });

  it("does not replace an explicit empty dependency root with ambient packages", async () => {
    const root = await mkdtemp(join(tmpdir(), "sarj-installed-example-"));
    try {
      await expect(verifyRuleExamples(zodOutput, { installedDependencyRoot: root })).rejects.toThrow("ENOENT");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
