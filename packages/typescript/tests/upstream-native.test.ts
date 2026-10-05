import {
  mkdtempSync,
  readFileSync,
  writeFileSync,
  mkdirSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { expect, it } from "vitest";
import globals from "globals";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);

interface Control {
  code: string;
  options?: unknown[];
}
interface Fixture {
  rule: string;
  valid: Control;
  invalid: Control;
}
const corpus = JSON.parse(
  readFileSync(
    new URL("./upstream-unicorn-controls.json", import.meta.url),
    "utf8",
  ),
) as { fixtures: Fixture[] };

it("runs licensed Unicorn positive and negative upstream controls through stock Oxlint", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-native-upstream-"));
  try {
    mkdirSync(path.join(directory, "valid"));
    mkdirSync(path.join(directory, "invalid"));
    const overrides = [];
    for (const fixture of corpus.fixtures) {
      for (const kind of ["valid", "invalid"] as const) {
        const relative = `${kind}/${fixture.rule}.tsx`;
        const code = fixture[kind].code;
        const script =
          fixture.rule === "no-exports-in-scripts" ||
          (
            fixture[kind] as Control & {
              languageOptions?: { sourceType?: string };
            }
          ).languageOptions?.sourceType === "script";
        const moduleCode = script ? code : `${code}\nexport {};`;
        writeFileSync(path.join(directory, relative), moduleCode);
        overrides.push({
          files: [relative],
          rules: {
            [`port/${fixture.rule}`]: [
              "error",
              ...(fixture[kind].options ?? []),
            ],
          },
        });
      }
    }
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        env: { browser: true, node: true, es2024: true },
        globals: Object.fromEntries(
          Object.keys({ ...globals.builtin, ...globals.node }).map((name) => [
            name,
            "readonly",
          ]),
        ),
        jsPlugins: [
          {
            name: "port",
            specifier: path.join(packageRoot, "dist/upstream/unicorn.js"),
          },
        ],
        overrides,
      }),
    );
    const run = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--format=json", "valid", "invalid"],
      { cwd: directory, encoding: "utf8", timeout: 60_000 },
    );
    expect(run).toMatchObject({ stderr: "", status: 1 });
    const result = JSON.parse(run.stdout) as {
      diagnostics: Array<{ filename: string; code?: string; message: string }>;
    };
    expect(result.diagnostics.filter((item) => !item.code)).toEqual([]);
    expect(
      result.diagnostics.filter((item) => item.filename.startsWith("valid/")),
    ).toEqual([]);
    const missing = [];
    for (const fixture of corpus.fixtures) {
      const failures = result.diagnostics.filter(
        (item) => item.filename === `invalid/${fixture.rule}.tsx`,
      );
      if (!failures.some((item) => item.code === `port(${fixture.rule})`))
        missing.push(fixture.rule);
    }
    expect(missing).toEqual([]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 60_000);

