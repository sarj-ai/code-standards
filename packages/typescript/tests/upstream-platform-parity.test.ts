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
const controls = [
  ["decimal", 'export const result=parseInt("42",10);', 0, 0],
  ["no-radix", 'export const result=parseInt("42");', 0, 0],
  [
    "local-radix",
    'const radix=10;export const result=parseInt("42",radix);',
    0,
    0,
  ],
  ["hexadecimal", 'export const result=parseInt("ff",16);', 1, 0],
  [
    "unknown-radix",
    'declare const radix:number;export const result=parseInt("ff",radix);',
    1,
    0,
  ],
  ["parse-float", 'export const result=parseFloat("4.2");', 1, 0],
  ["number-method", 'export const result=Number.parseInt("ff",16);', 0, 0],
  ["disabled-constants", "export const result=[Infinity,NaN];", 0, 0],
  [
    "shadowed-parse",
    'export function run(parseInt:(value:string,radix:number)=>number){return parseInt("ff",16);}',
    0,
    0,
  ],
  [
    "false-branch",
    "export function choose(condition:boolean,value:boolean){return condition?value:false;}",
    0,
    1,
  ],
  [
    "true-branch",
    "export function choose(condition:boolean,value:boolean){return condition?value:true;}",
    0,
    1,
  ],
  [
    "unknown-false-branch",
    "export function choose(condition:unknown,value:boolean){return condition?value:false;}",
    0,
    0,
  ],
  [
    "literal-false-test",
    "export function choose(value:boolean){return (value===true)?value:false;}",
    0,
    1,
  ],
  [
    "ordinary-branches",
    "export function choose(condition:boolean,a:number,b:number){return condition?a:b;}",
    0,
    0,
  ],
  [
    "self-reference",
    "export function choose(value:string|undefined,fallback:string){return value?value:fallback;}",
    0,
    1,
  ],
  ["true-literal-overlap", "export const result=true?true:false;", 0, 0],
  ["false-literal-overlap", "export const result=false?false:true;", 0, 0],
] as const;

function lint(directory: string, flags: string[] = []) {
  return spawnSync(
    process.execPath,
    [engine, "--config", "oxlint.json", "--format=json", ...flags, "."],
    { cwd: directory, encoding: "utf8", timeout: 30_000 },
  );
}
function writeConfig(directory: string) {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      jsPlugins: [
        {
          name: "sarj-unicorn",
          specifier: fileURLToPath(
            new URL("../src/upstream/unicorn.js", import.meta.url),
          ),
        },
      ],
      rules: {
        "sarj-unicorn/prefer-number-properties": [
          "error",
          { checkInfinity: false, checkNaN: false },
        ],
        "sarj-unicorn/prefer-logical-operator-over-ternary": "error",
      },
    }),
  );
}

it("matches maintained parseInt radix exemptions and boolean ternary boundaries in real stock workers", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-platform-parity-"));
  try {
    writeConfig(directory);
    for (const [name, source] of controls)
      writeFileSync(path.join(directory, `${name}.ts`), source);
    const result = lint(directory);
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(result.stdout) as {
      diagnostics: Array<{ filename: string; code: string }>;
    } & Record<"number_of_files", number>;
    expect(report["number_of_files"]).toBe(controls.length);
    expect(
      report.diagnostics.map((d) => `${d.filename}:${d.code}`).toSorted(),
    ).toEqual(
      controls
        .flatMap(([name, , number, logical]) => [
          ...Array.from(
            { length: number },
            () => `${name}.ts:sarj-unicorn(prefer-number-properties)`,
          ),
          ...Array.from(
            { length: logical },
            () =>
              `${name}.ts:sarj-unicorn(prefer-logical-operator-over-ternary)`,
          ),
        ])
        .toSorted(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("retains exact upstream fixes and avoids unsafe TypeScript boolean rewrites", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-platform-fix-"));
  try {
    writeConfig(directory);
    const js = path.join(directory, "sample.js");
    const ts = path.join(directory, "sample.ts");
    writeFileSync(
      js,
      'const result=parseInt("ff",16);function choose(value,candidate){return value>0?candidate:false;}',
    );
    const typed =
      "export function choose(condition:boolean,value:boolean){return condition?value:false;}";
    writeFileSync(ts, typed);
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 1, stderr: "" });
    const fixed = readFileSync(js, "utf8");
    expect(fixed).toContain('Number.parseInt("ff",16)');
    expect(fixed).toContain("(value>0) && candidate");
    expect(readFileSync(ts, "utf8")).toBe(typed);
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 1, stderr: "" });
    expect(readFileSync(js, "utf8")).toBe(fixed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("selects one upstream authority while leaving consumer option overrides available", async () => {
  const config = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
  });
  expect(config.rules).toMatchObject({
    "unicorn/prefer-number-properties": "off",
    "unicorn/prefer-logical-operator-over-ternary": "off",
    "sarj-unicorn/prefer-number-properties": "error",
    "sarj-unicorn/prefer-logical-operator-over-ternary": "error",
  });
});
