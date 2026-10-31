import { join } from "node:path";

import type { TSESLint } from "@typescript-eslint/utils";
import { Linter, type Rule } from "eslint";
import ts from "typescript";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  createRule,
  type DiagnosticExpectation,
  type RuleDocumentation,
  type RuleExample,
} from "../src/rules/_docs.js";
import { verifyRuleExamples } from "../src/verify-rule-examples.js";

const SUMMARY = "Report the debugger statement precisely.";
const SOURCE = "const token = 1;\ndebugger;\n";
const OUTPUT = "const token = 1;\nvoid 0;\n";
const ALTERNATIVE = "const token = 1;\nvoid 1;\n";
const MESSAGES = {
  found: "Found {{name}}.",
  other: "Other diagnostic.",
  replace: "Replace debugger.",
  alternative: "Use the alternative replacement.",
} as const;
type MessageId = keyof typeof MESSAGES;
type Mutation = "correct" | "program" | "sibling" | "identity" | "interpolation" |
  "promote" | "demote" | "drop" | "corrupt" | "reverse-suggestions";

function expectedDiagnostic(automaticFix: boolean): DiagnosticExpectation {
  return {
    messageId: "found", message: "Found debugger.",
    location: { line: 2, column: 1, end: { line: 2, column: 10 } },
    automaticFix,
    suggestions: [
      { messageId: "replace", output: OUTPUT },
      { messageId: "alternative", output: ALTERNATIVE },
    ],
  };
}

function probe(mutation: Mutation, checked: boolean, automaticFix = false, fixedFiles = false) {
  const matchingBase: RuleExample<[]> = {
    id: "matching", title: "Reject debugger", outcome: "match", expectedCount: 1, public: true,
    focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: SOURCE }],
  };
  const matchingWithDiagnostics: RuleExample<[]> = checked
    ? { ...matchingBase, expectedDiagnostics: [expectedDiagnostic(automaticFix)] }
    : matchingBase;
  const matching: RuleExample<[]> = fixedFiles
    ? { ...matchingWithDiagnostics, fixedFiles: [{ path: "src/input.ts", source: OUTPUT }] }
    : matchingWithDiagnostics;
  const clean: RuleExample<[]> = {
    id: "clean", title: "Allow ordinary source", outcome: "no-match", expectedCount: 0, public: true,
    focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "export {};\n" }],
  };
  const suppressed: RuleExample<[]> = {
    id: "suppressed", title: "Respect explicit suppression", outcome: "no-match", expectedCount: 0,
    focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "/* eslint-disable @sarj/expectation-probe */\ndebugger;\n" }],
  };
  const documentation: RuleDocumentation<[]> = {
    summary: SUMMARY, rationale: "A misplaced or misdelivered report is a different contract.",
    remediation: "Report the reviewed statement and deliver the reviewed edits.", category: "correctness",
    examples: [
      matching,
      checked ? { ...clean, expectedDiagnostics: [] } : clean,
      checked ? { ...suppressed, expectedDiagnostics: [] } : suppressed,
    ],
  };
  return createRule<[], MessageId>({
    name: "expectation-probe", documentation,
    meta: { type: "problem", docs: { description: SUMMARY }, schema: [], messages: MESSAGES, fixable: "code", hasSuggestions: true },
    defaultOptions: [],
    create(context) {
      return { DebuggerStatement(node) {
        const replacement = mutation === "corrupt" ? "void 2;" : "void 0;";
        const suggestions = [
          { messageId: "replace" as const, fix: (fixer: TSESLint.RuleFixer) => fixer.replaceTextRange(node.range, replacement) },
          { messageId: "alternative" as const, fix: (fixer: TSESLint.RuleFixer) => fixer.replaceTextRange(node.range, "void 1;") },
        ];
        const reportBase: TSESLint.ReportDescriptor<MessageId> = {
          ...(mutation === "sibling" ? { loc: { line: 1, column: 6 } } : { node: mutation === "program" ? context.sourceCode.ast : node }),
          messageId: mutation === "identity" ? "other" : "found",
          data: { name: mutation === "interpolation" ? "mutated" : "debugger" },
        };
        const report = (automaticFix && mutation !== "demote") || mutation === "promote"
          ? { ...reportBase, fix: (fixer: TSESLint.RuleFixer) => fixer.replaceTextRange(node.range, "void 0;") }
          : reportBase;
        context.report({
          ...report,
          suggest: mutation === "drop" ? [] : mutation === "reverse-suggestions" ? [...suggestions].reverse() : suggestions,
        });
      } };
    },
  });
}

