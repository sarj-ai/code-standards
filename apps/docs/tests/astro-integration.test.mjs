import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const { scripts } = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));

function run(command) {
  return spawnSync("/bin/sh", ["-c", command], {
    cwd: root,
    env: {
      ...process.env,
      PATH: `${path.resolve(root, "../../node_modules/.bin")}:${process.env.PATH ?? ""}`,
    },
    encoding: "utf8",
    timeout: 120_000,
  });
}

for (const [name, source, rule, line] of [
  [
    "interactive Astro reaches its complete provider",
    '---\n"use client";\n---\n<button onClick={() => 1}>Save</button>\n',
  ],
  [
    "static Astro remains a blocking finding",
    '---\n"use client";\n---\n<button>Save</button>\n',
    "@sarj(no-unnecessary-use-client)",
    2,
  ],
  [
    "browser globals stay outside Astro frontmatter",
    '---\nwindow.alert("hello");\n---\n<div/>\n',
    "eslint(no-undef)",
    2,
  ],
  [
    "Node globals stay outside Astro client scripts",
    "<script>process.exit(1);</script>\n",
    "eslint(no-undef)",
    1,
  ],
  ["Node globals remain available in Astro frontmatter", "---\nprocess.exit(1);\n---\n<div/>\n"],
  [
    "browser globals remain available in Astro client scripts",
    '<script>window.alert("hello");</script>\n',
  ],
]) {
  await test(name, async () => {
    const status = rule === undefined ? 0 : 1;
    const directory = await mkdtemp(path.join(root, "src/.astro-integration-"));
    try {
      await writeFile(path.join(directory, "Component.astro"), source);
      await writeFile(path.join(directory, "sentinel.ts"), "export const sentinel = 1;\n");
      const target = `'${path.relative(root, directory)}'`;
      // Narrow only input paths; keep the authored commands and real docs policy.
      assert.ok(scripts.lint.includes(" . && ") && scripts.lint.endsWith(" src"));
      const command = scripts.lint
        .replace(" . && ", ` ${target} && `)
        .replace(/ src$/u, ` ${target}`);
      const ordinary = command.split(" && ")[0];
      const discovery = run(`${ordinary} --debug files`);
      assert.equal(discovery.status, 0, discovery.stderr);
      assert.deepEqual(discovery.stdout.trim().split(/\r?\n/u), [
        path.relative(root, path.join(directory, "sentinel.ts")),
      ]);
      const report = run(command);
      assert.equal(report.status, status, report.stderr || report.stdout);
      const findings = report.stderr.split(/\r?\n/u).filter(Boolean);
      assert.equal(findings.length, status);
      if (status) {
        assert.ok(findings[0].includes(rule));
        assert.ok(findings[0].includes(`Component.astro:${line}:`));
      }
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
}
