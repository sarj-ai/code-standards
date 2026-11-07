#!/usr/bin/env node
// Prove the Oxlint plugin bundles no ESLint module.
//
//   node scripts/oxlint/check-port-bundle.ts [entry]   (default src/index.ts)

import { join } from "node:path";

import { build } from "esbuild";

import { PACKAGE_DIR } from "./lib.ts";

const FORBIDDEN_INPUT = /node_modules\/(?:eslint|@eslint|@eslint-community|@typescript-eslint|typescript-eslint|eslint-[^/]+)\//;

await main();

async function main(): Promise<void> {
  const entry = process.argv[2] ?? join(PACKAGE_DIR, "src/index.ts");
  const result = await build({
    entryPoints: [entry],
    bundle: true,
    write: false,
    format: "esm",
    platform: "node",
    target: "node22",
    metafile: true,
    logLevel: "warning",
    absWorkingDir: PACKAGE_DIR,
  });
  const inputs = Object.keys(result.metafile.inputs);
  const forbidden = inputs.filter((input) => FORBIDDEN_INPUT.test(input));
  if (forbidden.length > 0) {
    console.error(`Oxlint plugin bundles ESLint modules:\n  ${forbidden.join("\n  ")}`);
    process.exit(1);
  }
  const externals = Object.values(result.metafile.outputs).flatMap((output) => output.imports.map((imported) => imported.path));
  const packages = [...new Set(inputs.filter((input) => input.includes("node_modules/")).map((input) => input.replace(/^.*node_modules\/((?:@[^/]+\/)?[^/]+).*$/, "$1")))];
  console.log(`ok: ${String(inputs.length)} modules, packages [${packages.join(", ")}], externals [${[...new Set(externals)].join(", ")}]`);
}