const otherControls = [
  {
    family: "core",
    rule: "no-octal",
    extension: "cjs",
    valid: "const value=0o71; module.exports=value;",
    invalid: "const value=071; module.exports=value;",
  },
  {
    family: "core",
    rule: "no-dupe-args",
    extension: "cjs",
    valid:
      "function repeated(left,right){return left+right;} module.exports=repeated;",
    invalid:
      "function repeated(value,value){return value;} module.exports=repeated;",
  },
  {
    family: "node",
    rule: "prefer-promises-fs",
    valid: 'import {readFile} from "node:fs/promises"; readFile("a");',
    invalid: 'import {readFile} from "node:fs"; readFile("a", ()=>{});',
  },
  {
    family: "node",
    rule: "prefer-promises-fs",
    valid: 'const fs = require("node:fs/promises"); fs.readFile("a");',
    invalid: 'const fs = require("node:fs"); fs.readFile("a", ()=>{});',
  },
  {
    family: "node",
    rule: "prefer-promises-fs",
    valid: 'const fs = {readFile(){}}; fs.readFile("a", ()=>{});',
    invalid:
      'const fs = process.getBuiltinModule("fs"); fs.readFile("a", ()=>{});',
  },
  {
    family: "node",
    rule: "prefer-promises-fs",
    valid: 'import * as fs from "fs"; fs.readFileSync("a");',
    invalid:
      'import * as fs from "fs"; const read = fs.readFile; read("a", ()=>{});',
  },
  {
    family: "typescript",
    rule: "naming-convention",
    valid: "const camelCase = 1;",
    invalid: "const bad_name = 1;",
    options: [{ selector: "variable", format: ["camelCase"] }],
  },
  {
    family: "typescript",
    rule: "naming-convention",
    valid: "const handleRequest = () => {};",
    invalid: "const bad_name = () => {};",
    options: [
      { selector: "variable", types: ["function"], format: ["camelCase"] },
    ],
  },
  {
    family: "typescript",
    rule: "naming-convention",
    valid: "const UPPER_CASE = {};",
    invalid: "const lowerCase = {};",
    options: [
      { selector: "variable", types: ["function"], format: ["camelCase"] },
      { selector: "variable", format: ["UPPER_CASE"] },
    ],
  },
  {
    family: "typescript",
    rule: "member-ordering",
    valid: "class Item { field = 1; method() {} }",
    invalid: "class Item { method() {} field = 1; }",
    options: [
      {
        default: {
          memberTypes: ["public-instance-field", "public-instance-method"],
        },
      },
    ],
  },
  {
    family: "typescript",
    rule: "member-ordering",
    valid:
      "abstract class Item { abstract field: string; abstract method(): void; }",
    invalid:
      "abstract class Item { abstract method(): void; abstract field: string; }",
    options: [
      {
        default: {
          memberTypes: ["public-abstract-field", "public-abstract-method"],
        },
      },
    ],
  },
  {
    family: "perfectionist",
    rule: "sort-interfaces",
    valid: "interface Item { a: number; z: number; }",
    invalid: "interface Item { z: number; a: number; }",
  },
  {
    family: "perfectionist",
    rule: "sort-jsx-props",
    valid: "const element = <Card a={1} z={2}/>;",
    invalid: "const element = <Card z={2} a={1}/>;",
  },
  {
    family: "perfectionist",
    rule: "sort-union-types",
    valid: 'type Item = "a" | "z";',
    invalid: 'type Item = "z" | "a";',
  },
  {
    family: "simple-import-sort",
    rule: "imports",
    valid: 'import a from "a";\nimport z from "z";',
    invalid: 'import z from "z";\nimport a from "a";',
  },
  {
    family: "simple-import-sort",
    rule: "exports",
    valid: 'export * from "a";\nexport * from "z";',
    invalid: 'export * from "z";\nexport * from "a";',
  },
  {
    family: "zod",
    rule: "no-any-schema",
    valid: 'import {z} from "zod"; z.string();',
    invalid: 'import {z} from "zod"; z.any();',
  },
  {
    family: "zod",
    rule: "no-coerce-boolean",
    valid: 'import {z} from "zod"; z.boolean();',
    invalid: 'import {z} from "zod"; z.coerce.boolean();',
  },
  {
    family: "zod",
    rule: "no-conflicting-checks",
    valid: 'import {z} from "zod"; z.number().min(1).max(10);',
    invalid: 'import {z} from "zod"; z.number().min(10).max(1);',
  },
  {
    family: "zod",
    rule: "no-duplicate-schema-methods",
    valid: 'import {z} from "zod"; z.string().min(1);',
    invalid: 'import {z} from "zod"; z.string().min(1).min(1);',
  },
  {
    family: "zod",
    rule: "no-throw-in-refine",
    valid:
      'import {z} from "zod"; z.string().refine(value => value.length > 0);',
    invalid:
      'import {z} from "zod"; z.string().refine(value => { throw new Error(value); });',
  },
  {
    family: "zod",
    rule: "no-transform-in-record-key",
    valid: 'import {z} from "zod"; z.record(z.string(), z.string());',
    invalid:
      'import {z} from "zod"; z.record(z.string().transform(value => value.toUpperCase()), z.string());',
  },
  {
    family: "zod",
    rule: "prefer-enum-over-literal-union",
    valid: 'import {z} from "zod"; z.enum(["a", "b"]);',
    invalid:
      'import {z} from "zod"; z.union([z.literal("a"), z.literal("b")]);',
  },
  {
    family: "zod",
    rule: "prefer-nullish",
    valid: 'import {z} from "zod"; z.string().nullish();',
    invalid: 'import {z} from "zod"; z.string().nullable().optional();',
  },
  {
    family: "node-test",
    rule: "no-assert-throws-async",
    valid:
      'import assert from "node:assert/strict"; assert.rejects(async () => { throw new Error(); });',
    invalid:
      'import assert from "node:assert/strict"; assert.throws(async () => { throw new Error(); });',
  },
  {
    family: "node-test",
    rule: "no-assert-throws-multiple-statements",
    valid:
      'import assert from "node:assert/strict"; assert.throws(() => operation());',
    invalid:
      'import assert from "node:assert/strict"; assert.throws(() => { first(); second(); });',
  },
  {
    family: "node-test",
    rule: "no-unneeded-async-rejects-callback",
    valid:
      'import assert from "node:assert/strict"; assert.rejects(() => operation());',
    invalid:
      'import assert from "node:assert/strict"; async function operation(){} assert.rejects(async () => await operation());',
  },
  {
    family: "node-test",
    rule: "no-useless-assertion",
    valid:
      'import assert from "node:assert/strict"; assert.equal(actual, expected);',
    invalid:
      'import assert from "node:assert/strict"; assert.doesNotThrow(() => operation());',
  },
  {
    family: "react",
    rule: "jsx-no-leaked-render",
    valid: "const element = <div>{Boolean(count) && <span />}</div>;",
    invalid: "const element = <div>{count && <span />}</div>;",
    options: [{ validStrategies: ["coerce"] }],
  },
  {
    family: "react",
    rule: "no-invalid-html-attribute",
    valid: 'const element = <a rel="noopener noreferrer"/>;',
    invalid: 'const element = <a rel="invented"/>;',
  },
  {
    family: "shadcn",
    rule: "no-restyle",
    valid:
      'import {Button} from "@/components/ui/button"; const element=<Button />;',
    invalid:
      'import {Button} from "@/components/ui/button"; const element=<Button className="bg-red-500" />;',
  },
  {
    family: "shadcn",
    rule: "no-arbitrary-values",
    valid: 'const element=<div className="w-4"/>;',
    invalid: 'const element=<div className="w-[37px]"/>;',
  },
  {
    family: "shadcn",
    rule: "no-inline-styles",
    valid: 'const element=<div className="p-2"/>;',
    invalid: "const element=<div style={{padding:2}}/>;",
  },
  {
    family: "shadcn",
    rule: "no-unknown-classes",
    valid: 'const element=<div className="p-2"/>;',
    invalid: 'const element=<div className="invented-unknown-class"/>;',
  },
  {
    family: "shadcn",
    rule: "require-static-classes",
    valid:
      'import {Button} from "@/components/ui/button"; const element=<Button className="m-2"/>;',
    invalid:
      'import {Button} from "@/components/ui/button"; const element=<Button className={dynamicClasses}/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "no-conflicting-classes",
    valid: 'const element=<div className="p-2 m-4"/>;',
    invalid: 'const element=<div className="p-2 p-4"/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "no-duplicate-classes",
    valid: 'const element=<div className="p-2"/>;',
    invalid: 'const element=<div className="p-2 p-2"/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "no-deprecated-classes",
    valid: 'const element=<div className="grow"/>;',
    invalid: 'const element=<div className="flex-grow"/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "no-unnecessary-whitespace",
    valid: 'const element=<div className="p-2 m-4"/>;',
    invalid: 'const element=<div className=" p-2  m-4 "/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "enforce-shorthand-classes",
    valid: 'const element=<div className="size-4"/>;',
    invalid: 'const element=<div className="w-4 h-4"/>;',
  },
  {
    family: "better-tailwindcss",
    rule: "enforce-consistent-variable-syntax",
    valid: 'const element=<div className="bg-(--color)"/>;',
    invalid: 'const element=<div className="bg-[var(--color)]"/>;',
    options: [
      {
        syntax: "shorthand",
      },
    ],
  },
];

