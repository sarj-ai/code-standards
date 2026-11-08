import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { createRequire } from "node:module";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
const require = createRequire(process.argv[2] + "/package.json");
const plugin = require.resolve("oxlint-plugin-react-doctor");
const parser = createRequire(plugin)("oxc-parser");
const core = await import(require.resolve("oxlint-plugin-react-doctor/core"));
const { reactDoctorArtifactPem } = await import(process.argv[3]);
const rule = core.REACT_DOCTOR_SCAN_RULES.find((e) => e.id === "artifact-secret-leak").rule;
const header = "-----BEGIN PRIVATE KEY-----";
const removal = `"".replace(/${header}/g, "")`;
const key = generateKeyPairSync("ed25519").privateKey.export({ type: "pkcs8", format: "pem" });
const builderKey = `const builder={replace(pattern){return pattern.source}};const key=builder.replace(/${header}/g,"")+${JSON.stringify(key.slice(header.length))};`;
const file = (content, path = "dist/main.js") => ({
  relativePath: path,
  absolutePath: "/" + path,
  content,
  isGeneratedBundle: true,
});
const findings = (f) => rule.scan(f);
const adapted = (f) => ({ ...f, content: reactDoctorArtifactPem(f, parser) });
const map = (source) =>
  JSON.stringify({
    version: 3,
    sources: ["worker.ts"],
    sourcesContent: [source],
    names: [],
    mappings: "",
  });
assert.equal(findings(file(removal)).length, 1);
assert.equal(findings(file(removal + ";const key=" + JSON.stringify(key))).length, 1); // old count-1 budget misses this
for (const path of ["dist/main.js", "dist/main.js.map"]) {
  const encode = (s) => (path.endsWith(".map") ? map(s) : s);
  assert.equal(findings(adapted(file(encode(removal), path))).length, 0);
  for (const source of [
    JSON.stringify(key),
    removal + ";const key=" + JSON.stringify(key),
    builderKey,
    `function decode(pem: string) { pem=builder as unknown as string; return pem.replace(/${header}/g, ""); }`,
    `function decode(pem: string) { { const pem=builder; return pem.replace(/${header}/g, ""); } }`,
    `function decode(pem: string) { arguments[0]=builder; return pem.replace(/${header}/g, ""); }`,
    `function decode(pem: string) { eval("pem=builder"); return pem.replace(/${header}/g, ""); }`,
    `String.prototype.replace=function(pattern){return pattern.source};${removal}`,
    `function decode(pem) { return pem.replace(/${header}/g, ""); }`,
    JSON.stringify(removal),
    "`" + removal + "`",
    `const r=/${header}/g; r.source`,
    `const key=/${header}/.source + "data"`,
    `pem.replace(/${header}/g,"x")`,
    removal + ";const =",
  ]) {
    assert.ok(findings(adapted(file(encode(source), path))).length > 0, "unsafe exclusion");
  }
  const source = 'const unicode="😀é";' + removal + ";\nconst key=" + JSON.stringify(key);
  const original = file(encode(source), path),
    masked = adapted(original);
  assert.equal(Buffer.byteLength(masked.content), Buffer.byteLength(original.content));
  const expected = findings({
    ...original,
    content: original.content.replace(header, "xxxxxBEGIN PRIVATE KEYxxxxx"),
  });
  assert.deepEqual(findings(masked), expected);
}
const escaped = map(removal).replaceAll("-", "\\u002d");
assert.equal(findings(adapted(file(escaped, "dist/main.js.map"))).length, 0);
const typedRemoval = `function decode(pem: string) { return pem.replace(/${header}/g, ""); }`;
assert.equal(findings(adapted(file(map(typedRemoval), "dist/main.js.map"))).length, 0);
for (const content of [
  map(removal).slice(0, -1),
  map(removal).replace('"version":3', '"version":2'),
  map(removal).replace("worker.ts", "worker.unknown"),
]) {
  const f = file(content, "dist/main.js.map");
  assert.equal(adapted(f).content, content);
}
for (const path of process.argv.slice(5)) {
  const f = file(readFileSync(path, "utf8"), "dist/main.js.map");
  console.log(
    JSON.stringify({ corpus: path, old: findings(f).length, new: findings(adapted(f)).length }),
  );
  const parsed = JSON.parse(f.content);
  parsed.sourcesContent.push("const key=" + JSON.stringify(key));
  parsed.sources.push("key.ts");
  assert.ok(findings(adapted(file(JSON.stringify(parsed), "dist/main.js.map"))).length > 0);
}
console.log("PASS: official callback, same-artifact key control, maps, offsets, fail-closed cases");

const { scanSecurity } = await import(new URL("./react-doctor-scan.mjs", process.argv[3]));
const root = process.argv[4];
mkdirSync(root + "/dist", { recursive: true });
for (const [name, content] of Object.entries({
  "removal.js": removal,
  "removal.js.map": map('const pem: string = "";' + removal),
  "key.js": "const key=" + JSON.stringify(key),
  "after.js": removal + ";const key=" + JSON.stringify(key),
  "after.js.map": map(removal + ";const key=" + JSON.stringify(key)),
  "lookalike.js": "const text=" + JSON.stringify(removal),
  "data.js": `const key=/${header}/.source + "data"`,
}))
  writeFileSync(
    root + "/dist/" + name,
    content + (name.endsWith(".js") ? ";" + "void 0;".repeat(4000) : ""),
  );
const originalInputs = [];
const observed = {
  ...core,
  REACT_DOCTOR_SCAN_RULES: [
    ...core.REACT_DOCTOR_SCAN_RULES,
    {
      id: "observe",
      key: "react-doctor/observe",
      rule: {
        severity: "error",
        scan(f) {
          originalInputs.push(f);
          return [];
        },
      },
    },
  ],
};
const diagnostics = scanSecurity(root, observed, {}, [], () => false, parser);
assert.equal(diagnostics.filter((d) => d.rule === "artifact-secret-leak").length, 5);
assert.ok(originalInputs.every((f) => f.content === readFileSync(f.absolutePath, "utf8")));
console.log("PASS: shared scan pipeline preserves original inputs for other callbacks");
