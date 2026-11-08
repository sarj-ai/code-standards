// Run after build with the isolated locked source fixture used by --refresh.
// Additional arguments are read-only corpora; no reference packages are installed here.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PACKAGE_DIR } from "./lib.ts";

const source = process.env["SARJ_UPSTREAM_SOURCE"];
if (!source)
  throw new Error("SARJ_UPSTREAM_SOURCE must identify the isolated locked source fixture");
assert.deepEqual(
  await readFile(join(source, "package-lock.json")),
  await readFile(join(PACKAGE_DIR, "src/upstream/sources.lock.json")),
  "Reference fixture must match the reviewed source lock",
);
const root = await mkdtemp(join(tmpdir(), "sarj-next-parity-"));
const ruleId = "no-location-assign-relative-destination";
interface Diagnostic {
  message: string;
  code?: string;
  filename?: string;
  labels?: unknown;
}
function lint(kind: string, target: string): Diagnostic[] {
  const result = spawnSync(
    join(PACKAGE_DIR, "node_modules/.bin/oxlint"),
    ["--config", join(root, `${kind}.json`), "--format=json", target],
    { encoding: "utf8", timeout: 60_000 },
  );
  if (result.error) throw result.error;
  assert.ok(result.status === 0 || result.status === 1, result.stderr);
  const output = JSON.parse(result.stdout) as { diagnostics: Diagnostic[] };
  return output.diagnostics.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}
function assertNoCrashes(diagnostics: Diagnostic[]): void {
  assert.ok(
    diagnostics.every(({ message }) => !message.includes("Error running JS plugin")),
    JSON.stringify(diagnostics),
  );
}
try {
  for (const kind of ["original", "bundled"]) {
    const implementation =
      kind === "original"
        ? `import {createRequire} from "node:module"; const rule=createRequire(import.meta.url)(${JSON.stringify(join(source, "node_modules/@next/eslint-plugin-next/dist/rules", `${ruleId}.js`))}).default; export default {rules:{${JSON.stringify(ruleId)}:rule}};`
        : `export {default} from ${JSON.stringify(join(PACKAGE_DIR, "dist/next.js"))};`;
    await writeFile(join(root, `${kind}.mjs`), implementation);
    await writeFile(
      join(root, `${kind}.json`),
      JSON.stringify({
        categories: { correctness: "off" },
        env: { browser: true },
        jsPlugins: [{ name: "next-js", specifier: join(root, `${kind}.mjs`) }],
        rules: { [`next-js/${ruleId}`]: "error" },
      }),
    );
  }
  const cycle = join(root, "cycle.ts");
  await writeFile(
    cycle,
    "const a = b; const b = a; location.assign(a); location.assign('/still-checked');",
  );
  const originalCycle = lint("original", cycle);
  assert.ok(
    originalCycle.some(({ message }) => message.includes("Maximum call stack size exceeded")),
    "Expected upstream cycle crash",
  );
  const bundledCycle = lint("bundled", cycle);
  assertNoCrashes(bundledCycle);
  assert.equal(
    bundledCycle.length,
    1,
    "Cyclic evaluation is unknown; subsequent relative navigation still reports",
  );
  const fixture = join(root, "noncyclic.ts");
  await writeFile(
    fixture,
    `
const base = '/a'; const alias = base; location.assign(alias); location.assign(alias);
location.assign('/A'.toLowerCase()); self['location']['href'] = '/a';
let url='https://example.com'; url='/b'; location.assign(url);
function shadow(location) { location.assign('/ignored') }
const prefix = '/relative/' + prefix; location.assign(prefix);
location.assign(\`/users/\${unknown}\`); location.assign('https://example.com');
`,
  );
  for (const target of [fixture, ...process.argv.slice(2)]) {
    const original = lint("original", target);
    const bundled = lint("bundled", target);
    assertNoCrashes(original);
    assertNoCrashes(bundled);
    assert.deepEqual(bundled, original, "Finding filename, rule, offsets and message must match");
    if (target === fixture) assert.ok(original.length > 0);
    console.log(
      JSON.stringify({
        corpus: target === fixture ? "noncyclic fixture" : "supplied corpus",
        findings: original.length,
        exactMatch: true,
      }),
    );
  }
  console.log(
    "Upstream cyclic alias crash reproduced; bundled cycle returns unknown and retains subsequent findings",
  );
} finally {
  await rm(root, { recursive: true, force: true });
}
