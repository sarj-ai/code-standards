import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const CLI = join(dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))), "bin/oxlint");
const PLUGIN = fileURLToPath(new URL("../dist/index.js", import.meta.url));

/** Execute the stock CLI and ordinary native configuration in an isolated fixture. */
export function stockLint(ruleId: string, source: string, extension = "ts", setting: unknown = "error") {
  const root = mkdtempSync(join(tmpdir(), "sarj-stock-oxlint-"));
  try {
    const filename = join(root, `example.${extension}`);
    const config = join(root, ".oxlintrc.json");
    writeFileSync(filename, source);
    writeFileSync(config, JSON.stringify({
      categories: { correctness: "off" }, plugins: [],
      jsPlugins: [{ name: "@sarj", specifier: PLUGIN }],
      rules: { [`@sarj/${ruleId}`]: setting },
    }));
    const result = spawnSync(process.execPath, [CLI, "--config", config, "--format=json", "--no-ignore", filename], {
      cwd: root, encoding: "utf8", timeout: 30_000,
    });
    if (result.error !== undefined) throw result.error;
    const parsed: unknown = JSON.parse(result.stdout);
    if (typeof parsed !== "object" || parsed === null || !("diagnostics" in parsed) || !Array.isArray(parsed.diagnostics)) {
      throw new Error(`invalid native output: ${result.stdout}\n${result.stderr}`);
    }
    return { status: result.status, diagnostics: parsed.diagnostics };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}