describe("opt-in exact diagnostic expectations", () => {
  it.each([
    { checked: false, fixedFiles: false },
    { checked: true, fixedFiles: false },
    { checked: false, fixedFiles: true },
    { checked: true, fixedFiles: true },
  ])("preserves genuine optional-field omission: checked=$checked fixedFiles=$fixedFiles", ({ checked, fixedFiles }) => {
    const spec = probe("correct", checked, fixedFiles, fixedFiles).documentation;
    if (spec === undefined) throw new Error("Missing probe documentation");
    for (const example of spec.examples) {
      expect(Object.hasOwn(example, "expectedDiagnostics")).toBe(checked);
      expect(Object.hasOwn(example, "fixedFiles")).toBe(example.id === "matching" && fixedFiles);
    }
  });

  it("checks identity, location, complete suggestions, suppression and clean automatic fixes", async () => {
    await expect(verifyRuleExamples(probe("correct", true))).resolves.toBe(3);
    await expect(verifyRuleExamples(probe("correct", true, true, true))).resolves.toBe(3);
  });

  it.each([
    "program", "sibling", "identity", "interpolation", "promote", "drop", "corrupt", "reverse-suggestions",
  ] as const)("rejects %s while the omitted-field compatibility path still accepts its count", async (mutation) => {
    await expect(verifyRuleExamples(probe(mutation, false))).resolves.toBe(3);
    await expect(verifyRuleExamples(probe(mutation, true))).rejects.toThrow("matching: unexpected diagnostics");
  });

  it("rejects demotion from an automatic fix to suggestions without requiring fixedFiles", async () => {
    await expect(verifyRuleExamples(probe("demote", false, true))).resolves.toBe(3);
    await expect(verifyRuleExamples(probe("demote", true, true))).rejects.toThrow("matching: unexpected diagnostics");
  });

  it("detects a missing suggestion even when the actual automatic output is clean and idempotent", async () => {
    await expect(verifyRuleExamples(probe("drop", false, true, true))).resolves.toBe(3);
    await expect(verifyRuleExamples(probe("drop", true, true, true))).rejects.toThrow("matching: unexpected diagnostics");
  });

  it.each([false, true])("matches distinct same-span identities regardless of emission order: reversed=%s", async (reversed) => {
    const expectations = ["first", "second"].map((messageId) => ({
      messageId, message: messageId === "first" ? "First." : "Second.",
      location: { line: 1, column: 1, end: { line: 1, column: 10 } }, automaticFix: false, suggestions: [],
    }));
    const rule = createRule<[], "first" | "second">({
      name: "distinct-expectations",
      documentation: { summary: SUMMARY, rationale: "Both reports are independently meaningful.", remediation: "Remove debugger.", category: "correctness", examples: [
        { id: "matching", title: "Report both identities", outcome: "match", expectedCount: 2, public: true, focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "debugger;" }], expectedDiagnostics: expectations },
        { id: "clean", title: "Allow ordinary source", outcome: "no-match", expectedCount: 0, public: true, focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "export {};" }], expectedDiagnostics: [] },
      ] },
      meta: { type: "problem", docs: { description: SUMMARY }, schema: [], messages: { first: "First.", second: "Second." } },
      defaultOptions: [],
      create(context) { return { DebuggerStatement(node) {
        for (const messageId of reversed ? ["second", "first"] as const : ["first", "second"] as const) context.report({ node, messageId });
      } }; },
    });
    await expect(verifyRuleExamples(rule)).resolves.toBe(2);
  });

  it("rejects an authored location outside physical UTF-16 source bounds", async () => {
    const rule = probe("correct", true);
    const spec = rule.documentation;
    if (spec === undefined) throw new Error("Missing probe documentation");
    const examples = spec.examples.map((example) => example.id === "matching" ? {
      ...example, expectedDiagnostics: [{ ...expectedDiagnostic(false), location: { line: 2, column: 100 } }],
    } : example);
    await expect(verifyRuleExamples({ ...rule, documentation: { ...spec, examples } })).rejects.toThrow("invalid expected diagnostic location");
  });

  it("accepts an exact point diagnostic at CRLF EOF without inventing an end span", async () => {
    const rule = createRule<[], "found">({
      name: "eof-expectation-probe",
      documentation: { summary: SUMMARY, rationale: "A point report has no implied end span.", remediation: "Use the reviewed point.", category: "correctness", examples: [
        { id: "matching", title: "Report the EOF point", outcome: "match", expectedCount: 1, public: true, focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "debugger;\r\n" }], expectedDiagnostics: [{ messageId: "found", message: "At EOF.", location: { line: 2, column: 1 }, automaticFix: false, suggestions: [] }] },
        { id: "clean", title: "Allow ordinary source", outcome: "no-match", expectedCount: 0, public: true, focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "export {};" }], expectedDiagnostics: [] },
      ] },
      meta: { type: "problem", docs: { description: SUMMARY }, schema: [], messages: { found: "At EOF." } },
      defaultOptions: [],
      create(context) { return { DebuggerStatement() { context.report({ loc: { line: 2, column: 0 }, messageId: "found" }); } }; },
    });
    await expect(verifyRuleExamples(rule)).resolves.toBe(2);
  });
});

