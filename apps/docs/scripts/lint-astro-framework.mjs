import { readdir } from "node:fs/promises";
import path from "node:path";
import { lintAstroFiles } from "@sarj/oxlint-plugin/framework/astro";

async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const results = await Promise.all(entries.map(async (entry) => {
    const filename = path.join(directory, entry.name);
    return entry.isDirectory() ? files(filename) : entry.isFile() && entry.name.endsWith(".astro") ? [filename] : [];
  }));
  return results.flat();
}

const report = await lintAstroFiles({
  filenames: await files(path.resolve(process.argv[2] ?? "src")),
  configPath: path.resolve("oxlint.config.mjs"),
  cwd: process.cwd(),
});
for (const diagnostic of report.diagnostics) {
  const span = diagnostic.labels?.[0]?.span;
  console.error(`${diagnostic.filename}:${span?.line ?? 1}:${span?.column ?? 1}: ${diagnostic.code ?? "oxlint"}: ${diagnostic.message}`);
}
if (report.diagnostics.length) process.exitCode = 1;
