/**
 * @fileoverview verify-rule-examples — run every authored example of a rule through Oxlint's RuleTester.
 *
 * Each example gets its own temporary project on disk (its files, a default
 * `tsconfig.json`, linked installed dependencies), so type-aware rules see the
 * same program they would in a repository. The focus file is linted with the
 * example's options; authored `fixedFiles` must equal the fixed source, which
 * must then leave nothing to report.
 */

import { AssertionError } from "node:assert";
import { mkdtemp, mkdir, rm, writeFile, readFile, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

import { parseSync } from "oxc-parser";
import { RuleTester } from "oxlint/plugins-dev";

import type { DocumentedRule } from "./catalog.js";
import type { DiagnosticExpectation, ExampleFile, RuleExample } from "./documentation.js";

export type { ExampleFile, RuleExample } from "./documentation.js";

export type FixedSourceFormatter = (file: ExampleFile, example: RuleExample) => string | Promise<string>;

interface Setup {
  readonly installedDependencyRoot?: string;
  readonly formatFixedSource?: FixedSourceFormatter;
}

// Never a fixed source, so RuleTester always reports the actual one.
const UNREACHABLE_OUTPUT = "\0sarj-rule-examples: actual fixed source\0";
const DEFAULT_TSCONFIG = JSON.stringify({ compilerOptions: {
  target: "ESNext", module: "ESNext", moduleResolution: "Bundler", strict: true,
  allowJs: true, jsx: "preserve", noEmit: true,
}, include: ["**/*"] });

/** Execute all authored examples, including private regressions, in isolated projects. */
export async function verifyRuleExamples(rule: DocumentedRule, setup: Setup = {}): Promise<number> {
  const spec = rule.documentation;
  if (!spec.publicExamples.some((item) => item.outcome === "match") ||
      !spec.publicExamples.some((item) => item.outcome === "no-match")) {
    throw new Error("rule requires documented public matching and non-matching examples");
  }
  for (const example of spec.examples) {
    const root = await mkdtemp(join(tmpdir(), "sarj-rule-example-"));
    try {
      await writeProject(root, example, setup);
      await verifyExample(rule, example, root, setup.formatFixedSource);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }
  return spec.examples.length;
}

async function writeProject(root: string, example: RuleExample, setup: Setup): Promise<void> {
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
    // eslint-disable-next-line @sarj/no-runtime-typeof -- This dependency-free package bootstrap verifies raw package identity before linking a fixture dependency.
    if (typeof metadata !== "object" || metadata === null || !("name" in metadata) || !("version" in metadata) || metadata.name !== dependency.module || metadata.version !== dependency.version) throw new Error(`${example.id}: installed dependency identity/version mismatch for ${dependency.module}`);
    const destination = fixturePath(root, `node_modules/${dependency.module}`);
    await mkdir(dirname(destination), { recursive: true });
    await symlink(dirname(packageFile), destination, process.platform === "win32" ? "junction" : "dir");
  }
  if (!example.files.some((file) => file.path === "tsconfig.json")) {
    await writeFile(join(root, "tsconfig.json"), DEFAULT_TSCONFIG);
  }
}

function fixturePath(root: string, path: string): string {
  const resolved = resolve(root, path);
  if (!resolved.startsWith(root + sep)) throw new Error(`unsafe example path: ${path}`);
  return resolved;
}

function validateFixtureSyntax(exampleId: string, file: ExampleFile, path: string): void {
  if (!/\.[cm]?[jt]sx?$/u.test(file.path)) return;
  const [error] = parseSync(path, file.source).errors;
  if (error !== undefined) throw new Error(`${exampleId}: invalid fixture ${file.path}: ${error.message}`);
}

async function verifyExample(rule: DocumentedRule, example: RuleExample, root: string, formatFixedSource?: FixedSourceFormatter): Promise<void> {
  const focus = example.files.find((file) => file.path === example.focusPath);
  if (focus === undefined) throw new Error(`${example.id}: focus file is missing`);
  const base: RuleTester.ValidTestCase = {
    code: focus.source,
    filename: fixturePath(root, focus.path),
    // Authored options are JSON data: the catalog publishes them.
    ...(example.ruleOptions !== undefined && { options: [...example.ruleOptions] as RuleTester.ValidTestCase["options"] & object }),
  };
  const name = rule.documentation.ruleId;
  // plugins-dev bundles its own copy of the @oxlint/plugins rule types, which TypeScript cannot relate to ours.
  const tested = rule as unknown as Parameters<RuleTester["run"]>[1];
  const tester = new RuleTester({ eslintCompat: true, cwd: root });
  if (example.expectedCount === 0) {
    run(example, () => { tester.run(name, tested, { valid: [base], invalid: [] }); });
    return;
  }
  const expected = example.expectedDiagnostics?.toSorted(byLocation);
  const fixed = actualFixedSource(example, () => {
    tester.run(name, tested, { valid: [], invalid: [{ ...base, errors: expected?.map(identity) ?? example.expectedCount, output: UNREACHABLE_OUTPUT, recursive: true }] });
  });
  if (expected !== undefined) {
    actualFixedSource(example, () => {
      tester.run(name, tested, { valid: [], invalid: [{ ...base, errors: expected.map(message), output: UNREACHABLE_OUTPUT, recursive: true }] });
    });
    if (expected.some((item) => item.automaticFix) !== (fixed !== focus.source)) {
      throw new Error(`${example.id}: automatic fix delivery differs from the expected diagnostics`);
    }
  }
  const expectedFixed = example.fixedFiles?.find((file) => file.path === focus.path);
  if (expectedFixed === undefined) return;
  if (formatFixedSource === undefined && fixed !== expectedFixed.source) throw new Error(`${example.id}: unexpected fixed source`);
  await writeFile(fixturePath(root, focus.path), fixed);
  run(example, () => { tester.run(name, tested, { valid: [{ ...base, code: fixed }], invalid: [] }); });
  if (formatFixedSource !== undefined && await formatFixedSource({ path: focus.path, source: fixed }, example) !== expectedFixed.source) {
    throw new Error(`${example.id}: unexpected fixed source`);
  }
}

function byLocation(left: DiagnosticExpectation, right: DiagnosticExpectation): number {
  const lines = left.location.line - right.location.line;
  return lines === 0 ? left.location.column - right.location.column : lines;
}

function location({ location: { line, column, end } }: DiagnosticExpectation): Pick<RuleTester.Error, "line" | "column" | "endLine" | "endColumn"> {
  return { line, column, endLine: end?.line, endColumn: end?.column };
}

function identity(expected: DiagnosticExpectation): RuleTester.Error {
  return {
    ...location(expected),
    messageId: expected.messageId,
    suggestions: expected.suggestions.map((suggestion) => ({ messageId: suggestion.messageId, output: suggestion.output })),
  };
}

function message(expected: DiagnosticExpectation): RuleTester.Error {
  return { ...location(expected), message: expected.message };
}

/** Run one RuleTester case synchronously, outside any test framework's describe/it. */
function run(example: RuleExample, body: () => void): void {
  const { describe, it } = RuleTester;
  RuleTester.describe = (_text, method) => { method(); };
  RuleTester.it = (_text, method) => { method(); };
  try {
    body();
  } catch (error) {
    throw new Error(`${example.id}: ${error instanceof Error ? error.message : String(error)}`, { cause: error });
  } finally {
    RuleTester.describe = describe;
    RuleTester.it = it;
  }
}

/** The source after all fixes, read from RuleTester's failed comparison with an unreachable output. */
function actualFixedSource(example: RuleExample, body: () => void): string {
  try {
    run(example, body);
  } catch (error) {
    const { cause } = error as Error;
    // eslint-disable-next-line @sarj/no-runtime-typeof -- AssertionError types its compared values as unknown.
    if (cause instanceof AssertionError && cause.expected === UNREACHABLE_OUTPUT && typeof cause.actual === "string") return cause.actual;
    throw error;
  }
  throw new Error(`${example.id}: RuleTester accepted an unreachable fixed source`);
}