interface EditCase {
  readonly id: string;
  readonly source: string;
  readonly range: readonly [number, number];
  readonly replacement: string;
  readonly output: string;
  readonly line: number;
}

function suggestionProbe(edit: EditCase) {
  return createRule<[], "found" | "replace">({
    name: "suggestion-offset-probe",
    documentation: { summary: SUMMARY, rationale: "Suggestion offsets follow native ESLint source semantics.", remediation: "Apply only the selected suggestion.", category: "correctness", examples: [
      { id: "matching", title: "Apply the reviewed suggestion", outcome: "match", expectedCount: 1, public: true,
        focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: edit.source }],
        expectedDiagnostics: [{ messageId: "found", message: "Found debugger.", location: { line: edit.line, column: 1, end: { line: edit.line, column: 10 } }, automaticFix: false, suggestions: [{ messageId: "replace", output: edit.output }] }] },
      { id: "clean", title: "Allow ordinary source", outcome: "no-match", expectedCount: 0, public: true,
        focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: "export {};" }], expectedDiagnostics: [] },
    ] },
    meta: { type: "problem", docs: { description: SUMMARY }, schema: [], messages: { found: "Found debugger.", replace: "Replace debugger." }, hasSuggestions: true },
    defaultOptions: [],
    create(context) { return { DebuggerStatement(node) {
      context.report({ node, messageId: "found", suggest: [{ messageId: "replace", fix: (fixer) => fixer.replaceTextRange([edit.range[0], edit.range[1]], edit.replacement) }] });
    } }; },
  });
}

function nativeSingleFixOutput(edit: EditCase): string {
  let firstPass = true;
  const rule: Rule.RuleModule = {
    meta: { type: "problem", schema: [], messages: { found: "Found debugger." }, fixable: "code" },
    create(context) {
      if (!firstPass) return {};
      firstPass = false;
      return { DebuggerStatement(node) {
        context.report({ node, messageId: "found", fix: (fixer) => fixer.replaceTextRange([edit.range[0], edit.range[1]], edit.replacement) });
      } };
    },
  };
  return new Linter().verifyAndFix(edit.source, {
    plugins: { probe: { rules: { edit: rule } } }, rules: { "probe/edit": "error" },
  }).output;
}

const EDITS: readonly EditCase[] = [
  { id: "empty-output", source: "debugger;", range: [0, 9], replacement: "", output: "", line: 1 },
  { id: "preserve-bom", source: "\uFEFFdebugger;", range: [0, 9], replacement: "void 0;", output: "\uFEFFvoid 0;", line: 1 },
  { id: "remove-bom", source: "\uFEFFdebugger;", range: [-1, 0], replacement: "", output: "debugger;", line: 1 },
  { id: "replace-bom-once", source: "\uFEFFdebugger;", range: [0, 0], replacement: "\uFEFF", output: "\uFEFFdebugger;", line: 1 },
  { id: "astral-crlf", source: "const label = '😀';\r\ndebugger;\r\n", range: [21, 30], replacement: "void 0;", output: "const label = '😀';\r\nvoid 0;\r\n", line: 2 },
];

