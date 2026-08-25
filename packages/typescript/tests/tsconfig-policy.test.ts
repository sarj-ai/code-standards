import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import ts from "typescript";

const TSCONFIG_ROOT = join(import.meta.dirname, "..", "..", "tsconfig");

function readJson(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(TSCONFIG_ROOT, name), "utf8")) as Record<string, unknown>;
}

function compilerDiagnosticCodes(file: string, sourceText: string): number[] {
  const configPath = join(TSCONFIG_ROOT, "base.json");
  const loaded = ts.readConfigFile(configPath, (path) => ts.sys.readFile(path));
  const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, TSCONFIG_ROOT);
  const fileName = join(TSCONFIG_ROOT, file);
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true);
  const host = ts.createCompilerHost({ ...parsed.options, noEmit: true });
  const getSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (requested, languageVersion, onError, shouldCreateNewSourceFile) =>
    requested === fileName
      ? source
      : getSourceFile(requested, languageVersion, onError, shouldCreateNewSourceFile);
  host.fileExists = (requested) => requested === fileName || ts.sys.fileExists(requested);
  host.readFile = (requested) =>
    requested === fileName ? source.text : ts.sys.readFile(requested);
  const program = ts.createProgram([fileName], { ...parsed.options, noEmit: true }, host);
  return ts.getPreEmitDiagnostics(program).map((diagnostic) => diagnostic.code);
}

describe("shared TypeScript compiler policy", () => {
  it("keeps the complete strict policy in base.json", () => {
    const base = readJson("base.json");
    expect(base.compilerOptions).toMatchObject({
      alwaysStrict: true,
      erasableSyntaxOnly: true,
      exactOptionalPropertyTypes: true,
      isolatedDeclarations: true,
      isolatedModules: true,
      noFallthroughCasesInSwitch: true,
      noEmitOnError: true,
      noImplicitAny: true,
      noImplicitOverride: true,
      noImplicitReturns: true,
      noImplicitThis: true,
      noPropertyAccessFromIndexSignature: true,
      noUncheckedIndexedAccess: true,
      noUncheckedSideEffectImports: true,
      skipLibCheck: false,
      strict: true,
      strictBindCallApply: true,
      strictBuiltinIteratorReturn: true,
      strictFunctionTypes: true,
      strictNullChecks: true,
      strictPropertyInitialization: true,
      useUnknownInCatchVariables: true,
      verbatimModuleSyntax: true,
    });
  });

  it("keeps strict.json as a compatibility alias without weaker overrides", () => {
    expect(readJson("strict.json")).toEqual({
      $schema: "https://json.schemastore.org/tsconfig",
      extends: "./base.json",
    });
  });

  it("rejects parameter properties through the compiler policy", () => {
    expect(compilerDiagnosticCodes(
      "parameter-property.ts",
      "class Session { constructor(public token: string) {} }",
    )).toContain(1294);
  });

  it("requires type-only exports through the compiler policy", () => {
    expect(compilerDiagnosticCodes(
      "type-export.ts",
      "interface User { readonly id: string }\nexport { User };",
    )).toContain(1205);
  });
});
