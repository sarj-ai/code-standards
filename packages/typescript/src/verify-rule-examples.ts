import { mkdtemp, mkdir, rm, writeFile, readFile, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";

import { createExampleParser } from "./create-example-parser.js";
import type { DiagnosticExpectation, DocumentedRule, ExampleFile, ExampleLocation, RuleExample } from "./rules/_docs.js";

export type { ExampleFile, RuleExample } from "./rules/_docs.js";

export type FixedSourceFormatter = (file: ExampleFile, example: RuleExample) => string | Promise<string>;

/** Execute all authored examples, including private regressions, in isolated projects. */
export async function verifyRuleExamples<Options extends readonly unknown[], MessageIds extends string>(
  rule: DocumentedRule<Options, MessageIds>,
  setup: { readonly installedDependencyRoot?: string; readonly formatFixedSource?: FixedSourceFormatter } = {},
): Promise<number> {
  const spec = rule.documentation;
  if (spec === undefined || !spec.publicExamples.some((item) => item.outcome === "match") ||
      !spec.publicExamples.some((item) => item.outcome === "no-match")) {
    throw new Error("rule requires documented public matching and non-matching examples");
  }
  const exampleParser = createExampleParser();
  try {
    for (const example of spec.examples) {
      const root = await mkdtemp(join(tmpdir(), "sarj-rule-example-"));
      try {
        for (const file of example.files) {
          const path = fixturePath(root, file.path);
          validateFixtureSyntax(example.id, file, path);
          await mkdir(dirname(path), { recursive: true });
          await writeFile(path, file.source);
        }
        for (const dependency of example.installedDependencies ?? []) {
          if (setup.installedDependencyRoot === undefined) throw new Error(`${example.id}: explicit installed dependency root is required`);
          const packageFile = fixturePath(resolve(setup.installedDependencyRoot), `node_modules/${dependency.module}/package.json`);
          const metadata: unknown = JSON.parse(await readFile(packageFile, "utf8"));
          if (typeof metadata !== "object" || metadata === null || !("name" in metadata) || !("version" in metadata) || metadata.name !== dependency.module || metadata.version !== dependency.version) throw new Error(`${example.id}: installed dependency identity/version mismatch for ${dependency.module}`);
          const destination = fixturePath(root, `node_modules/${dependency.module}`);
          await mkdir(dirname(destination), { recursive: true });
          await symlink(dirname(packageFile), destination, process.platform === "win32" ? "junction" : "dir");
        }
        const tsconfig = join(root, "tsconfig.json");
        if (!example.files.some((file) => file.path === "tsconfig.json")) {
          await writeFile(tsconfig, JSON.stringify({ compilerOptions: {
            target: "ESNext", module: "ESNext", moduleResolution: "Bundler", strict: true,
            allowJs: true, jsx: "preserve", noEmit: true,
          }, include: ["**/*"] }));
        }
        const ruleId = `@sarj/${spec.ruleId}`;
        const config: Linter.Config = {
          files: ["**/*.{ts,tsx,js,jsx,mts,cts,mjs,cjs}"],
          languageOptions: { parser: exampleParser, parserOptions: { project: tsconfig, tsconfigRootDir: root, disallowAutomaticSingleRunInference: true } },
          plugins: { "@sarj": { rules: { [spec.ruleId]: rule as unknown as Rule.RuleModule } } },
          rules: { [ruleId]: ["error", ...(example.ruleOptions ?? rule.defaultOptions ?? [])] },
        };
        await verifyExample(new Linter({ cwd: root }), config, example, root, ruleId, setup.formatFixedSource);
      } finally {
        parser.clearCaches();
        await rm(root, { recursive: true, force: true });
      }
    }
  } finally {
    exampleParser.clear();
  }
  return spec.examples.length;
}

function fixturePath(root: string, path: string): string {
  const resolved = resolve(root, path);
  if (!resolved.startsWith(root + sep)) throw new Error(`unsafe example path: ${path}`);
  return resolved;
}

function validateFixtureSyntax(exampleId: string, file: ExampleFile, path: string): void {
  if (!/\.[cm]?[jt]sx?$/u.test(file.path)) return;
  try {
    parser.parse(file.source, { filePath: path });
  } catch (error) {
    throw new Error(`${exampleId}: invalid fixture ${file.path}`, { cause: error });
  }
}

async function verifyExample(linter: Linter, config: Linter.Config, example: RuleExample, root: string, ruleId: string, formatFixedSource?: FixedSourceFormatter): Promise<void> {
  const focus = example.files.find((file) => file.path === example.focusPath);
  if (focus === undefined) throw new Error(`${example.id}: focus file is missing`);
  const filename = fixturePath(root, focus.path);
  const messages = linter.verify(focus.source, config, { filename });
  if (messages.some((message) => message.fatal || message.ruleId !== ruleId)) {
    throw new Error(`${example.id}: invalid fixture: ${messages.map((message) => message.message).join("; ")}`);
  }
  const lines = linter.getSourceCode().lines;
  if (messages.some((message) => !physicalDiagnosticLocation(message, lines))) {
    throw new Error(`${example.id}: invalid diagnostic location`);
  }
  const locations = messages.map((message) => JSON.stringify([
    message.ruleId, message.messageId ?? message.message,
    message.line, message.column, message.endLine, message.endColumn,
  ]));
  if (new Set(locations).size !== locations.length) throw new Error(`${example.id}: duplicate diagnostic`);
  if (messages.length !== example.expectedCount) {
    throw new Error(`${example.id}: expected ${example.expectedCount} findings, received ${messages.length}`);
  }
  if (example.expectedDiagnostics !== undefined) {
    verifyExpectedDiagnostics(example, messages, focus.source, lines);
  }
  for (const expected of example.fixedFiles ?? []) {
    const input = example.files.find((file) => file.path === expected.path);
    if (input === undefined) throw new Error(`${example.id}: fixed file has no original`);
    const options = { filename: fixturePath(root, input.path) };
    const fixed = linter.verifyAndFix(input.source, config, options);
    if (formatFixedSource === undefined && fixed.output !== expected.source) throw new Error(`${example.id}: unexpected fixed source`);
    await writeFile(options.filename, fixed.output);
    const repeated = linter.verifyAndFix(fixed.output, config, options);
    if (repeated.fixed || repeated.output !== fixed.output || repeated.messages.length > 0) {
      throw new Error(`${example.id}: fix is not clean and idempotent`);
    }
    if (formatFixedSource !== undefined &&
        await formatFixedSource({ path: input.path, source: fixed.output }, example) !== expected.source) {
      throw new Error(`${example.id}: unexpected fixed source`);
    }
  }
}

function verifyExpectedDiagnostics(example: RuleExample, messages: readonly Linter.LintMessage[], source: string, lines: readonly string[]): void {
  const expectations = example.expectedDiagnostics ?? [];
  if (expectations.some((item) => !physicalExpectedLocation(item.location, lines))) {
    throw new Error(`${example.id}: invalid expected diagnostic location`);
  }
  const expected = expectations.map(expectedDiagnosticKey).sort();
  const actual = messages.map((message) => JSON.stringify([
    message.messageId, message.message,
    [message.line, message.column, message.endLine, message.endColumn],
    message.fix !== undefined,
    (message.suggestions ?? []).map((suggestion) => [
      suggestion.messageId, applySuggestion(source, suggestion.fix, example.id),
    ]),
  ])).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${example.id}: unexpected diagnostics\nexpected: ${JSON.stringify(expected)}\nreceived: ${JSON.stringify(actual)}`);
  }
}

function expectedDiagnosticKey(expected: DiagnosticExpectation): string {
  return JSON.stringify([
    expected.messageId, expected.message,
    [expected.location.line, expected.location.column, expected.location.end?.line, expected.location.end?.column],
    expected.automaticFix,
    expected.suggestions.map((suggestion) => [suggestion.messageId, suggestion.output]),
  ]);
}

function applySuggestion(source: string, fix: Rule.Fix, exampleId: string): string {
  const bom = source.startsWith("\uFEFF") ? "\uFEFF" : "";
  const text = bom === "" ? source : source.slice(1);
  const [start, end] = fix.range;
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end ||
      start < (bom === "" ? 0 : -1) || end < 0 || end > text.length) {
    throw new Error(`${exampleId}: invalid suggestion edit range`);
  }
  // ESLint's normalized edit offsets exclude the input BOM; replacing it uses [-1, 0].
  const prefix = (start < 0 && end >= 0) || (start === 0 && fix.text.startsWith("\uFEFF")) ? "" : bom;
  return prefix + text.slice(0, Math.max(0, start)) + fix.text + text.slice(end);
}

function physicalExpectedLocation(location: ExampleLocation, lines: readonly string[]): boolean {
  if (!physicalPosition(lines, location.line, location.column)) return false;
  if (location.end === undefined) return true;
  return physicalPosition(lines, location.end.line, location.end.column) &&
    (location.end.line > location.line || (location.end.line === location.line && location.end.column >= location.column));
}

function physicalDiagnosticLocation(message: Linter.LintMessage, lines: readonly string[]): boolean {
  if (!physicalPosition(lines, message.line, message.column)) return false;
  if (message.endLine === undefined && message.endColumn === undefined) return true;
  if (!physicalPosition(lines, message.endLine, message.endColumn)) return false;
  return message.endLine !== undefined && message.endColumn !== undefined &&
    (message.endLine > message.line || (message.endLine === message.line && message.endColumn >= message.column));
}

/** ESLint columns are one-based UTF-16 offsets; an exclusive EOF position is valid. */
function physicalPosition(lines: readonly string[], line: number | undefined, column: number | undefined): boolean {
  if (line === undefined || column === undefined || !Number.isInteger(line) || !Number.isInteger(column)) return false;
  const text = lines[line - 1];
  return text !== undefined && column >= 1 && column <= text.length + 1;
}
