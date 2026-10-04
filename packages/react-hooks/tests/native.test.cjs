const assert = require("node:assert/strict");
const { mkdtempSync, writeFileSync, rmSync, readFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { dirname, join, resolve } = require("node:path");
const { spawnSync } = require("node:child_process");
const { createHash } = require("node:crypto");
const { test } = require("node:test");

const binary = join(dirname(require.resolve("oxlint/package.json")), "bin/oxlint");
const plugin = resolve(__dirname, "../index.cjs");
function lint(rule, code, options = []) {
  const root = mkdtempSync(join(tmpdir(), "native-react-hooks-"));
  try {
    writeFileSync(
      join(root, "policy.mjs"),
      `export default ${JSON.stringify({
        categories: { correctness: "off" },
        jsPlugins: [{ name: "react-hooks-js", specifier: plugin }],
        rules: { [`react-hooks-js/${rule}`]: ["error", ...options] },
      })};`,
    );
    writeFileSync(join(root, "sample.tsx"), code);
    const result = spawnSync(
      process.execPath,
      [binary, "--config", "policy.mjs", "--format", "json", "sample.tsx"],
      {
        cwd: root,
        encoding: "utf8",
        timeout: 30_000,
      },
    );
    assert.ifError(result.error);
    assert.equal(result.stderr, "");
    assert.ok(result.status === 0 || result.status === 1, result.stdout);
    return JSON.parse(result.stdout).diagnostics;
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("licensed upstream implementation is unchanged", () => {
  const metadata = require("../PROVENANCE.json");
  const hash = createHash("sha256")
    .update(readFileSync(resolve(__dirname, "../vendor/react-hooks.cjs")))
    .digest("hex");
  assert.equal(hash, metadata.files["vendor/react-hooks.cjs"].sha256);
});
for (const [rule, invalid, valid] of [
  [
    "rules-of-hooks",
    'import {useState} from "react";function Component({enabled}){if(enabled)useState(0);return null;}',
    'import {useState} from "react";function Component(){useState(0);return null;}',
  ],
  [
    "exhaustive-deps",
    'import {useEffect} from "react";function Component({value}){useEffect(()=>console.log(value),[]);return null;}',
    'import {useEffect} from "react";function Component({value}){useEffect(()=>console.log(value),[value]);return null;}',
  ],
  [
    "immutability",
    "function Component(props){props.value=1;return <div>{props.value}</div>;}",
    "function Component(props){return <div>{props.value}</div>;}",
  ],
  [
    "set-state-in-render",
    'import {useState} from "react";function Component(){const [v,setV]=useState(0);setV(1);return <div>{v}</div>;}',
    'import {useState} from "react";function Component(){const [v,setV]=useState(0);return <button onClick={()=>setV(1)}>{v}</button>;}',
  ],
]) {
  test(`${rule} runs its original positive and negative controls in stock Oxlint`, () => {
    assert.ok(
      lint(rule, invalid).some((diagnostic) => diagnostic.code === `react-hooks-js(${rule})`),
    );
    assert.deepEqual(lint(rule, valid), []);
  });
}
