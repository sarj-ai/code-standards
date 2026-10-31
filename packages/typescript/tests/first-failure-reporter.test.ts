import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, describe, expect, it } from "vitest";

const CONFIG = fileURLToPath(new URL("../vitest.config.ts", import.meta.url));
const CLI = fileURLToPath(new URL("../node_modules/vitest/dist/cli.js", import.meta.url));
const VITEST = new URL("../node_modules/vitest/dist/index.js", import.meta.url).href;
const PREVIEW_START = "First failed test (preview; complete details remain in the final report):";
const PREVIEW_END = "[End of first failure preview]";

let privateCache: string | undefined;

async function fixtureEnvironment(): Promise<NodeJS.ProcessEnv> {
  if (process.env.NODE_COMPILE_CACHE !== undefined || process.env.NODE_DISABLE_COMPILE_CACHE !== undefined ||
      process.env.NODE_V8_COVERAGE !== undefined) {
    return { ...process.env };
  }
  privateCache ??= await mkdtemp(join(tmpdir(), "sarj-first-failure-compile-cache-"));
  return { ...process.env, NODE_COMPILE_CACHE: privateCache };
}

afterAll(async () => {
  if (privateCache !== undefined) await rm(privateCache, { recursive: true, force: true });
});

async function runFixture(source: string, options: { arguments?: string[]; acknowledgePreview?: boolean; collect?: boolean } = {}) {
  const root = await mkdtemp(join(tmpdir(), "sarj-first-failure-"));
  try {
    await mkdir(join(root, ".git"));
    await mkdir(join(root, "tests"));
    await writeFile(join(root, "tests/cases.test.ts"), `import { afterEach, beforeEach, expect, test } from ${JSON.stringify(VITEST)};\n${source}`);
    const env = await fixtureEnvironment();
    const started = performance.now();
    const child = spawn(process.execPath, [CLI, options.collect ? "list" : "run", "--root", root, "--config", CONFIG, "--maxWorkers=1", "--no-color", ...options.arguments ?? []], {
      timeout: 15_000,
      stdio: ["ignore", "pipe", "pipe"],
      env,
    });
    let stdout = "";
    let stderr = "";
    let acknowledged: Promise<void> | undefined;
    child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
      if (options.acknowledgePreview && acknowledged === undefined && stderr.includes(PREVIEW_END)) {
        acknowledged = writeFile(join(root, "continue"), "preview received");
      }
    });
    const status = await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", resolve);
    });
    await acknowledged;
    if (child.signalCode !== null) {
      throw new Error(`Fixture CLI terminated by ${child.signalCode} after ${Math.round(performance.now() - started)}ms.\n${stdout}\n${stderr}`);
    }
    const report: unknown = options.arguments?.includes("--reporter=json")
      ? JSON.parse(await readFile(join(root, "report.json"), "utf8"))
      : undefined;
    return { status, stdout, stderr, report, output: stdout + stderr };
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

describe("native first failure preview", () => {
  it("previews one bounded failure while another case is running and preserves full final details", async () => {
    const message = `first assertion ${"x".repeat(5000)} final detail`;
    const result = await runFixture(`
import { existsSync } from "node:fs";
test("first case", () => { throw new Error(${JSON.stringify(message)}); });
test("later case", async () => {
  const started = Date.now();
  while (!existsSync(new URL("../continue", import.meta.url))) {
    if (Date.now() - started > 2000) throw new Error("preview was withheld");
    await new Promise(resolve => setTimeout(resolve, 10));
  }
});
test("second failure", () => { throw new Error("second assertion"); });
`, { acknowledgePreview: true });
    expect(result.status).toBe(1);
    expect(result.stderr.split(PREVIEW_START)).toHaveLength(2);
    const preview = result.stderr.split(PREVIEW_END)[0]?.split(PREVIEW_START)[1] ?? "";
    expect(preview.length + PREVIEW_START.length).toBeLessThanOrEqual(4097);
    expect(preview).toContain("tests/cases.test.ts > first case");
    expect(preview).toContain("first assertion");
    expect(preview).not.toContain("final detail");
    expect(preview).not.toContain("second assertion");
    expect(result.output).toContain("final detail");
    expect(result.output).toContain("second assertion");
    expect(result.output).toContain("1 passed");
    expect(result.output).not.toContain("preview was withheld");
  });

  it.each([
    'beforeEach(() => { throw new Error("setup assertion"); }); test("setup case", () => {});',
    'afterEach(() => { throw new Error("teardown assertion"); }); test("teardown case", () => {});',
    'test.fails("unexpected pass", () => {});',
  ])("previews final failed results from hooks and expected-failure cases: %s", async (source) => {
    const result = await runFixture(source);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(PREVIEW_START);
    expect(result.output).toContain("1 failed");
  });

  it("keeps passed retries and skipped cases quiet", async () => {
    const result = await runFixture(`
let attempts = 0;
test("retry succeeds", { retry: 1 }, () => { if (attempts++ === 0) throw new Error("retry assertion"); });
test.skip("skipped case", () => { throw new Error("skipped assertion"); });
`);
    expect(result.status).toBe(0);
    expect(result.output).not.toContain(PREVIEW_START);
    expect(result.output).not.toContain("retry assertion");
    expect(result.output).toContain("1 passed");
    expect(result.output).toContain("1 skipped");
  });

  it("honors explicit JSON reporters and console suppression", async () => {
    const result = await runFixture('test("failure", () => { console.log("suppressed console"); throw new Error("JSON assertion"); });', { arguments: ["--reporter=json", "--outputFile=report.json", "--silent"] });
    expect(result.status).toBe(1);
    expect(result.output).not.toContain(PREVIEW_START);
    expect(result.output).not.toContain("suppressed console");
    expect(result.report).toMatchObject({ numFailedTests: 1, numTotalTests: 1 });
  });

  it("keeps collection free of failure previews", async () => {
    const result = await runFixture('test("collected case", () => { throw new Error("unexecuted assertion"); });', { collect: true });
    expect(result.status).toBe(0);
    expect(result.output).not.toContain(PREVIEW_START);
    expect(result.output).not.toContain("unexecuted assertion");
  });
});
