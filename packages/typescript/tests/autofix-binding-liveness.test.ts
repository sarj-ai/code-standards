import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as parser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { RULES } from "../src/index.js";

interface Example {
  readonly name: string;
  readonly rule: keyof typeof RULES;
  readonly source: string;
  readonly expected: string;
  readonly naive?: string;
  readonly filename?: string;
  readonly rules?: readonly (keyof typeof RULES)[];
}

const ZOD = 'import { z } from "zod"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }';
const CRYPTO = 'import { createHash, hash } from "node:crypto"; export const seed = hash("sha256", "seed", "hex"); export const digest = createHash("sha256").update("value").digest("hex");';
const CRYPTO_FIXED = CRYPTO.replace('createHash("sha256").update("value").digest("hex")', 'hash("sha256", "value", "hex")');
const MOCK = 'import type { Mock } from "vitest"; declare const value: unknown; const fake = value as Mock;';
const TEST_DOUBLE = 'import { vi } from "vitest"; interface Client { read(): string } const client = { read: vi.fn() } as unknown as Client;';
const BROAD = 'export {}; type Opaque = unknown; function read(value: { id: string }): Opaque { return value; }';
const KNOWN = 'export {}; type Opaque = unknown; declare const tool: { id: string }; const fields: Opaque = tool;';
const PREDICATE = 'export {}; type Numeric = number; function positive(value: unknown): value is Numeric { return typeof value === "number" && value > 0; }';
const EXAMPLES: readonly Example[] = [
  {name: "Zod sole return type stays manual", rule: "prefer-zod-parse-output-type", source: ZOD, expected: ZOD, naive: ZOD.replace(": ParsedRow", ": z.output<typeof RowSchema>")},
  {name: "Zod exported type witness survives the actual fix", rule: "prefer-zod-parse-output-type", source: `${ZOD} export type Kept = ParsedRow;`, expected: `${ZOD.replace(": ParsedRow", ": z.output<typeof RowSchema>")} export type Kept = ParsedRow;`},
  {name: "crypto sole runtime factory use stays manual", rule: "prefer-node-crypto-hash", source: CRYPTO, expected: CRYPTO, naive: CRYPTO_FIXED},
  {name: "crypto independent streaming call survives the actual fix", rule: "prefer-node-crypto-hash", source: `${CRYPTO} export const streaming = createHash("sha256");`, expected: `${CRYPTO_FIXED} export const streaming = createHash("sha256");`},
  {name: "Mock sole imported type use stays manual", rule: "no-unsafe-mock-casting", source: MOCK, expected: MOCK, naive: MOCK.replace("value as Mock", "value")},
  {name: "Mock exported type witness survives the actual fix", rule: "no-unsafe-mock-casting", source: `${MOCK} export type Kept = Mock;`, expected: `${MOCK.replace("value as Mock", "value")} export type Kept = Mock;`},
  {name: "test-double sole Client type stays manual", rule: "no-unsafe-test-double-cast", filename: "service.test.ts", source: TEST_DOUBLE, expected: TEST_DOUBLE, naive: TEST_DOUBLE.replace(" as unknown as Client", "")},
  {name: "test-double exported Client use survives the actual fix", rule: "no-unsafe-test-double-cast", filename: "service.test.ts", source: `${TEST_DOUBLE} export type Kept = Client;`, expected: `${TEST_DOUBLE.replace(" as unknown as Client", "")} export type Kept = Client;`},
  {name: "broad return sole alias stays manual", rule: "no-broad-return-type", source: BROAD, expected: BROAD, naive: BROAD.replace(": Opaque", "")},
  {name: "broad return exported type witness survives the actual fix", rule: "no-broad-return-type", source: `${BROAD} export type Kept = Opaque;`, expected: `${BROAD.replace(": Opaque", "")} export type Kept = Opaque;`},
  {name: "local widening sole alias stays manual", rule: "no-known-value-widening", source: KNOWN, expected: KNOWN, naive: KNOWN.replace(": Opaque", "")},
  {name: "predicate sole alias stays manual", rule: "no-partial-type-predicate", source: PREDICATE, expected: PREDICATE, naive: PREDICATE.replace("value is Numeric", "boolean")},
];

/** Use the actual imported compiler implementation, independently of the ESLint fix renderer. */
function nativeDiagnostics(filename: string): readonly string[] {
  const options: ts.CompilerOptions = {strict: true, target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, types: ["node"], typeRoots: [join(dirname(dirname(filename)), "node_modules", "@types")],
    noEmit: true, noUnusedLocals: true, skipLibCheck: true};
  const host = ts.createCompilerHost(options);
  host.getCurrentDirectory = () => dirname(dirname(filename));
  const program = ts.createProgram([filename], options, host);
  const diagnostics = ts.getPreEmitDiagnostics(program);
  expect(diagnostics.filter((diagnostic) => [2307, 2688, 2591].includes(diagnostic.code))).toEqual([]);
  return diagnostics.map((diagnostic) =>
    `${diagnostic.code}:${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`).sort();
}

