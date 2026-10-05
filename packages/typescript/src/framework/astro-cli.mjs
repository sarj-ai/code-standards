#!/usr/bin/env node
import { parseArgs } from "node:util";
import path from "node:path";
import { lintAstroFiles } from "./astro.mjs";

try {
  const { values, positionals } = parseArgs({
    options: {
      config: { type: "string" },
      format: { type: "string", default: "json" },
      "type-aware": { type: "boolean" },
      "deny-warnings": { type: "boolean" },
      "no-error-on-unmatched-pattern": { type: "boolean" },
      fix: { type: "boolean" },
      "fix-suggestions": { type: "boolean" },
    },
    allowPositionals: true,
  });
  if (!values.config || values.format !== "json") {
    throw new Error("sarj-astro-lint requires --config and --format json");
  }
  if (
    positionals.length === 0 ||
    positionals.some((filename) => !filename.endsWith(".astro"))
  ) {
    throw new Error("sarj-astro-lint requires explicit Astro filenames");
  }
  const report = await lintAstroFiles({
    filenames: positionals.map((filename) => path.resolve(filename)),
    configPath: path.resolve(values.config),
    cwd: process.cwd(),
    ...(values["type-aware"] && { typeAware: true }),
    fix: values.fix || values["fix-suggestions"] || false,
    fixSuggestions: values["fix-suggestions"] || false,
  });
  if (
    report["number_of_files"] === 0 &&
    !values["no-error-on-unmatched-pattern"]
  ) {
    throw new Error("No Astro files matched the authored native policy");
  }
  process.stdout.write(`${JSON.stringify(report)}\n`);
  process.exitCode = report.diagnostics.some(
    (diagnostic) =>
      diagnostic.severity === "error" ||
      (values["deny-warnings"] && diagnostic.severity === "warning"),
  )
    ? 1
    : 0;
} catch (error) {
  process.stderr.write(
    `${error instanceof Error ? error.message : String(error)}\n`,
  );
  process.exitCode = 2;
}