describe("independent normalized suggestion edits", () => {
  it.each(EDITS)("matches pinned ESLint's single automatic edit for $id", async (edit) => {
    expect(nativeSingleFixOutput(edit)).toBe(edit.output);
    await expect(verifyRuleExamples(suggestionProbe(edit))).resolves.toBe(2);
  });

  it.each([
    { id: "past-eof", range: [0, 99] }, { id: "reversed", range: [3, 1] },
    { id: "fraction", range: [0, 0.5] }, { id: "nan", range: [Number.NaN, 1] },
    { id: "infinity", range: [0, Number.POSITIVE_INFINITY] }, { id: "missing-bom", range: [-1, 0] },
    { id: "before-bom", range: [-2, 0] }, { id: "negative-end", range: [-1, -1] },
  ] as const)("rejects a real reported malformed suggestion: $id", async ({ id, range }) => {
    const source = id === "before-bom" || id === "negative-end" ? "\uFEFFdebugger;" : "debugger;";
    await expect(verifyRuleExamples(suggestionProbe({ id, source, range, replacement: "", output: "", line: 1 }))).rejects.toThrow("invalid suggestion edit range");
  });
});

function runtimeDeclaration(expectedDiagnostics: unknown): void {
  Reflect.apply(createRule, undefined, [{
    name: "runtime-expectation-probe",
    documentation: { summary: SUMMARY, rationale: "Validate untyped authored declarations.", remediation: "Use the closed expectation types.", category: "correctness", examples: [
      { id: "matching", title: "Check one diagnostic", outcome: "match", expectedCount: 1, focusPath: "src/input.ts", files: [{ path: "src/input.ts", source: SOURCE }], expectedDiagnostics },
    ] },
    meta: { type: "problem", docs: { description: SUMMARY }, schema: [], messages: MESSAGES },
    defaultOptions: [], create: () => ({}),
  }]);
}

describe("runtime authored expectation boundary", () => {
  it.each([
    { id: "not-array", value: null }, { id: "count", value: [] },
    { id: "unknown-id", value: [{ ...expectedDiagnostic(false), messageId: "missing" }] },
    { id: "prototype-id", value: [{ ...expectedDiagnostic(false), messageId: "toString" }] },
    { id: "message-type", value: [{ ...expectedDiagnostic(false), message: 1 }] },
    { id: "delivery-type", value: [{ ...expectedDiagnostic(false), automaticFix: "false" }] },
    { id: "missing-suggestions", value: [{ messageId: "found", message: "Found debugger.", location: { line: 2, column: 1 }, automaticFix: false }] },
    { id: "unknown-suggestion", value: [{ ...expectedDiagnostic(false), suggestions: [{ messageId: "missing", output: "" }] }] },
    { id: "prototype-suggestion", value: [{ ...expectedDiagnostic(false), suggestions: [{ messageId: "constructor", output: "" }] }] },
    { id: "suggestion-output-type", value: [{ ...expectedDiagnostic(false), suggestions: [{ messageId: "replace", output: null }] }] },
    { id: "zero-line", value: [{ ...expectedDiagnostic(false), location: { line: 0, column: 1 } }] },
    { id: "fractional-column", value: [{ ...expectedDiagnostic(false), location: { line: 1, column: 1.5 } }] },
    { id: "infinite-column", value: [{ ...expectedDiagnostic(false), location: { line: 1, column: Number.POSITIVE_INFINITY } }] },
    { id: "half-end", value: [{ ...expectedDiagnostic(false), location: { line: 2, column: 1, end: { line: 2 } } }] },
    { id: "reversed-end", value: [{ ...expectedDiagnostic(false), location: { line: 2, column: 1, end: { line: 1, column: 1 } } }] },
    { id: "extra-field", value: [{ ...expectedDiagnostic(false), extra: true }] },
  ])("rejects $id through the actual untyped createRule boundary", ({ value }) => {
    expect(() => runtimeDeclaration(value)).toThrow(TypeError);
  });
});

