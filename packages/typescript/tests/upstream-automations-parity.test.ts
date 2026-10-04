import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../src/create-strict-oxlint-config.js";

const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const upstream = fileURLToPath(
  new URL("../src/upstream/unicorn.js", import.meta.url),
);
const conversionControls = [
  [
    "typed-array",
    "const digest=new Uint8Array([255]);const hex=[...digest.slice(0,1)].map(byte=>byte.toString(16));",
    "",
  ],
  [
    "array",
    "const values=[1,2];const copy=[...values.slice(0,1)];",
    "no-useless-spread",
  ],
  [
    "dynamic-fetch",
    'async function api(method,body){return fetch("https://example.invalid",{body:body===undefined?undefined:JSON.stringify(body),method});}',
    "",
  ],
  [
    "get",
    'fetch("https://example.invalid",{body:"body",method:"GET"});',
    "no-invalid-fetch-options",
  ],
  [
    "head",
    'fetch("https://example.invalid",{body:"body",method:"HEAD"});',
    "no-invalid-fetch-options",
  ],
  ["post", 'fetch("https://example.invalid",{body:"body",method:"POST"});', ""],
  [
    "default-method",
    'fetch("https://example.invalid",{body:"body"});',
    "no-invalid-fetch-options",
  ],
  ["no-body", 'fetch("https://example.invalid",{method:"GET"});', ""],
] as const;
const guardControls = [
  [
    "throw-call",
    "function run(a,b){if(a)throw failure();if(b)throw failure();}",
    "",
  ],
  [
    "return-binding",
    "function run(a,b,value){if(a)return value;if(b)return value;}",
    "",
  ],
  [
    "literal-throw",
    "function run(a,b){if(a)throw 1;if(b)throw 1;}",
    "prefer-combined-guards",
  ],
  [
    "literal-return",
    "function run(a,b){if(a)return 1;if(b)return 1;}",
    "prefer-combined-guards",
  ],
  [
    "empty-return",
    "function run(a,b){if(a)return;if(b)return;}",
    "prefer-combined-guards",
  ],
  [
    "compound-default",
    "function run(a,b,c){if(a&&b)return 1;if(c)return 1;}",
    "",
  ],
  ["different-exits", "function run(a,b){if(a)return 1;if(b)return 2;}", ""],
  ["tagged", "function run(a,b){if(a)return tag`a`;if(b)return tag`a`;}", ""],
  [
    "labels",
    "function run(a,b){label:while(true){if(a)break label;if(b)break label;}}",
    "prefer-combined-guards",
  ],
  [
    "continue",
    "function run(a,b){while(true){if(a)continue;if(b)continue;}}",
    "prefer-combined-guards",
  ],
  ["comment", "function run(a,b){if(a)return 1;/*reason*/if(b)return 1;}", ""],
  [
    "process-literal",
    "function run(a,b){if(a)process.exit(1);if(b)process.exit(1);}",
    "prefer-combined-guards",
  ],
  [
    "process-empty",
    "function run(a,b){if(a)process.exit();if(b)process.exit();}",
    "prefer-combined-guards",
  ],
  [
    "process-binding",
    "function run(a,b,code){if(a)process.exit(code);if(b)process.exit(code);}",
    "",
  ],
] as const;
const moduleControls = [
  ["sole-marker", "export {};", ""],
  [
    "runtime-export",
    "export const value=1;export {};",
    "require-module-specifiers",
  ],
  ["repeated-markers", "export {};export {};", "require-module-specifiers"],
  ["empty-import", 'import {} from "module";', "require-module-specifiers"],
  ["side-effect-import", 'import "module";', ""],
] as const;

