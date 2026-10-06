import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
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
      false,
      `Unmitigated dependency advisory: ${name}`,
    );
  }
}
process.stdout.write("Dependency audit passed\n");
