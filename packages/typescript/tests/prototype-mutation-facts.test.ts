import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";
import * as ts from "typescript";
import { expect, it, vi } from "vitest";

import rule from "../src/rules/require-explicit-contract-implementation.js";

vi.mock("typescript", async (importOriginal) => {
  const actual = await importOriginal<typeof import("typescript")>();
  return {
    ...actual,
    forEachChild: vi.fn(actual.forEachChild),
  };
});

function nominalProgram(mutation = ""): {
  readonly code: string;
  readonly filename: string;
  readonly program: ts.Program;
  readonly source: ts.SourceFile;
} {
  const filename = join(process.cwd(), "src", "prototype-cache-fixture.ts").replaceAll("\\", "/");
  const code = [
    "export {};",
    "abstract class Contract { abstract operation(): void }",
    "class Consumer { constructor(readonly dependency: Contract) { if (!(dependency instanceof Contract)) throw new TypeError(); } }",
    "class Substitute { operation(): void {} }",
    ...Array.from({ length: 8 }, () => "new Consumer(new Substitute());"),
    mutation,
  ].join("\n");
  const source = ts.createSourceFile(
    filename,
    code,
    ts.ScriptTarget.Latest,
    true,
  );
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    noLib: true,
    strict: true,
    noEmit: true,
  };
  const host: ts.CompilerHost = {
    ...ts.createCompilerHost(options, true),
    getSourceFile: (path) => (path.replaceAll("\\", "/") === filename ? source : undefined),
    fileExists: (path) => path.replaceAll("\\", "/") === filename,
    readFile: (path) => (path.replaceAll("\\", "/") === filename ? code : undefined),
  };
  const program = ts.createProgram([filename], options, host);
  return { code, filename, program, source };
}

function lint(fixture: ReturnType<typeof nominalProgram>): Linter.LintMessage[] {
  return new Linter().verify(
    fixture.code,
    [
      {
        files: ["**/*.ts"],
        languageOptions: {
          parser,
          parserOptions: {
            programs: [fixture.program],
            disallowAutomaticSingleRunInference: true,
          },
        },
        plugins: {
          local: {
            rules: {
              nominal: rule as unknown as Rule.RuleModule,
            },
          },
        },
        rules: { "local/nominal": "error" },
      },
    ],
    { filename: fixture.filename },
  );
}

function sourceWalks(source: ts.SourceFile): number {
  return vi.mocked(ts.forEachChild).mock.calls.filter(([node]) => node === source)
    .length;
}

it("reuses the negative safety fact across candidates and repeated analysis", () => {
  const fixture = nominalProgram();
  vi.mocked(ts.forEachChild).mockClear();
  const first = lint(fixture);
  expect(first).toHaveLength(8);
  expect(first.map((message) => message.messageId)).toEqual(
    Array.from({ length: 8 }, () => "declareActualContract"),
  );
  expect(first.every((message) => message.fix === undefined)).toBe(true);

  expect(sourceWalks(fixture.source)).toBe(2);
  expect(lint(fixture)).toEqual(first);
  expect(sourceWalks(fixture.source)).toBe(2);
});

it("reuses a positive mutation fact without relaxing the exclusion", () => {
  const fixture = nominalProgram(
    "Object.setPrototypeOf(Substitute.prototype, Contract.prototype);",
  );
  vi.mocked(ts.forEachChild).mockClear();
  expect(lint(fixture)).toEqual([]);
  expect(sourceWalks(fixture.source)).toBe(1);
  expect(lint(fixture)).toEqual([]);
  expect(sourceWalks(fixture.source)).toBe(1);
});

it("checks replacement source identities at the same filename for new mutations", () => {
  const original = nominalProgram();
  const changed = nominalProgram(
    "Object.setPrototypeOf(Substitute.prototype, Contract.prototype);",
  );
  expect(changed.filename).toBe(original.filename);
  expect(changed.source).not.toBe(original.source);
  vi.mocked(ts.forEachChild).mockClear();
  const findings = lint(original);
  expect(findings).toHaveLength(8);
  expect(lint(changed)).toEqual([]);
  expect(sourceWalks(original.source)).toBe(2);
  expect(sourceWalks(changed.source)).toBe(1);
  expect(lint(original)).toEqual(findings);
  expect(sourceWalks(original.source)).toBe(2);
});
