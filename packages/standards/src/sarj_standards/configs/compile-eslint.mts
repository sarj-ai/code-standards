import type * as Compiler from "typescript";

import { readFileSync } from "node:fs";
import { createRequire, stripTypeScriptTypes } from "node:module";

const source = readFileSync(0, "utf8");
const header = "// Generated from eslint.strict.ts by compile-eslint.mts.\n";
if (process.argv[2] === "--declaration") {
  const compiler = process.argv[3];
  if (compiler === undefined) throw new Error("Declaration generation requires the producer's pinned compiler path");
  const require = createRequire(import.meta.url);
  const ts = require(compiler) as typeof Compiler;
  const result = ts.transpileDeclaration(source, {
    fileName: "eslint.strict.mts",
    reportDiagnostics: true,
    compilerOptions: {
      target: ts.ScriptTarget.Latest,
      module: ts.ModuleKind.ESNext,
      newLine: ts.NewLineKind.LineFeed,
      removeComments: true,
    },
  });
  const errors = result.diagnostics?.filter(
    (diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
  ) ?? [];
  if (errors.length !== 0) {
    throw new Error(errors.map(
      (diagnostic) => `TS${diagnostic.code}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`,
    ).join("\n"));
  }
  process.stdout.write(header + result.outputText);
} else {
  if (process.argv[2] !== undefined) throw new Error("Expected --declaration or no arguments");
  const compiled = stripTypeScriptTypes(source, {
    // @ts-expect-error -- Pinned Node 24 supports transform; shared Node 26 types expose only strip.
    mode: "transform",
  });
  process.stdout.write(header + compiled);
}
