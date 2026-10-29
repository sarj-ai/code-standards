import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { beforeAll, expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));
const INDEX = resolve(PACKAGE_ROOT, "src/index.ts");
const SOURCE = readFileSync(INDEX, "utf8");
const SOURCE_FILES = new Map<string, ts.SourceFile>();

interface PolicyCase {
  readonly name: string;
  readonly rule: string;
  readonly setting?: string;
  readonly key?: string;
  readonly accepted: boolean;
}

interface Mutation {
  readonly source: string;
  readonly start: number;
  readonly end: number;
}

const CASES: readonly PolicyCase[] = [
  {
    name: "valid boolean and list options",
    rule: "@sarj/prefer-logical-tailwind-utilities",
    setting: '["error", "both", () => [{ enabled: true, checkInsets: true, allowUtilities: ["left-0"] }] as const]',
    accepted: true,
  },
  {
    name: "valid numeric option",
    rule: "@sarj/no-fat-try-blocks",
    setting: '["error", "both", () => [{ max: 7 }] as const]',
    accepted: true,
  },
  { name: "unknown rule key", rule: "@sarj/no-enum", key: "@sarj/no-such-rule", accepted: false },
  {
    name: "string in boolean option",
    rule: "@sarj/prefer-logical-tailwind-utilities",
    setting: '["error", "both", () => [{ enabled: "false" }] as const]',
    accepted: false,
  },
  {
    name: "misspelled option",
    rule: "@sarj/prefer-logical-tailwind-utilities",
    setting: '["error", "both", () => [{ enabld: false }] as const]',
    accepted: false,
  },
  {
    name: "unsupported Zod version",
    rule: "@sarj/prefer-multi-value-zod-literal",
    setting: '["error", "both", () => [{ zodMajorVersion: 3 }] as const]',
    accepted: false,
  },
  {
    name: "extra option argument",
    rule: "@sarj/prefer-logical-tailwind-utilities",
    setting: '["error", "both", () => [{ enabled: false }, { enabled: true }] as const]',
    accepted: false,
  },
  {
    name: "options on optionless rule",
    rule: "@sarj/no-enum",
    setting: '["error", "strict", () => [{ enabled: true }] as const]',
    accepted: false,
  },
  { name: "invalid severity", rule: "@sarj/no-enum", setting: '["warning", "strict"]', accepted: false },
  { name: "invalid membership", rule: "@sarj/no-enum", setting: '["error", "strictest"]', accepted: false },
];

let control: ts.Program | undefined;

beforeAll(() => {
  expect(ts.version).toBe("6.0.3");
  control = compile(SOURCE);
  expect(messages(policyDiagnostics(control))).toEqual([]);
});

it.each(CASES)("checks $name at the actual policy declaration", (example) => {
  if (control === undefined) throw new Error("The real policy control did not compile.");
  const mutation = mutatePolicy(example);
  const program = compile(mutation.source, control);
  expect(program.getSourceFile(INDEX)?.text).toBe(mutation.source);
  expect(program.getSourceFile(INDEX)).not.toBe(control.getSourceFile(INDEX));
  const diagnostics = policyDiagnostics(program);
  if (example.accepted) {
    expect(messages(diagnostics)).toEqual([]);
    return;
  }
  expect(diagnostics.length).toBeGreaterThan(0);
  expect(diagnostics.some((diagnostic) => diagnostic.file?.fileName === INDEX
    && diagnostic.start !== undefined
    && diagnostic.start >= mutation.start
    && diagnostic.start < mutation.end), messages(diagnostics).join("\n")).toBe(true);
});

function policyDiagnostics(program: ts.Program): readonly ts.Diagnostic[] {
  const index = program.getSourceFile(INDEX);
  if (index === undefined) throw new Error("The actual policy source was not loaded.");
  return ts.getPreEmitDiagnostics(program, index);
}

function compile(source: string, oldProgram?: ts.Program): ts.Program {
  if (oldProgram === undefined) SOURCE_FILES.clear();
  const parsed = ts.getParsedCommandLineOfConfigFile(
    resolve(PACKAGE_ROOT, "tsconfig.json"),
    { noEmit: true, incremental: false },
    {
      ...ts.sys,
      onUnRecoverableConfigFileDiagnostic: (diagnostic) => {
        throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"));
      },
    },
  );
  if (parsed === undefined || parsed.errors.length > 0) {
    throw new Error("The actual TypeScript package configuration could not be loaded.");
  }
  if (!parsed.fileNames.some((filename) => resolve(filename) === INDEX)) {
    throw new Error("The actual policy entrypoint is not part of the package project.");
  }
  const roots = [INDEX, ...parsed.fileNames.filter((filename) => filename.endsWith(".d.ts")
    || filename.endsWith(".d.mts") || filename.endsWith(".d.cts"))];
  const host = ts.createCompilerHost(parsed.options);
  const readFile = host.readFile.bind(host);
  host.readFile = (filename) => resolve(filename) === INDEX ? source : readFile(filename);
  const getSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (filename, languageVersionOrOptions, onError, shouldCreateNewSourceFile) => {
    const path = resolve(filename);
    const previous = SOURCE_FILES.get(path);
    if (oldProgram !== undefined && path !== INDEX && !shouldCreateNewSourceFile
      && previous !== undefined && readFile(filename) === previous.text) {
      return previous;
    }
    const current = getSourceFile(filename, languageVersionOrOptions, onError, shouldCreateNewSourceFile);
    if (path !== INDEX && current !== undefined) SOURCE_FILES.set(path, current);
    return current;
  };
  return ts.createProgram(roots, parsed.options, host, oldProgram);
}

function mutatePolicy(example: PolicyCase): Mutation {
  const tree = ts.createSourceFile(INDEX, SOURCE, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const declaration = tree.statements
    .filter(ts.isVariableStatement)
    .flatMap((statement) => [...statement.declarationList.declarations])
    .find((statement) => ts.isIdentifier(statement.name) && statement.name.text === "RULE_POLICY");
  const initializer = declaration?.initializer;
  if (initializer === undefined || !ts.isSatisfiesExpression(initializer)
    || !ts.isAsExpression(initializer.expression)
    || !ts.isObjectLiteralExpression(initializer.expression.expression)) {
    throw new Error("The actual preset policy table was not found.");
  }
  const property = initializer.expression.expression.properties
    .filter(ts.isPropertyAssignment)
    .find((entry) => ts.isStringLiteral(entry.name) && entry.name.text === example.rule);
  if (property === undefined) throw new Error("The selected real policy entry was not found.");
  const target = example.key === undefined ? property.initializer : property.name;
  const replacement = example.key === undefined ? example.setting : JSON.stringify(example.key);
  if (replacement === undefined) throw new Error("The policy case has no mutation.");
  const start = target.getStart(tree);
  return {
    source: SOURCE.slice(0, start) + replacement + SOURCE.slice(target.getEnd()),
    start,
    end: start + replacement.length,
  };
}

function messages(diagnostics: readonly ts.Diagnostic[]): readonly string[] {
  return diagnostics.map((diagnostic) => `${diagnostic.code}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`);
}
