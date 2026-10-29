import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { afterAll, beforeAll, expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));

interface DeclarationFixture {
  readonly directory: string;
  readonly emitted: readonly string[];
  readonly invalid: string;
  readonly options: ts.CompilerOptions;
}

let preparation: Promise<DeclarationFixture> | undefined;
let fixture: DeclarationFixture | undefined;

beforeAll(async () => {
  preparation = prepareDeclarations();
  fixture = await preparation;
});

afterAll(async () => {
  if (preparation === undefined) return;
  let prepared: DeclarationFixture;
  try {
    prepared = await preparation;
  } catch {
    return;
  }
  await rm(prepared.directory, { recursive: true, force: true });
});

it("emits portable public declarations for inferred ESM and CommonJS rule exports", () => {
  if (fixture === undefined) throw new Error("The real declaration producer did not complete.");
  const consumer = ts.createProgram([...fixture.emitted, fixture.invalid], {
    ...fixture.options,
    emitDeclarationOnly: false,
    noEmit: true,
  });
  const rejected = ts.getPreEmitDiagnostics(consumer);
  expect(rejected.map((diagnostic) => diagnostic.file?.fileName), messages(rejected).join("\n"))
    .toEqual([fixture.invalid, fixture.invalid, fixture.invalid, fixture.invalid]);
  expect(new Set(rejected.map((diagnostic) => diagnostic.start === undefined || diagnostic.file === undefined
    ? -1
    : diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start).line)))
    .toEqual(new Set([1, 2, 3, 4]));
});

async function prepareDeclarations(): Promise<DeclarationFixture> {
  const directory = await mkdtemp(
    join(await realpath(tmpdir()), "sarj-public-declarations-"),
  );
  try {
    const dependencies = join(directory, "node_modules");
    const installed = join(dependencies, "@sarj", "eslint-plugin");
    await mkdir(installed, { recursive: true });
    await writeFile(
      join(installed, "package.json"),
      await readFile(join(PACKAGE_ROOT, "package.json")),
    );
    await cp(join(PACKAGE_ROOT, "dist"), join(installed, "dist"), {
      recursive: true,
    });
    for (const dependency of [
      "@typescript-eslint",
      "eslint",
      "typescript",
      "ts-api-utils",
      "jsonc-parser",
      "@types",
    ]) {
      await symlink(
        join(PACKAGE_ROOT, "node_modules", dependency),
        join(dependencies, dependency),
        "dir",
      );
    }
    await writeFile(
      join(directory, "package.json"),
      '{"private":true,"type":"module"}\n',
    );
    const source = [
      'import plugin, { ADVISORY_RULES, STRICT_RULES } from "@sarj/eslint-plugin";',
      'export const selectedRule = plugin.rules["no-comment-cruft"];',
      'export const selectedRules = { "no-comment-cruft": selectedRule };',
      'export const configured: readonly ["error", { readonly enabled: false }] = STRICT_RULES["@sarj/prefer-logical-tailwind-utilities"];',
      'export const fromConfig: typeof configured = plugin.configs.recommended.rules["@sarj/prefer-logical-tailwind-utilities"];',
      'export const advisory: readonly string[] = ADVISORY_RULES;',
      'export const warning: "warn" = STRICT_RULES["@sarj/excessive-commentary"];',
      "",
    ].join("\n");
    const entrypoints = ["mts", "cts"].map((extension) =>
      join(directory, `consumer.${extension}`),
    );
    await Promise.all(
      entrypoints.map((entrypoint) => writeFile(entrypoint, source)),
    );
    const options: ts.CompilerOptions = {
      strict: true,
      declaration: true,
      emitDeclarationOnly: true,
      noEmitOnError: true,
      skipLibCheck: false,
      types: [],
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.NodeNext,
      moduleResolution: ts.ModuleResolutionKind.NodeNext,
    };
    const emitted = new Map<string, string>();
    const host = ts.createCompilerHost(options);
    host.writeFile = (filename, text) => {
      emitted.set(filename, text);
    };
    const program = ts.createProgram(entrypoints, options, host);
    expect(messages(program.getConfigFileParsingDiagnostics())).toEqual([]);
    const result = program.emit();
    expect(result.emitSkipped).toBe(false);
    expect(messages(result.diagnostics)).toEqual([]);
    expect(new Set(emitted.keys())).toEqual(
      new Set([
        join(directory, "consumer.d.mts"),
        join(directory, "consumer.d.cts"),
      ]),
    );
    await Promise.all(
      [...emitted].map(([filename, text]) => writeFile(filename, text)),
    );
    const invalid = join(directory, "invalid-consumer.mts");
    await writeFile(invalid, [
      'import plugin, { ADVISORY_RULES, STRICT_RULES } from "@sarj/eslint-plugin";',
      'STRICT_RULES["@sarj/no-such-rule"];',
      'plugin.configs.recommended.rules["@sarj/no-enum"];',
      'ADVISORY_RULES.push("@sarj/excessive-commentary");',
      'STRICT_RULES["@sarj/prefer-logical-tailwind-utilities"][1].enabled = true;',
      "",
    ].join("\n"));
    return { directory, emitted: [...emitted.keys()], invalid, options };
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
}

function messages(diagnostics: readonly ts.Diagnostic[]): readonly string[] {
  return diagnostics.map((diagnostic) =>
    `${diagnostic.code}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`);
}
