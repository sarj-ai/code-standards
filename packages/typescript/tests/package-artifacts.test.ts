import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, it } from "vitest";
import ts from "typescript";

it.each(["./dist/cli.js", { "sarj-astro-lint": "./dist/cli.js" }])(
  "verifies declared CLI artifacts: %j",
  (bin) => {
    const root = mkdtempSync(path.join(os.tmpdir(), "sarj-package-artifacts-"));
    try {
      mkdirSync(path.join(root, "scripts"));
      mkdirSync(path.join(root, "dist"));
      const script = path.join(root, "scripts/verify-package.mjs");
      copyFileSync(
        new URL("../scripts/verify-package.mjs", import.meta.url),
        script,
      );
      writeFileSync(
        path.join(root, "package.json"),
        JSON.stringify({ main: "./dist/index.js", bin }),
      );
      writeFileSync(path.join(root, "dist/index.js"), "export {};\n");
      const missing = spawnSync(process.execPath, [script], {
        encoding: "utf8",
      });
      expect(missing.status).toBe(1);
      expect(missing.stderr).toContain("dist/cli.js");
      writeFileSync(path.join(root, "dist/cli.js"), "#!/usr/bin/env node\n");
      expect(spawnSync(process.execPath, [script]).status).toBe(0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
);


it("exposes precise framework types through the real public package export", () => {
  const root = path.resolve(import.meta.dirname, "..");
  const consumer = mkdtempSync(path.join(root, ".sarj-framework-types-"));
  try {
    const filename = path.join(consumer, "consumer.mts");
    writeFileSync(filename, `
      import { createAstroCompiler, lintAstroFiles, mapAstroRange, projectAstroPattern }
        from "@sarj/oxlint-plugin/framework/astro";
      const compiler = createAstroCompiler({ cwd: "." });
      const compiled = await compiler.compile("<p />", "Page.astro");
      const text: string = compiled.javascript.outputText;
      const range = mapAstroRange(compiled.origin, [0, text.length], { exact: true });
      if (range) { const start: number = range[0]; void start; }
      const report = await lintAstroFiles({ filenames: ["Page.astro"], configPath: "oxlint.config.mjs" });
      const count: number = report["number_of_files"];
      const pattern: string = projectAstroPattern("**/*.astro", ".tsx");
      void count; void pattern; compiler.close();
      // @ts-expect-error Files must be original source paths.
      await lintAstroFiles({ filenames: [42], configPath: "oxlint.config.mjs" });
      // @ts-expect-error Exact mapping is a boolean contract.
      mapAstroRange(compiled.origin, [0, 1], { exact: "yes" });
      // @ts-expect-error Structured report counts are numbers.
      const invalidCount: string = report["number_of_files"];
      void invalidCount;
    `);
    const program = ts.createProgram([filename], {
      strict: true, noEmit: true, skipLibCheck: false,
      target: ts.ScriptTarget.ES2025,
      lib: ["lib.es2025.d.ts"],
      module: ts.ModuleKind.NodeNext,
      moduleResolution: ts.ModuleResolutionKind.NodeNext,
      types: [],
    });
    expect(ts.getPreEmitDiagnostics(program).map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))).toEqual([]);
  } finally { rmSync(consumer, { recursive: true, force: true }); }
});