it("runs native type, sorting, Zod, Node test and React policies with positive and negative controls", () => {
  const directory = mkdtempSync(
    path.join(packageRoot, ".sarj-native-families-"),
  );
  try {
    mkdirSync(path.join(directory, "components/ui"), { recursive: true });
    writeFileSync(
      path.join(directory, "components/ui/button.tsx"),
      "export const Button = ({ className }) => <button className={className} />;",
    );
    writeFileSync(
      path.join(directory, "components.json"),
      JSON.stringify({
        aliases: { ui: "@/components/ui" },
        tailwind: { css: "global.css" },
      }),
    );
    writeFileSync(
      path.join(directory, "tsconfig.json"),
      JSON.stringify({
        compilerOptions: { baseUrl: ".", paths: { "@/*": ["./*"] } },
      }),
    );
    writeFileSync(path.join(directory, "global.css"), '@import "tailwindcss";');
    const families = [...new Set(otherControls.map((item) => item.family))];
    const jsPlugins = families.map((name) => ({
      name: `port-${name}`,
      specifier:
        name === "shadcn"
          ? fileURLToPath(import.meta.resolve("@sarj/oxlint-plugin/upstream/shadcn"))
          : name === "better-tailwindcss"
            ? fileURLToPath(
                import.meta.resolve("@sarj/oxlint-plugin/upstream/better-tailwindcss"),
              )
            : path.join(packageRoot, `dist/upstream/${name}.js`),
    }));
    const overrides = [];
    for (const [index, control] of otherControls.entries()) {
      for (const kind of ["valid", "invalid"] as const) {
        const filename = `${kind}-${index}.${"extension" in control ? control.extension : "tsx"}`;
        writeFileSync(
          path.join(directory, filename),
          "extension" in control
            ? control[kind]
            : `${control[kind]}\nexport {};`,
        );
        overrides.push({
          files: [filename],
          rules: {
            [`port-${control.family}/${control.rule}`]: [
              "error",
              ...("options" in control ? control.options : []),
            ],
          },
        });
      }
    }
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        env: { browser: true, node: true, es2024: true },
        globals: Object.fromEntries(
          Object.keys({ ...globals.builtin, ...globals.node }).map((name) => [
            name,
            "readonly",
          ]),
        ),
        jsPlugins,
        overrides,
      }),
    );
    const run = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--format=json", "."],
      { cwd: directory, encoding: "utf8", timeout: 60_000 },
    );
    expect(run).toMatchObject({ stderr: "", status: 1 });
    const result = JSON.parse(run.stdout) as {
      diagnostics: Array<{ filename: string; code?: string }>;
    };
    expect(result.diagnostics.filter((item) => !item.code)).toEqual([]);
    expect(
      result.diagnostics.filter((item) => item.filename.startsWith("valid-")),
    ).toEqual([]);
    const missing = otherControls.flatMap((control, index) =>
      result.diagnostics.some(
        (item) =>
          item.filename ===
            `invalid-${index}.${"extension" in control ? control.extension : "tsx"}` &&
          item.code === `port-${control.family}(${control.rule})`,
      )
        ? []
        : [`port-${control.family}/${control.rule}`],
    );
    expect(missing).toEqual([]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 60_000);

