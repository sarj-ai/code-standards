import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import * as nativeParser from "@typescript-eslint/parser";
import ts from "typescript";
import { expect, it } from "vitest";

import { createExampleParser } from "../src/create-example-parser.js";

async function project(files: Readonly<Record<string, string>>): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "example-parser-contract-"));
  try {
    await writeFile(join(root, "tsconfig.json"), JSON.stringify({
      compilerOptions: { strict: true, target: "ES2022", module: "ESNext", moduleResolution: "Bundler",
        types: [], baseUrl: ".", paths: { "@fixture": ["value.ts"] } },
      include: ["**/*.ts"],
    }));
    for (const [name, source] of Object.entries(files)) {
      await mkdir(dirname(join(root, name)), { recursive: true });
      await writeFile(join(root, name), source);
    }
    return root;
  } catch (error) {
    await rm(root, { recursive: true, force: true });
    throw error;
  }
}

function observe(adapter: ReturnType<typeof createExampleParser>, root: string, source: string): ts.Program {
  const result = adapter.parseForESLint(source, {
    filePath: join(root, "input.ts"), project: join(root, "tsconfig.json"), tsconfigRootDir: root,
    disallowAutomaticSingleRunInference: true,
  });
  const program = result.services.program;
  if (program == null) throw new Error("The example lost its native type information.");
  expect(program.getSourceFile(join(root, "input.ts"))?.text).toBe(source);
  return program;
}

function expressionType(program: ts.Program, root: string): string {
  const source = program.getSourceFile(join(root, "input.ts"));
  const statement = source?.statements.find(ts.isExpressionStatement);
  if (statement === undefined) throw new Error("The typed expression fixture was not loaded.");
  const checker = program.getTypeChecker();
  return checker.typeToString(checker.getTypeAtLocation(statement.expression));
}

it("reads actual path aliases and changed sibling declarations with unchanged focus text", async () => {
  const source = 'import { value } from "@fixture"; value;\n';
  const root = await project({ "input.ts": source, "value.ts": 'export let value = "text";\n' });
  const adapter = createExampleParser();
  try {
    const before = observe(adapter, root, source);
    expect(expressionType(before, root)).toBe("string");
    await writeFile(join(root, "value.ts"), "export let value = 1;\n");
    const after = observe(adapter, root, source);
    expect(after).not.toBe(before);
    expect(after.getSourceFile(join(root, "value.ts"))).not.toBe(before.getSourceFile(join(root, "value.ts")));
    expect(expressionType(after, root)).toBe("number");
  } finally {
    adapter.clear();
    nativeParser.clearCaches();
    await rm(root, { recursive: true, force: true });
  }
});

it("isolates same-named projects and global augmentations while sharing only native library ASTs", async () => {
  const source = "export {}; declare const input: string[]; input.parserMarker;\n";
  const roots: string[] = [];
  const adapter = createExampleParser();
  try {
    for (const type of ["string", "number"]) roots.push(await project({
      "input.ts": source,
      "globals.d.ts": `export {}; declare global { interface Array<T> { readonly parserMarker: ${type} } }\n`,
    }));
    for (const [index, type] of [[0, "string"], [1, "number"], [0, "string"]] as const) {
      const root = roots[index];
      if (root === undefined) throw new Error("The isolated project fixture was not created.");
      expect(expressionType(observe(adapter, root, source), root)).toBe(type);
    }
    const statistics = adapter.statistics();
    expect(statistics.libraryAcquires).toBeGreaterThan(0);
    expect(statistics.libraryHits).toBeGreaterThan(0);
    expect(statistics.nativeFallbacks).toBe(0);
    adapter.clear();
    expect(adapter.statistics().libraryFiles).toBe(0);
    expect(adapter.statistics().libraryBytes).toBe(0);
  } finally {
    adapter.clear();
    nativeParser.clearCaches();
    await Promise.all(roots.map((root) => rm(root, { recursive: true, force: true })));
  }
});

it("loads every incoming fix-pass source even while the on-disk input is unchanged", async () => {
  const original = 'export let current = "text"; current;\n';
  const fixed = "export let current = 1; current;\n";
  const root = await project({ "input.ts": original });
  const adapter = createExampleParser();
  try {
    const before = observe(adapter, root, original);
    const after = observe(adapter, root, fixed);
    const repeated = observe(adapter, root, fixed);
    expect(after).not.toBe(before);
    expect(repeated).not.toBe(after);
    expect(expressionType(before, root)).toBe("string");
    expect(expressionType(after, root)).toBe("number");
    expect(expressionType(repeated, root)).toBe("number");
  } finally {
    adapter.clear();
    nativeParser.clearCaches();
    await rm(root, { recursive: true, force: true });
  }
});

function failure(operation: () => unknown): string {
  try {
    operation();
  } catch (error) {
    if (error instanceof Error) return error.message;
    throw error;
  }
  throw new Error("The malformed native configuration unexpectedly passed.");
}

it("preserves native malformed-config failures and delegates unsupported project selectors", async () => {
  const source = "export const value = 1;\n";
  const root = await project({ "input.ts": source });
  const adapter = createExampleParser();
  try {
    const options = { filePath: join(root, "input.ts"), project: join(root, "tsconfig.json"),
      tsconfigRootDir: root, disallowAutomaticSingleRunInference: true };
    const delegated = adapter.parseForESLint(source, { ...options, project: [options.project] });
    expect(delegated.services.program?.getSourceFile(options.filePath)?.text).toBe(source);
    nativeParser.clearCaches();
    await writeFile(options.project, '{ "compilerOptions": ');
    const actual = failure(() => adapter.parseForESLint(source, options));
    nativeParser.clearCaches();
    expect(actual).toBe(failure(() => nativeParser.parseForESLint(source, options)));
    expect(adapter.statistics().nativeFallbacks).toBeGreaterThan(0);
  } finally {
    adapter.clear();
    nativeParser.clearCaches();
    await rm(root, { recursive: true, force: true });
  }
});
