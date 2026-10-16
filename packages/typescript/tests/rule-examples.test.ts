import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import restrictedLoad from "../src/rules/no-restricted-library-load.js";
import statelessStorage from "../src/rules/no-storage-in-stateless-modules.js";
import zodOutput from "../src/rules/prefer-zod-parse-output-type.js";
import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
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

function locationProbe(loc: TSESTree.Position | TSESTree.SourceLocation, source = "debugger;") {
  return createRule<[], "found">({
    name: "location-probe",
    documentation: { ...DOCUMENTATION, autofix: "none", examples: [
      { id: "matching", title: "Reports at an explicit location", outcome: "match", expectedCount: 1, public: true,
        focusPath: "src/example.ts", files: [{ path: "src/example.ts", source }] },
      { id: "non-matching", title: "Leaves the negative control clean", outcome: "no-match", expectedCount: 0, public: true,
        focusPath: "src/example.ts", files: [{ path: "src/example.ts", source: "export {};" }] },
    ] },
    meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [], messages: { found: "Found." } },
    defaultOptions: [],
    create(context) {
      return { Program() {
        if (context.sourceCode.text !== "export {};") context.report({ loc, messageId: "found" });
      } };
    },
  });
}

describe("physical diagnostic locations", () => {
  it.each([
    { line: 999, column: 999 },
    { line: 1, column: 999 },
    { start: { line: 1, column: 0 }, end: { line: 999, column: 999 } },
    { start: { line: 1, column: 0 }, end: { line: 1, column: 999 } },
    { start: { line: 1, column: 5 }, end: { line: 1, column: 0 } },
  ])("rejects a count-correct finding outside its source: %j", async (loc) => {
    await expect(verifyRuleExamples(locationProbe(loc))).rejects.toThrow("matching: invalid diagnostic location");
  });

  it("uses UTF-16 columns rather than a UTF-8 byte upper bound", async () => {
    const source = "const label = '😀'; debugger;";
    await expect(verifyRuleExamples(locationProbe({ line: 1, column: source.length + 1 }, source))).rejects.toThrow("matching: invalid diagnostic location");
    await expect(verifyRuleExamples(locationProbe({ line: 1, column: source.length }, source))).resolves.toBe(2);
  });

  it.each(["\n", "\r", "\r\n", "\u2028", "\u2029"])("allows EOF on an empty physical line after %j", async (source) => {
    await expect(verifyRuleExamples(locationProbe({ line: 2, column: 0 }, source))).resolves.toBe(2);
  });

  it("allows an exclusive end location exactly at EOF", async () => {
    const source = "debugger;";
    await expect(verifyRuleExamples(locationProbe({ start: { line: 1, column: 0 }, end: { line: 1, column: source.length } }, source))).resolves.toBe(2);
  });

  it("allows a span ending at EOF after a CRLF line break", async () => {
    await expect(verifyRuleExamples(locationProbe({ start: { line: 1, column: 0 }, end: { line: 2, column: 0 } }, "debugger;\r\n"))).resolves.toBe(2);
  });

  it("preserves the empty source's zero-width EOF position", async () => {
    const rule = locationProbe({ line: 1, column: 0 });
    const spec = rule.documentation;
    if (spec === undefined) throw new Error("Missing probe documentation");
    const examples = spec.examples.map((example) => example.outcome === "match"
      ? { ...example, files: [{ path: example.focusPath, source: "" }] }
      : example);
    await expect(verifyRuleExamples({ ...rule, documentation: { ...spec, examples } })).resolves.toBe(2);
  });
});

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
  it("rejects malformed sibling source even when the focus file parses", async () => {
    const rule = probeRule(true, { ...DOCUMENTATION, examples: (DOCUMENTATION.examples ?? []).map((example) => ({
      ...example,
      files: [...example.files, { path: "src/sibling.ts", source: "export const = ;" }],
    })) });
    await expect(verifyRuleExamples(rule)).rejects.toThrow("matching: invalid fixture src/sibling.ts");
  });
  it("does not count duplicate same-span diagnostics as independent findings", async () => {
    const rule = createRule<[], "found">({
      name: "duplicate-probe",
      documentation: { ...DOCUMENTATION, autofix: "none", examples: (DOCUMENTATION.examples ?? [])
        .filter((example) => example.public)
        .map((example) => ({ ...example, expectedCount: example.outcome === "match" ? 2 : 0, fixedFiles: [] })) },
      meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [], messages: { found: "Found." } },
      defaultOptions: [],
      create(context) {
        return { DebuggerStatement(node) {
          context.report({ node, messageId: "found" });
          context.report({ node, messageId: "found" });
        } };
      },
    });
    await expect(verifyRuleExamples(rule)).rejects.toThrow("matching: duplicate diagnostic");
  });
  it("permits different diagnostic identities at one span", async () => {
    const rule = createRule<[], "first" | "second">({
      name: "distinct-probe",
      documentation: { ...DOCUMENTATION, autofix: "none", examples: (DOCUMENTATION.examples ?? [])
        .filter((example) => example.public)
        .map((example) => ({ ...example, expectedCount: example.outcome === "match" ? 2 : 0, fixedFiles: [] })) },
      meta: { type: "problem", docs: { description: DOCUMENTATION.summary }, schema: [], messages: { first: "First.", second: "Second." } },
      defaultOptions: [],
      create(context) {
        return { DebuggerStatement(node) {
          context.report({ node, messageId: "first" });
          context.report({ node, messageId: "second" });
        } };
      },
    });
    await expect(verifyRuleExamples(rule)).resolves.toBe(2);
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
    await expect(verifyRuleExamples(restrictedLoad)).resolves.toBe(3);
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
