import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { describe, expect, it } from "vitest";
import { z } from "zod";

import { RULES } from "../src/index.js";
import type { ExampleFile } from "../src/rules/_docs.js";
import { verifyRuleExamples } from "../src/verify-rule-examples.js";

interface DisplayExample {
  readonly id: string;
  readonly focusPath: string;
  readonly expectedCount: number;
  readonly files: readonly ExampleFile[];
  readonly fixedFiles: readonly ExampleFile[];
}

interface DisplayCatalog {
  readonly rules: Readonly<Record<string, { readonly examples: readonly DisplayExample[] }>>;
}

const DISPLAY = JSON.parse(readFileSync(new URL("../../../apps/docs/src/generated/formatted-code.v1.json", import.meta.url), "utf8")) as DisplayCatalog;
const DOCUMENTED_RULES = Object.entries(RULES).sort(([left], [right]) => left.localeCompare(right));
const SETUP = { installedDependencyRoot: fileURLToPath(new URL("../", import.meta.url)) };

describe("every shipped rule's authored examples", () => {
  it.each(DOCUMENTED_RULES)("%s executes its matching, nonmatching and private examples", async (_id, rule) => {
    await expect(verifyRuleExamples(rule, SETUP)).resolves.toBe(rule.documentation?.examples.length);
  });
});

describe("every shipped rule's displayed examples", () => {
  it.each(DOCUMENTED_RULES)("%s preserves behavior after documentation formatting", async (id, rule) => {
    const spec = rule.documentation;
    if (spec === undefined) throw new Error(`${id}: missing source-owned examples`);
    const display = DISPLAY.rules[`eslint:${id}`];
    if (display === undefined) throw new Error(`${id}: missing displayed examples`);
    const examples = spec.examples.filter((example) => example.public === true).map((example) => {
      const formatted = display.examples.find((item) => item.id === example.id);
      if (formatted === undefined) throw new Error(`${id}:${example.id}: missing displayed example`);
      expect(formatted.focusPath).toBe(example.focusPath);
      expect(formatted.expectedCount).toBe(example.expectedCount);
      expect(formatted.files.map((file) => file.path)).toEqual(example.files.map((file) => file.path));
      expect(formatted.fixedFiles.map((file) => file.path)).toEqual((example.fixedFiles ?? []).map((file) => file.path));
      return { ...example, files: formatted.files, fixedFiles: formatted.fixedFiles };
    });
    await expect(verifyRuleExamples({ ...rule, documentation: { ...spec, examples } }, SETUP)).resolves.toBe(examples.length);
  });
});

function focusSource(ruleId: keyof typeof RULES, exampleId: string): string {
  const example = RULES[ruleId].documentation?.examples.find((item) => item.id === exampleId);
  const source = example?.files.find((file) => file.path === example.focusPath)?.source;
  if (source === undefined) throw new Error(`${ruleId}:${exampleId}: missing source`);
  return source;
}

function execute(source: string, expression: string, globals: Readonly<Record<string, unknown>> = {}): unknown {
  const compiled = ts.transpileModule(`${source}\n${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } });
  return runInNewContext(compiled.outputText, { exports: {}, ...globals });
}

it("the switch remediation preserves every documented branch and the fallback", () => {
  const inputs = '["a", "b", "c", "missing"]';
  const before = execute(focusSource("prefer-switch-for-repeated-equality", "repeated-equality"), `JSON.stringify(${inputs}.map(render));`);
  const after = execute(focusSource("prefer-switch-for-repeated-equality", "switch-dispatch"), `JSON.stringify(${inputs}.map(render));`);
  expect(before).toBe('["alpha","beta","gamma","unknown"]');
  expect(after).toBe(before);
});

it("the structural comparator remediation ignores insertion order and retains value differences", () => {
  const source = focusSource("no-json-stringify-object-equality", "domain-comparator");
  expect(execute(source, "same;")).toBe(true);
  expect(execute(source, "sameRecord({ id: '1', state: 'ready' }, { id: '1', state: 'failed' });")).toBe(false);
  expect(execute(focusSource("no-json-stringify-object-equality", "serialized-object-equality"), "same;")).toBe(false);
});

const ZOD_GLOBALS = { require: (specifier: string): { readonly z: typeof z } => {
  if (specifier !== "zod") throw new Error(`Unexpected example dependency: ${specifier}`);
  return { z };
} };

it("hoisting the documented refinement preserves acceptance, rejection and trimming", () => {
  const expression = "JSON.stringify([1, ' Ada ', '', 'x'.repeat(129)].map(value => { try { return { accepted: true, value: parse(value) }; } catch { return { accepted: false }; } }));";
  const before = execute(focusSource("prefer-module-level-refined-schema", "local-refinement"), expression, ZOD_GLOBALS);
  const after = execute(focusSource("prefer-module-level-refined-schema", "module-refinement"), expression, ZOD_GLOBALS);
  expect(before).toBe('[{"accepted":false},{"accepted":true,"value":"Ada"},{"accepted":false},{"accepted":false}]');
  expect(after).toBe(before);
});

it("the documented payload validator validates actual response data", async () => {
  const source = focusSource("prefer-schema-for-api-payload", "validated-payload");
  await expect(execute(source, "load(new Response(JSON.stringify({ id: 'user-1' })));", { ...ZOD_GLOBALS, Response })).resolves.toBe("user-1");
  await expect(execute(source, "load(new Response(JSON.stringify({ id: 1 })));", { ...ZOD_GLOBALS, Response })).rejects.toThrow();
});

it("removing declaration commentary preserves the enum's public values", () => {
  const before = execute(focusSource("no-declaration-comment-wall", "restated-enum-members"), "JSON.stringify(Status);");
  const after = execute(focusSource("no-declaration-comment-wall", "uncommented-members"), "JSON.stringify(Status);");
  expect(after).toBe(before);
});

it("removing member commentary preserves fields, types and optionality", () => {
  const fields = (source: string): readonly object[] => {
    const tree = ts.createSourceFile("example.ts", source, ts.ScriptTarget.Latest, true);
    const declaration = tree.statements.find(ts.isInterfaceDeclaration);
    if (declaration === undefined) throw new Error("Missing interface");
    return declaration.members.map((member) => ({
      name: member.name?.getText(tree),
      optional: ts.isPropertySignature(member) && member.questionToken !== undefined,
      type: ts.isPropertySignature(member) ? member.type?.getText(tree) : undefined,
    }));
  };
  expect(fields(focusSource("no-type-member-comment-wall", "uncommented-members"))).toEqual(fields(focusSource("no-type-member-comment-wall", "restated-type-members")));
});

it("the documented never helper makes an added union member a compiler error", () => {
  const codes = (source: string): readonly number[] => {
    const filename = "/sarj-example/render.ts";
    const options: ts.CompilerOptions = { noEmit: true, strict: true, target: ts.ScriptTarget.ES2022, types: [] };
    const host = ts.createCompilerHost(options);
    const original = host.getSourceFile.bind(host);
    host.getSourceFile = (path, ...args) => path === filename
      ? ts.createSourceFile(path, source, ts.ScriptTarget.ES2022, true)
      : original(path, ...args);
    const program = ts.createProgram([filename], options, host);
    return ts.getPreEmitDiagnostics(program).map((diagnostic) => diagnostic.code);
  };
  const source = focusSource("require-assert-never", "assert-never-default");
  expect(codes(source)).toEqual([]);
  expect(codes(source.replace("'a' | 'b'", "'a' | 'b' | 'c'"))).toContain(2345);
});
