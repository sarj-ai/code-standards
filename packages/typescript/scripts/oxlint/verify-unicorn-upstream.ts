// Read-only comparison with the isolated source-lock installation used by refresh.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PACKAGE_DIR } from "./lib.ts";

const source = process.env["SARJ_UPSTREAM_SOURCE"];
if (!source) throw new Error("SARJ_UPSTREAM_SOURCE must identify the locked source fixture");
assert.deepEqual(
  await readFile(join(source, "package-lock.json")),
  await readFile(join(PACKAGE_DIR, "src/upstream/sources.lock.json")),
);
const bundled = (await import(join(PACKAGE_DIR, "dist/unicorn-js.js"))) as {
  default: { rules: Record<string, unknown> };
};
const extras = ["prefer-https", "prefer-switch"];
const managed = Object.keys(bundled.default.rules)
  .filter((id) => !extras.includes(id))
  .sort();
assert.equal(managed.length, 80);
const root = await mkdtemp(join(tmpdir(), "sarj-unicorn-parity-"));
const fixture = join(root, "fixture.ts");
const originalSource = `
const insecure = "http://api.github.com/path";
const secure = "https://api.github.com/path";
const local = "http://localhost:3000";
const namespace = "http://www.w3.org/2000/svg";
function choose(value: number) {
  if (value === 1) return "one";
  else if (value === 2) return "two";
  else if (value === 3) return "three";
  return "other";
}
function short(value: number) { if(value === 1) return 1; else if(value === 2) return 2; }
function other(value: number, second: number) { if(value === 1) return 1; else if(second === 2) return 2; }
function typeError(value: unknown) { if (typeof value !== "string") throw new Error("Expected a string"); }
const values = new Array(3); const first = values[values.length - 1];
const empty = values.filter(Boolean); console.log(parseInt("10"));
`;
interface Finding {
  message: string;
  code?: string;
}
function lint(config: string, fix: boolean): Finding[] {
  const result = spawnSync(
    join(PACKAGE_DIR, "node_modules/.bin/oxlint"),
    ["--config", config, "--format=json", ...(fix ? ["--fix"] : []), fixture],
    { encoding: "utf8", timeout: 60_000 },
  );
  if (result.error) throw result.error;
  assert.ok(result.status === 0 || result.status === 1, result.stderr);
  const output = JSON.parse(result.stdout) as { diagnostics: Finding[] };
  assert.ok(
    output.diagnostics.every(({ message }) => !message.includes("Error running JS plugin")),
    JSON.stringify(output.diagnostics),
  );
  return output.diagnostics.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}
try {
  for (const [label, ids, options] of [
    ["existing80", managed, {}],
    ["extras-defaults", extras, {}],
    [
      "extras-options",
      extras,
      {
        "prefer-https": ["error", { ignore: ["http://api.github.com/path"] }],
        "prefer-switch": ["error", { minimumCases: 2, emptyDefaultCase: "no-default-case" }],
      },
    ],
  ] as const) {
    const results = [];
    for (const kind of ["original", "bundled"]) {
      const config = join(root, `${kind}.json`);
      await writeFile(
        config,
        JSON.stringify({
          categories: { correctness: "off" },
          jsPlugins: [
            {
              name: "unicorn-policy",
              specifier:
                kind === "original"
                  ? join(source, "node_modules/eslint-plugin-unicorn/index.js")
                  : join(PACKAGE_DIR, "dist/unicorn-js.js"),
            },
          ],
          rules: Object.fromEntries(
            ids.map((id) => [
              `unicorn-policy/${id}`,
              options[id as keyof typeof options] ?? "error",
            ]),
          ),
        }),
      );
      await writeFile(fixture, originalSource);
      const diagnostics = lint(config, false);
      const afterFix = lint(config, true);
      results.push({ diagnostics, afterFix, fixed: await readFile(fixture, "utf8") });
    }
    assert.deepEqual(
      results[1],
      results[0],
      `${label}: messages, positions, fixes and post-fix diagnostics must match`,
    );
    assert.ok(results[0]!.diagnostics.length > 0, `${label}: nonvacuous findings`);
    if (label === "extras-defaults")
      assert.deepEqual(results[0]!.diagnostics.map((item) => item.code).sort(), [
        "unicorn-policy(prefer-https)",
        "unicorn-policy(prefer-switch)",
      ]);
    console.log(
      `${label}: ${String(ids.length)} rule exports, ${String(results[0]!.diagnostics.length)} findings; exact finding/fix parity`,
    );
  }
} finally {
  await rm(root, { recursive: true, force: true });
}