function configuration(root: string, names: readonly (keyof typeof RULES)[]): Linter.Config {
  return {files: ["**/*.ts"], languageOptions: {parser, parserOptions: {project: join(root, "tsconfig.json"), tsconfigRootDir: root, disallowAutomaticSingleRunInference: true}},
    plugins: {sarj: {rules: Object.fromEntries(names.map((name) => [name, RULES[name] as unknown as Rule.RuleModule]))}},
    rules: Object.fromEntries(names.map((name) => [`sarj/${name}`, "error" as const]))};
}

async function check(example: Example): Promise<void> {
  const root = await mkdtemp(join(tmpdir(), "sarj-binding-liveness-"));
  const filename = join(root, "src", example.filename ?? "owner.ts");
  try {
    await mkdir(dirname(filename));
    await symlink(fileURLToPath(new URL("../node_modules", import.meta.url)), join(root, "node_modules"));
    await writeFile(join(root, "tsconfig.json"), JSON.stringify({compilerOptions: {strict: true, target: "ESNext", module: "ESNext", moduleResolution: "Bundler", types: ["node"], skipLibCheck: true}, include: ["src/*.ts"]}));
    await writeFile(filename, example.source);
    const before = nativeDiagnostics(filename);
    const config = configuration(root, example.rules ?? [example.rule]);
    const linter = new Linter({cwd: root});
    const messages = linter.verify(example.source, config, {filename});
    expect(new Set(messages.map((message) => message.ruleId))).toEqual(new Set((example.rules ?? [example.rule]).map((name) => `sarj/${name}`)));
    expect(messages.every((message) => !message.fatal && message.ruleId?.startsWith("sarj/") === true)).toBe(true);
    const actual = linter.verifyAndFix(example.source, config, {filename});
    expect(actual.output).toBe(example.expected);
    expect(actual.fixed).toBe(example.expected !== example.source);
    if (example.expected === example.source) expect(actual.messages).toEqual(messages);
    else expect(actual.messages).toEqual([]);
    await writeFile(filename, actual.output);
    expect(nativeDiagnostics(filename)).toEqual(before);
    parser.clearCaches();
    const second = linter.verifyAndFix(actual.output, config, {filename});
    expect(second.fixed).toBe(false);
    expect(second.output).toBe(actual.output);
    expect(second.messages).toEqual(actual.messages);
    if (example.naive !== undefined) {
      await writeFile(filename, example.naive);
      const changed = nativeDiagnostics(filename);
      expect(changed).not.toEqual(before);
      expect(changed.some((message) => /^(?:6133|6196):/u.test(message) && !before.includes(message))).toBe(true);
    }
  } finally {
    parser.clearCaches();
    await rm(root, {recursive: true, force: true});
  }
}

describe("actual autofixes preserve named-binding liveness under the compiler", () => {
  it.each(EXAMPLES)("$name", check);
  it("does not let simultaneous return, variable and predicate erasures witness each other", async () => {
    const source = `${BROAD} declare const tool: { id: string }; const fields: Opaque = tool; type Numeric = number; function positive(value: unknown): value is Numeric { return typeof value === "number" && value > 0; } function contradictory(value: unknown): value is Numeric { return typeof value === "string"; }`;
    await check({name: "mutual annotation witnesses", rule: "no-broad-return-type", source, expected: source,
      rules: ["no-broad-return-type", "no-known-value-widening", "no-partial-type-predicate", "no-contradictory-type-predicate"],
      naive: source.replace(": Opaque", "").replace(": Opaque", "").replaceAll("value is Numeric", "boolean")});
  });
  it("does not let a Mock assertion and consumer union preserve each other's removed types", async () => {
    const source = 'import type { Mock } from "vitest"; interface Animal { readonly name: string } interface Dog extends Animal { readonly email: string } const account = {name: "Ada", email: "a"}; function label(value: Dog | Animal): string { return value.name; } label(account); declare const raw: unknown; const fake = raw as Mock<() => Dog>;';
    await check({name: "cross-rule assertion witness", rule: "no-redundant-consumer-union", source, expected: source,
      rules: ["no-redundant-consumer-union", "no-unsafe-mock-casting"],
      naive: source.replace("Dog | Animal", "Animal").replace("raw as Mock<() => Dog>", "raw")});
  });
});