it("preserves Bun matcher imports, aliases, shadowing, primitive checks and stable upstream fixes", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-native-bun-"));
  const valid = [
    'import {expect} from "bun:test"; expect(value).toBe(1);',
    'import {expect} from "bun:test"; expect(value).toEqual({value:1});',
    'import {expect} from "bun:test"; expect(value).toEqual(/text/);',
    'import {expect} from "other"; expect(value).toEqual(1);',
    "const expect = factory(); expect(value).toEqual(1);",
    'import {expect} from "bun:test"; function check(expect){expect(value).toEqual(1)}',
  ];
  const invalid = [
    'import {expect} from "bun:test"; expect(value).toEqual(1);',
    'import {expect as check} from "bun:test"; check(value).toStrictEqual(-1);',
    'import {expect} from "bun:test"; expect(value)["toEqual"](`text`);',
    'import {expect} from "bun:test"; expect(value).toEqual(null);',
    'import {expect} from "bun:test"; expect(value).not.toEqual(undefined);',
    'import {expect} from "bun:test"; expect(value).toEqual(NaN);',
    'import {expect} from "bun:test"; expect(value).not.toBeDefined();',
    'const {expect:check}=require("bun:test"); check(value).toEqual(true);',
    'const {expect}=await import("bun:test"); expect(value).resolves.toEqual(1);',
  ];
  try {
    for (const [kind, controls] of [
      ["valid", valid],
      ["invalid", invalid],
    ] as const)
      controls.forEach((code, index) =>
        writeFileSync(
          path.join(directory, `${kind}-${index}.ts`),
          `${code}\nexport {};`,
        ),
      );
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        jsPlugins: [
          {
            name: "sarj-bun",
            specifier: path.join(packageRoot, "dist/upstream/bun.js"),
          },
        ],
        rules: { "sarj-bun/prefer-to-be": "error" },
      }),
    );
    const run = (fix = false) =>
      spawnSync(
        process.execPath,
        [
          engine,
          "--config",
          "oxlint.json",
          "--format=json",
          ...(fix ? ["--fix"] : []),
          ".",
        ],
        { cwd: directory, encoding: "utf8", timeout: 60_000 },
      );
    const first = run();
    expect(first).toMatchObject({ stderr: "", status: 1 });
    const diagnostics = JSON.parse(first.stdout).diagnostics as Array<{
      filename: string;
      code: string;
    }>;
    expect(diagnostics).toHaveLength(invalid.length);
    expect(
      diagnostics.every(
        (item) =>
          item.filename.startsWith("invalid-") &&
          item.code === "sarj-bun(prefer-to-be)",
      ),
    ).toBe(true);
    const fixed = run(true);
    expect(fixed).toMatchObject({ stderr: "", status: 0 });
    expect(JSON.parse(fixed.stdout).diagnostics).toEqual([]);
    expect(
      readFileSync(path.join(directory, "invalid-4.ts"), "utf8"),
    ).toContain("expect(value).toBeDefined()");
    const afterFix = invalid.map((_, index) =>
      readFileSync(path.join(directory, `invalid-${index}.ts`), "utf8"),
    );
    expect(run(true).status).toBe(0);
    expect(
      invalid.map((_, index) =>
        readFileSync(path.join(directory, `invalid-${index}.ts`), "utf8"),
      ),
    ).toEqual(afterFix);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("loads the complete public policy from its own package dependencies and preserves clean and failing consumer fixtures", async () => {
  const { createStrictOxlintConfig } = await import("../dist/config.js");
  const directory = mkdtempSync(path.join(packageRoot, ".sarj-public-policy-"));
  try {
    const config = await createStrictOxlintConfig({
      root: directory,
      typeAware: false,
      testFrameworks: [
        "vitest",
        "bun",
        "node",
        "testing-library",
        "playwright",
      ],
    });
    writeFileSync(path.join(directory, "oxlint.json"), JSON.stringify(config));
    writeFileSync(
      path.join(directory, "sample-schema.tsx"),
      'import { z } from "zod";\nexport const SampleSchema = z.string();\n',
    );
    writeFileSync(
      path.join(directory, "sample.bun.test.ts"),
      'import { expect } from "bun:test"; expect(actual).toBe(expected);\n',
    );
    const run = () =>
      spawnSync(
        process.execPath,
        [engine, "--config", "oxlint.json", "--format=json", "."],
        {
          cwd: directory,
          encoding: "utf8",
          timeout: 60_000,
        },
      );
    expect(run()).toMatchObject({ stderr: "", status: 0 });
    writeFileSync(
      path.join(directory, "sample-schema.tsx"),
      'import { z } from "zod";\nexport const SampleSchema = z.any();\n',
    );
    writeFileSync(
      path.join(directory, "sample.bun.test.ts"),
      'import { expect } from "bun:test"; expect(actual).toEqual(1);\n',
    );
    writeFileSync(
      path.join(directory, "dynamic.js"),
      "new Function('return 1;'); setTimeout('throw Error()', 1);",
    );
    const failing = run();
    expect(failing).toMatchObject({ stderr: "", status: 1 });
    const diagnostics = JSON.parse(failing.stdout).diagnostics as Array<{
      code?: string;
    }>;
    expect(diagnostics.filter((item) => !item.code)).toEqual([]);
    expect(diagnostics.map((item) => item.code)).toEqual(
      expect.arrayContaining([
        "zod(no-any-schema)",
        "sarj-bun(prefer-to-be)",
        "eslint(no-new-func)",
        "eslint(no-implied-eval)",
      ]),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("runs the original Astro recommended script policies in actual extracted frontmatter", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-native-astro-"));
  const controls = [
    {
      rule: "no-deprecated-astro-canonicalurl",
      valid: "const value = Astro.url;",
      invalid: "const value = Astro.canonicalURL;",
    },
    {
      rule: "no-deprecated-astro-fetchcontent",
      valid: "const value = await Astro.glob('./*.md');",
      invalid: "const value = await Astro.fetchContent('./*.md');",
    },
    {
      rule: "no-deprecated-astro-resolve",
      valid: "const value = Astro.url;",
      invalid: "const value = Astro.resolve('./image.svg');",
    },
    {
      rule: "no-deprecated-getentrybyslug",
      valid: 'import {getEntry} from "astro:content";',
      invalid: 'import {getEntryBySlug as getPage} from "astro:content";',
    },
    {
      rule: "no-exports-from-components",
      valid:
        "export const partial = true; export interface Props {title:string}",
      invalid: "export const title = 'component';",
    },
    {
      rule: "no-prerender-export-outside-pages",
      valid: "const prerender = true;",
      invalid: "export const prerender = true;",
    },
  ];
  try {
    const overrides = [];
    for (const [index, control] of controls.entries()) {
      for (const kind of ["valid", "invalid"] as const) {
        const filename = `${kind}-${index}.astro`;
        writeFileSync(
          path.join(directory, filename),
          `---\n${control[kind]}\n---\n<div />`,
        );
        overrides.push({
          files: [filename],
          rules: { [`port/${control.rule}`]: "error" },
        });
      }
    }
    writeFileSync(
      path.join(directory, "shadow.astro"),
      "---\nconst Astro = {canonicalURL:'url',fetchContent(){},resolve(){}}; Astro.canonicalURL; Astro.fetchContent(); Astro.resolve();\n---\n<div />",
    );
    mkdirSync(path.join(directory, "pages"));
    writeFileSync(
      path.join(directory, "pages/index.astro"),
      "---\nexport const prerender = true;\n---\n<div />",
    );
    writeFileSync(
      path.join(directory, "ordinary.ts"),
      "export const title = Astro.canonicalURL; export const prerender=true;",
    );
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        globals: { Astro: "readonly" },
        jsPlugins: [
          {
            name: "port",
            specifier: path.join(packageRoot, "dist/upstream/astro.js"),
          },
        ],
        rules: Object.fromEntries(
          controls.map(({ rule }) => [`port/${rule}`, "off"]),
        ),
        overrides: [
          ...overrides,
          {
            files: ["shadow.astro", "pages/**/*.astro", "ordinary.ts"],
            rules: Object.fromEntries(
              controls.map(({ rule }) => [`port/${rule}`, "error"]),
            ),
          },
        ],
      }),
    );
    const run = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--format=json", "."],
      { cwd: directory, encoding: "utf8", timeout: 60_000 },
    );
    expect(run).toMatchObject({ stderr: "", status: 1 });
    const result = JSON.parse(run.stdout) as {
      diagnostics: Array<{ filename: string; code?: string }>;
    };
    expect(
      result.diagnostics.filter(
        (diagnostic) =>
          !diagnostic.code || !diagnostic.filename.startsWith("invalid-"),
      ),
    ).toEqual([]);
    expect(
      controls.filter(
        (control, index) =>
          !result.diagnostics.some(
            (diagnostic) =>
              diagnostic.filename === `invalid-${index}.astro` &&
              diagnostic.code === `port(${control.rule})`,
          ),
      ),
    ).toEqual([]);
    const fixed = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--fix", "invalid-1.astro"],
      { cwd: directory, encoding: "utf8", timeout: 60_000 },
    );
    expect(fixed).toMatchObject({ stderr: "", status: 0 });
    const fixedSource = readFileSync(
      path.join(directory, "invalid-1.astro"),
      "utf8",
    );
    expect(fixedSource).toContain("Astro.glob(");
    const second = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--fix", "invalid-1.astro"],
      { cwd: directory, encoding: "utf8", timeout: 60_000 },
    );
    expect(second).toMatchObject({ stderr: "", status: 0 });
    expect(readFileSync(path.join(directory, "invalid-1.astro"), "utf8")).toBe(
      fixedSource,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 60_000);