function writeConfig(directory: string, rules: Record<string, unknown>) {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      env: { node: true },
      jsPlugins: [{ name: "sarj-unicorn", specifier: upstream }],
      rules,
    }),
  );
}
function lint(directory: string, flags: string[] = []) {
  return spawnSync(
    process.execPath,
    [engine, "--config", "oxlint.json", "--format=json", ...flags, "."],
    {
      cwd: directory,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
}
function verifyControls(
  controls: ReadonlyArray<readonly [string, string, string]>,
  rules: Record<string, unknown>,
) {
  const directory = mkdtempSync(
    path.join(tmpdir(), "sarj-automations-parity-"),
  );
  try {
    writeConfig(directory, rules);
    for (const [name, source] of controls)
      for (const extension of ["ts", "mjs"])
        writeFileSync(path.join(directory, `${name}.${extension}`), source);
    const result = lint(directory);
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(result.stdout) as {
      diagnostics: Array<{ filename: string; code: string }>;
    } & Record<"number_of_files", number>;
    expect(report["number_of_files"]).toBe(controls.length * 2);
    expect(
      report.diagnostics
        .map(({ filename, code }) => `${filename}:${code}`)
        .toSorted(),
    ).toEqual(
      controls
        .flatMap(([name, , rule]) =>
          rule === ""
            ? []
            : ["ts", "mjs"].map(
                (extension) => `${name}.${extension}:sarj-unicorn(${rule})`,
              ),
        )
        .toSorted(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

it("preserves typed-array conversion and unknown fetch methods while rejecting actual redundant spreads and invalid bodies", () => {
  verifyControls(conversionControls, {
    "sarj-unicorn/no-useless-spread": "error",
    "sarj-unicorn/no-invalid-fetch-options": "error",
  });
});

it("combines proven literal and empty exits while retaining uncertain exits and default compound-condition exclusions", () => {
  verifyControls(guardControls, {
    "sarj-unicorn/prefer-combined-guards": "error",
  });
});

it("retains sole module markers and side-effect imports while rejecting redundant markers and empty import specifiers", () => {
  verifyControls(moduleControls, {
    "sarj-unicorn/require-module-specifiers": "error",
  });
});

it("removes redundant module markers without deleting the sole marker and produces stable fixes", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-module-fix-"));
  try {
    writeConfig(directory, {
      "sarj-unicorn/require-module-specifiers": "error",
    });
    const sources = {
      "sole.ts": "export {};",
      "runtime.ts": "export const value=1;export {};",
      "repeated.ts": "export {};export {};",
    };
    for (const [name, source] of Object.entries(sources))
      writeFileSync(path.join(directory, name), source);
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 0, stderr: "" });
    expect(readFileSync(path.join(directory, "sole.ts"), "utf8")).toBe(
      "export {};",
    );
    expect(readFileSync(path.join(directory, "runtime.ts"), "utf8")).toBe(
      "export const value=1;",
    );
    expect(readFileSync(path.join(directory, "repeated.ts"), "utf8")).toBe(
      "export {};",
    );
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 0, stderr: "" });
    expect(readFileSync(path.join(directory, "sole.ts"), "utf8")).toBe(
      "export {};",
    );
    expect(readFileSync(path.join(directory, "runtime.ts"), "utf8")).toBe(
      "export const value=1;",
    );
    expect(readFileSync(path.join(directory, "repeated.ts"), "utf8")).toBe(
      "export {};",
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("retains explicit compound-condition checking and stable safe fixes without changing uncertain exits", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-automations-fix-"));
  try {
    writeConfig(directory, {
      "sarj-unicorn/prefer-combined-guards": [
        "error",
        { checkCompoundConditions: true },
      ],
      "sarj-unicorn/no-useless-spread": "error",
    });
    const file = path.join(directory, "sample.ts");
    writeFileSync(
      file,
      "const values=[1,2];const copy=[...[1,2]];const clone=[...values.slice(0,1)];function literal(a,b,c){if(a&&b)return 1;if(c)return 1;}function uncertain(a,b){if(a)throw failure();if(b)throw failure();}",
    );
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 1, stderr: "" });
    const fixed = readFileSync(file, "utf8");
    expect(fixed).toContain("copy=[1,2]");
    expect(fixed).toContain("clone=[...values.slice(0,1)]");
    expect(fixed).toContain("if ((a&&b) || c)return 1;");
    expect(fixed).toContain("if(a)throw failure();if(b)throw failure();");
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 1, stderr: "" });
    expect(readFileSync(file, "utf8")).toBe(fixed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("selects one shared authority for spread and fetch rules without changing original severities or options", async () => {
  const config = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
  });
  expect(config.rules).toMatchObject({
    "unicorn/no-useless-spread": "off",
    "unicorn/no-invalid-fetch-options": "off",
    "unicorn/require-module-specifiers": "off",
    "sarj-unicorn/no-useless-spread": "error",
    "sarj-unicorn/no-invalid-fetch-options": "error",
    "sarj-unicorn/require-module-specifiers": "error",
  });
});
