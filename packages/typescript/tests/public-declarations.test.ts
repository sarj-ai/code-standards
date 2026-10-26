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
import { expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));

it("emits portable public declarations for inferred ESM and CommonJS rule exports", async () => {
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
    const source =
      'import plugin from "@sarj/eslint-plugin";\nexport const selectedRule = plugin.rules["no-comment-cruft"];\nexport const selectedRules = { "no-comment-cruft": selectedRule };\n';
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
    const messages = (
      diagnostics: readonly ts.Diagnostic[],
    ): readonly string[] =>
      diagnostics.map(
        (diagnostic) =>
          `${diagnostic.code}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`,
      );
    expect(messages(ts.getPreEmitDiagnostics(program))).toEqual([]);
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
    const consumer = ts.createProgram([...emitted.keys()], {
      ...options,
      emitDeclarationOnly: false,
      noEmit: true,
    });
    expect(messages(ts.getPreEmitDiagnostics(consumer))).toEqual([]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
