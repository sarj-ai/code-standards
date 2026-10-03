import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { hash } from "node:crypto";
import { readFile } from "node:fs/promises";
import process from "node:process";
import { URL } from "node:url";

const result = spawnSync("npm", ["audit", "--json", "--audit-level=moderate"], {
  cwd: new URL("../", import.meta.url),
  encoding: "utf8",
  shell: false,
});
assert.ok(!result.error && [0, 1].includes(result.status), "npm audit failed");
process.stdout.write(result.stdout);
const report = JSON.parse(result.stdout);
assert.ok(
  report &&
    !report.error &&
    report.vulnerabilities &&
    typeof report.vulnerabilities === "object" &&
    !Array.isArray(report.vulnerabilities),
  "Invalid npm audit report",
);
const findings = report.vulnerabilities;

// This unreleased upstream patch retains version 4.2.0, so verify its source before accepting the advisory.
const source = await readFile(
  new URL("../node_modules/http-cache-semantics/index.js", import.meta.url),
);
const patched =
  hash("sha256", source) ===
  "7e9f2231d0a955704a70a434c6e8bdfbc6e5a9b5cc68238aba0c1546b51e191f";
for (const [name, finding] of Object.entries(findings)) {
  assert.ok(
    ["info", "low", "moderate", "high", "critical"].includes(
      finding?.severity,
    ) &&
      Array.isArray(finding.via) &&
      finding.via.length > 0,
    "Invalid audit finding",
  );
  if (["moderate", "high", "critical"].includes(finding.severity)) {
    assert.ok(
      patched && coveredByPatch(name),
      `Unmitigated dependency advisory: ${name}`,
    );
  }
}
process.stdout.write(
  "Dependency audit passed; source-verified mitigation applies only to GHSA-ch52-4w7c-c8xp\n",
);

function coveredByPatch(name, visited = new Set()) {
  if (visited.has(name) || !Object.hasOwn(findings, name)) return false;
  const finding = findings[name];
  if (name === "http-cache-semantics") {
    return (
      Array.isArray(finding.nodes) &&
      finding.nodes.length === 1 &&
      finding.nodes[0] === "node_modules/http-cache-semantics" &&
      finding.via.length === 1 &&
      finding.via[0]?.url ===
        "https://github.com/advisories/GHSA-ch52-4w7c-c8xp"
    );
  }
  return finding.via.every(
    (cause) =>
      typeof cause === "string" &&
      coveredByPatch(cause, new Set([...visited, name])),
  );
}
