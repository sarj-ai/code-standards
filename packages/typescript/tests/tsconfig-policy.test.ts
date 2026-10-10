import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";

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

function nativeConfigSnapshot(configs: Readonly<Record<string, string>>) {
  const root = join(TSCONFIG_ROOT, "native-equivalence");
  const files = new Map(Object.entries(configs).map(([name, source]) => [resolve(root, name), source]));
  const parsed = ts.getParsedCommandLineOfConfigFile(resolve(root, "leaf/tsconfig.json"), {}, {
    useCaseSensitiveFileNames: true,
    getCurrentDirectory: () => root,
    fileExists: (file) => files.has(file),
    readFile: (file) => files.get(file),
    readDirectory: () => [],
    onUnRecoverableConfigFileDiagnostic: (diagnostic) => {
      throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"));
    },
  });
  if (parsed === undefined || parsed.errors.length > 0) {
    throw new Error(parsed?.errors.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")).join("\n") ?? "Config parsing failed");
  }
  return {
    // The edited syntax tree changes; native compiler and project semantics must not.
    options: { ...parsed.options, configFile: undefined },
    fileNames: parsed.fileNames,
    projectReferences: parsed.projectReferences,
    watchOptions: parsed.watchOptions,
    wildcardDirectories: parsed.wildcardDirectories,
    typeAcquisition: parsed.typeAcquisition,
    compileOnSave: parsed.compileOnSave,
    errors: parsed.errors,
  };
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

describe("native evidence for inherited boolean review", () => {
  it.each([
    { name: "an explicitly inherited literal", base: { strict: true }, child: { strict: true }, same: true },
    { name: "a genuine override", base: { strict: true }, child: { strict: false }, same: false },
    { name: "an implicit strict subflag default", base: { strict: true }, child: { strictNullChecks: true }, same: false },
  ])("compares the complete native result for $name", ({ base, child, same }) => {
    const inherited = {
      "base.json": JSON.stringify({ compilerOptions: { ...base, rootDir: "./shared-src", outDir: "./shared-dist", paths: { "@shared/*": ["./shared/*"] } } }),
      "leaf/source.ts": "export {};",
    };
    const leaf = { extends: "../base.json", files: ["source.ts"], references: [{ path: "../dependency" }] };
    const before = nativeConfigSnapshot({ ...inherited, "leaf/tsconfig.json": JSON.stringify({ ...leaf, compilerOptions: child }) });
    const after = nativeConfigSnapshot({ ...inherited, "leaf/tsconfig.json": JSON.stringify(leaf) });
    expect(isDeepStrictEqual(before, after)).toBe(same);
    expect(after.fileNames).toEqual(before.fileNames);
    expect(after.projectReferences).toEqual(before.projectReferences);
  });

  it("honors ordered multiple extends rather than selecting a convenient parent", () => {
    const inherited = {
      "first.json": '{ "compilerOptions": { "strict": true } }',
      "last.json": '{ "compilerOptions": { "strict": false } }',
      "leaf/source.ts": "export {};",
    };
    const leaf = { extends: ["../first.json", "../last.json"], files: ["source.ts"] };
    const before = nativeConfigSnapshot({ ...inherited, "leaf/tsconfig.json": JSON.stringify({ ...leaf, compilerOptions: { strict: true } }) });
    const after = nativeConfigSnapshot({ ...inherited, "leaf/tsconfig.json": JSON.stringify(leaf) });
    expect(before.options.strict).toBe(true);
    expect(after.options.strict).toBe(false);
  });

  it("rejects unresolved inheritance instead of treating matching errors as equivalence", () => {
    expect(() => nativeConfigSnapshot({ "leaf/tsconfig.json": '{ "extends": "../missing.json", "files": ["source.ts"] }' })).toThrow();
  });
});

it("preserves named record child contracts and isolated declaration emission", () => {
  const fileName = join(import.meta.dirname, "named-child-contract.ts");
  const sourceText = `
    import { z } from "zod";
    const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]);
    const ValueSchema: z.ZodDefault<z.ZodReadonly<z.ZodObject<{ id: z.ZodString }>>> = z.object({ id: z.string() }).readonly().default({ id: "default" });
    export const OriginalSchema: z.ZodRecord<z.ZodEnum<{ a: "a"; b: "b" }>, z.ZodDefault<z.ZodReadonly<z.ZodObject<{ id: z.ZodString }>>>> = z.record(KeySchema, ValueSchema);
    export const ReducedSchema: z.ZodRecord<typeof KeySchema, typeof ValueSchema> = z.record(KeySchema, ValueSchema);
    type Same<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
    type Assert<T extends true> = T;
    type InputStable = Assert<Same<z.input<typeof OriginalSchema>, z.input<typeof ReducedSchema>>>;
    type OutputStable = Assert<Same<z.output<typeof OriginalSchema>, z.output<typeof ReducedSchema>>>;
    type DefaultInput = Assert<Same<z.input<typeof ValueSchema>, Readonly<{ id: string }> | undefined>>;
    type ReadonlyOutput = Assert<Same<z.output<typeof ValueSchema>, Readonly<{ id: string }>>>;
  `;
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.NodeNext,
    strict: true,
    isolatedDeclarations: true,
    declaration: true,
    emitDeclarationOnly: true,
    noEmitOnError: true,
  };
  const host = ts.createCompilerHost(options);
  const readFile = host.readFile.bind(host);
  host.readFile = (requested) => requested === fileName ? sourceText : readFile(requested);
  const fileExists = host.fileExists.bind(host);
  host.fileExists = (requested) => requested === fileName || fileExists(requested);
  const program = ts.createProgram([fileName], options, host);
  expect(ts.getPreEmitDiagnostics(program).map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))).toEqual([]);
  const emitted: string[] = [];
  const result = program.emit(undefined, (_file, content) => emitted.push(content));
  expect(result.diagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))).toEqual([]);
  expect(result.emitSkipped).toBe(false);
  expect(emitted.join("\n")).toContain("z.ZodRecord<typeof KeySchema, typeof ValueSchema>");
});
