import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import process from "node:process";
import { URL } from "node:url";

import { record, text } from "./_json.ts";

const result = spawnSync("npm", ["audit", "--json", "--audit-level=moderate"], {
  cwd: new URL("../", import.meta.url),
  encoding: "utf8",
  shell: false,
});
assert.ok(
  !result.error && result.status !== null && [0, 1].includes(result.status),
  "npm audit failed",
);
process.stdout.write(result.stdout);
const report = record(JSON.parse(result.stdout) as unknown, "npm audit report");
assert.ok(
  !report["error"] &&
    report["vulnerabilities"] &&
    typeof report["vulnerabilities"] === "object" &&
    !Array.isArray(report["vulnerabilities"]),
  "Invalid npm audit report",
);
for (const [name, value] of Object.entries(
  record(report["vulnerabilities"], "npm vulnerabilities"),
)) {
  const finding = record(value, `npm finding ${name}`);
  const severity = text(finding["severity"], `npm finding ${name} severity`);
  assert.ok(
    ["info", "low", "moderate", "high", "critical"].includes(severity),
    "Invalid audit finding",
  );
  assert.ok(
    !["moderate", "high", "critical"].includes(severity),
    `Unmitigated dependency advisory: ${name}`,
  );
}
process.stdout.write("Dependency audit passed\n");