const PACKAGE_ROOT = join(import.meta.dirname, "..");
const CONTRACT_PATH = join(PACKAGE_ROOT, "src", "example-expectations-contract.ts").replaceAll("\\", "/");
const ACCEPTED = `
import { createRule, type DiagnosticExpectation, type ExamplePoint, type RuleDocumentation } from "./rules/_docs.js";
type Options = readonly [{ readonly mode: "strict" }];
const point: ExamplePoint = { line: 1, column: 10 };
const expected = [{ messageId: "found", message: "Found.", location: { line: 1, column: 1, end: point }, automaticFix: false, suggestions: [{ messageId: "replace", output: "" }] }] as const satisfies readonly DiagnosticExpectation[];
const example = { id: "matching", title: "Report debugger", outcome: "match", files: [{ path: "src/input.ts", source: "debugger;" }], focusPath: "src/input.ts", expectedCount: 1, expectedDiagnostics: expected, ruleOptions: [{ mode: "strict" }] } as const;
const documentation = { summary: "Report debugger.", rationale: "Debugger pauses execution.", remediation: "Remove debugger.", category: "correctness", examples: [example] } as const satisfies RuleDocumentation<Options>;
const defaults: Options = [{ mode: "strict" }];
const base = { name: "typed-expectation", meta: { type: "problem", docs: { description: documentation.summary }, schema: [], messages: { found: "Found.", replace: "Replace." } }, defaultOptions: defaults, create: () => ({}) } as const;
export const rule = createRule<Options, "found" | "replace">({ ...base, documentation });
`;
const REJECTED = `${ACCEPTED}
point.column = 2; // readonly-point
expected.push(expected[0]); // readonly-expectations
export const wrongId: DiagnosticExpectation = { ...expected[0], messageId: 1 }; // wrong-id-type
export const wrongFix: DiagnosticExpectation = { ...expected[0], automaticFix: "false" }; // wrong-delivery-type
export const halfEnd: DiagnosticExpectation = { ...expected[0], location: { line: 1, column: 1, end: { line: 1 } } }; // incomplete-end
export const wrongOutput: DiagnosticExpectation = { ...expected[0], suggestions: [{ messageId: "replace", output: false }] }; // wrong-output-type
createRule<Options, "found" | "replace">({ ...base, documentation: { ...documentation, examples: [{ ...example, expectedDiagnostics: [{ ...expected[0], location: { line: 1, column: 1, end: { column: 10 } } }] }] } }); // actual-create-boundary
createRule<Options, "found" | "replace">({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "loose" }] }] } }); // options-stay-authoritative
`;

interface CompilerFixture {
  readonly program: ts.Program;
  readonly contract: ts.SourceFile;
  readonly configIssues: readonly ts.Diagnostic[];
}

function prepareCompilerFixture(source: string): CompilerFixture {
  const loaded = ts.readConfigFile(join(PACKAGE_ROOT, "tsconfig.json"), (path) => ts.sys.readFile(path));
  const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, PACKAGE_ROOT);
  const options = { ...parsed.options, noEmit: true, incremental: false };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path.replaceAll("\\", "/") === CONTRACT_PATH
    ? ts.createSourceFile(path, source, version, true)
    : original(path, version, onError, create);
  const program = ts.createProgram([CONTRACT_PATH], options, host);
  const contract = program.getSourceFile(CONTRACT_PATH);
  if (contract?.text !== source) throw new Error("The compiler did not load the intended contract source.");
  return { program, contract, configIssues: [...(loaded.error === undefined ? [] : [loaded.error]), ...parsed.errors] };
}

function compilerIssues(fixture: CompilerFixture) {
  return [...fixture.configIssues, ...ts.getPreEmitDiagnostics(fixture.program, fixture.contract)].map((issue) => ({
    path: issue.file?.fileName.replaceAll("\\", "/"),
    line: issue.file !== undefined && issue.start !== undefined ? issue.file.getLineAndCharacterOfPosition(issue.start).line + 1 : undefined,
    message: ts.flattenDiagnosticMessageText(issue.messageText, "\n"),
  }));
}

describe("actual typed authored expectation contracts", () => {
  describe("accepted compiler fixture", () => {
    let fixture: CompilerFixture | undefined;
    beforeAll(() => {
      fixture = prepareCompilerFixture(ACCEPTED);
    });
    afterAll(() => {
      fixture = undefined;
    });
    it("accepts readonly diagnostics and complete optional end points with typed options", () => {
      if (fixture === undefined) throw new Error("The accepted compiler fixture did not complete.");
      expect(compilerIssues(fixture)).toEqual([]);
    });
  });
  describe("rejected compiler fixture", () => {
    let fixture: CompilerFixture | undefined;
    beforeAll(() => {
      fixture = prepareCompilerFixture(REJECTED);
    });
    afterAll(() => {
      fixture = undefined;
    });
    it("rejects malformed fields and half end points through the actual compiler and createRule", () => {
      if (fixture === undefined) throw new Error("The rejected compiler fixture did not complete.");
      const issues = compilerIssues(fixture);
      const rejectedLines = REJECTED.split("\n").flatMap((line, index) => line.includes("// ") ? [index + 1] : []);
      for (const line of rejectedLines) expect(issues.some((issue) => issue.path === CONTRACT_PATH && issue.line === line), REJECTED.split("\n")[line - 1]).toBe(true);
      expect(issues.filter((issue) => issue.path !== CONTRACT_PATH || issue.line === undefined || !rejectedLines.includes(issue.line))).toEqual([]);
    });
  });
});
