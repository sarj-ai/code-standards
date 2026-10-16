import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import ts from "typescript";
import { record } from "../../standards/src/sarj_standards/configs/tool-json.mts";
import { describe, expect, it } from "vitest";

import { eslintRuleSetting } from "../eslint-rule-setting.ts";

const REPOSITORY_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const ESLINT_CLI = fileURLToPath(
  new URL("../node_modules/eslint/bin/eslint.js", import.meta.url),
);
const PARSER_MODULE = new URL(
  "../node_modules/@typescript-eslint/parser/dist/index.js",
  import.meta.url,
).href;

it("immutable policy options survive native ESLint configuration normalization", async () => {
  const options = Object.freeze({
    selector: "Identifier[name=blocked]",
    message: "preserved option",
  });
  const policy = Object.freeze(["error", options] as const);
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: [
      { rules: { "no-restricted-syntax": eslintRuleSetting(policy) } },
    ],
  });
  const [result] = await eslint.lintText("const blocked = 1;", {
    filePath: "example.js",
  });
  expect(
    result?.messages.map(({ ruleId, message }) => ({ ruleId, message })),
  ).toEqual([{ ruleId: "no-restricted-syntax", message: "preserved option" }]);
  expect(policy).toEqual(["error", options]);
  expect(Object.isFrozen(options)).toBe(true);
});

describe("native runtime support for migrated tooling", () => {
  it.each(["ts", "mts", "cts"])(
    "ESLint loads a typed .%s entrypoint with the pinned loader",
    async (suffix) => {
      const directory = await mkdtemp(
        join(await realpath(tmpdir()), "sarj-typed-eslint-"),
      );
      try {
        const config = join(directory, `eslint.config.${suffix}`);
        const source = join(directory, "sample.ts");
        await writeFile(
          config,
          `import parser from ${JSON.stringify(PARSER_MODULE)};\nconst severity: "warn" = "warn";\nexport default [{files:["**/*.ts"],languageOptions:{parser},rules:{"no-restricted-syntax":[severity,{selector:"Identifier[name=blocked]",message:"typed options applied"}]}}];\n`,
        );
        await writeFile(source, "const blocked: number = 1;\n");
        const output = execFileSync(
          process.execPath,
          [ESLINT_CLI, "--config", config, "--format", "json", source],
          { cwd: directory, encoding: "utf8" },
        );
        const results: unknown = JSON.parse(output);
        expect(results).toEqual([
          expect.objectContaining({
            warningCount: 1,
            fatalErrorCount: 0,
            messages: [
              expect.objectContaining({
                ruleId: "no-restricted-syntax",
                message: "typed options applied",
              }),
            ],
          }),
        ]);
      } finally {
        await rm(directory, { recursive: true, force: true });
      }
    },
  );

  it("executes the typed tsconfig control without a transpiler or emitted JavaScript", () => {
    expect(() =>
      execFileSync(
        process.execPath,
        [
          join(REPOSITORY_ROOT, ".github/scripts/ci-validate-tsconfig.mts"),
          join(REPOSITORY_ROOT, "packages/tsconfig"),
        ],
        { encoding: "utf8" },
      ),
    ).not.toThrow();
  });

  it("executes the typed immutable import analyzer while retaining runtime attestation", async () => {
    const script = join(
      REPOSITORY_ROOT,
      "packages/standards/src/sarj_standards/libs/repository/rule_imports.mts",
    );
    const compiler = fileURLToPath(
      new URL("../node_modules/typescript/lib/typescript.js", import.meta.url),
    );
    const metadata = record(
      JSON.parse(
        await readFile(
          new URL("../node_modules/typescript/package.json", import.meta.url),
          "utf8",
        ),
      ) as unknown,
      "compiler metadata",
    );
    const packageVersion = metadata["version"];
    if (typeof packageVersion !== "string")
      throw new TypeError("Compiler package version must be a string");
    const input = JSON.stringify({
      "entry.ts": "export { value } from './helper.js';",
      "helper.ts": "export const value = 1;",
    });
    const arguments_ = [
      script,
      compiler,
      process.version,
      packageVersion,
      ts.version,
    ];
    const output = execFileSync(process.execPath, arguments_, {
      input,
      encoding: "utf8",
    });
    const dependencies: unknown = JSON.parse(output);
    expect(dependencies).toEqual({
      "entry.ts": {
        error: null,
        imports: [{ specifier: "./helper.js", resolved: "helper.ts" }],
      },
      "helper.ts": { error: null, imports: [] },
    });
    expect(() =>
      execFileSync(
        process.execPath,
        [script, compiler, "v0.0.0", packageVersion, ts.version],
        { input, encoding: "utf8", stdio: "pipe" },
      ),
    ).toThrow();
  });

  it("imports the wheel formatter through Node's native .mts support", () => {
    const formatter = new URL(
      "../../../packages/standards/src/sarj_standards/configs/eslint-compact-formatter.mts",
      import.meta.url,
    ).href;
    const output = execFileSync(
      process.execPath,
      [
        "--input-type=module",
        "--eval",
        `import format from ${JSON.stringify(formatter)}; console.log(format([{filePath:'sample.ts',messages:[{line:2,column:3,ruleId:'example/rule',severity:1,message:'preserved warning'}]}]));`,
      ],
      { encoding: "utf8" },
    );
    const results: unknown = JSON.parse(output);
    expect(results).toEqual([
      {
        filePath: "sample.ts",
        messages: [
          {
            line: 2,
            column: 3,
            ruleId: "example/rule",
            severity: 1,
            message: "preserved warning",
          },
        ],
      },
    ]);
  });
});
