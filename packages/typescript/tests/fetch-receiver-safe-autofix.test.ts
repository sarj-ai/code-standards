import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import rule from "../src/rules/no-detached-global-fetch.js";

function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(
    source,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser },
        plugins: { local: { rules: { check: rule } } },
        rules: { "local/check": "error" },
      },
    ],
    { filename: "src/client.ts" },
  );
}

function sources(): { readonly original: string; readonly fixed: string } {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.files[0] === undefined || example.fixedFiles?.[0] === undefined)
    throw new Error("Missing owned fetch fixture");
  return {
    original: example.files[0].source,
    fixed: example.fixedFiles[0].source,
  };
}

function compiled(source: string): string {
  return ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
}

it("fixes and converges on the authored receiver correction", () => {
  const { original, fixed } = sources();
  const first = apply(original),
    second = apply(first.output);
  expect(first.fixed).toBe(true);
  expect(first.output).toBe(fixed);
  expect(first.messages).toEqual([]);
  expect(second.fixed).toBe(false);
  expect(second.messages).toEqual([]);
});

it("repairs an explicitly modeled receiver-sensitive host without claiming a browser run", () => {
  const { original, fixed } = sources();
  const model =
    "function fetch(input) { 'use strict'; if(this!==undefined)throw new TypeError('Modeled incompatible receiver'); return ['realm-global',input]; }\n";
  expect((): unknown =>
    runInNewContext(model + compiled(original) + "\nexports.load();", {
      exports: {},
    }),
  ).toThrow("Modeled incompatible receiver");
  expect(
    runInNewContext(
      model + compiled(fixed) + "\nJSON.stringify(exports.load());",
      { exports: {} },
    ),
  ).toBe(JSON.stringify(["realm-global", "data:text/plain,hello"]));
});

it("retains pinned Node fetch data-URL response status, headers and body", async () => {
  const { original, fixed } = sources();
  const before: unknown = await runInNewContext(
    compiled(original) + "\nexports.load();",
    { exports: {}, fetch },
  );
  const after: unknown = await runInNewContext(
    compiled(fixed) + "\nexports.load();",
    { exports: {}, fetch },
  );
  if (!(before instanceof Response) || !(after instanceof Response))
    throw new Error("Expected canonical Node Response objects");
  expect([
    after.status,
    after.headers.get("content-type"),
    await after.text(),
  ]).toEqual([
    before.status,
    before.headers.get("content-type"),
    await before.text(),
  ]);
});
