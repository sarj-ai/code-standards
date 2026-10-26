// vitest: shared-module-graph
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import rule from "../src/rules/no-positional-tuple-return.js";

const SOURCE =
  "function download(): [body: string, status: number] { return ['ok', 200]; }\nexport function run(): { body: string; status: number } { const [body, status] = download(); return { body, status }; }";
const FIXED =
  "function download(): { body: string; status: number } { return { body: 'ok', status: 200 }; }\nexport function run(): { body: string; status: number } { const { body, status } = download(); return { body, status }; }";

function configuration(): Linter.Config[] {
  return [
    {
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { local: { rules: { check: rule } } },
      rules: { "local/check": "error" },
    },
  ];
}

function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(source, configuration(), {
    filename: "src/download.ts",
  });
}

it.each(["\n", "\r\n"])(
  "removes the native finding with exact %s edits and convergence",
  (ending) => {
    const source = SOURCE.replaceAll("\n", ending);
    const fixed = FIXED.replaceAll("\n", ending);
    expect(
      new Linter().verify(source, configuration(), {
        filename: "src/download.ts",
      }),
    ).toHaveLength(1);
    const result = apply(source);
    expect(result.fixed).toBe(true);
    expect(result.output).toBe(fixed);
    expect(result.messages).toEqual([]);
    expect(apply(fixed).fixed).toBe(false);
  },
);

it.each([
  SOURCE.replaceAll("body", "内容").replaceAll("status", "状态"),
  SOURCE.replace("'ok'", "'𝄞\\n\\u0000'"),
  SOURCE.replaceAll("status: number", "status: boolean").replace(
    "200",
    "false",
  ),
  SOURCE.replaceAll("body: string", "body: boolean").replace("'ok'", "true"),
])("retains authored names, primitive domains and public output", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(true);
  expect(result.messages).toEqual([]);
  expect(apply(result.output).fixed).toBe(false);
});

it.each([
  "import 'setup';\n" + SOURCE,
  "// preserve ownership\n" + SOURCE,
  SOURCE + "\nexport const other = download;",
  SOURCE.replace("function download", "export function download"),
  SOURCE.replace("function download", "declare function download"),
  SOURCE.replace("function download()", "function download<T>()"),
  SOURCE.replace("function download()", "function download(value = 1)"),
  SOURCE.replace("function download()", "async function download()"),
  SOURCE.replace("function download()", "function* download()"),
  SOURCE.replace("[body: string, status: number]", "[string, number]"),
  SOURCE.replace(
    "[body: string, status: number]",
    "readonly [body: string, status: number]",
  ),
  SOURCE.replace(
    "[body: string, status: number]",
    "[body?: string, status?: number]",
  ),
  SOURCE.replace(
    "[body: string, status: number]",
    "[body: string, body: number]",
  ),
  SOURCE.replace("return ['ok', 200]", "return load()"),
  SOURCE.replace("return ['ok', 200]", "return [read(), 200]"),
  SOURCE.replace("return ['ok', 200]", "return ['ok', ...values]"),
  SOURCE.replace("return ['ok', 200]", "return ['ok', ]"),
  SOURCE.replace("return ['ok', 200]", "return ['ok', 200n]"),
  SOURCE.replaceAll("body", "__proto__"),
  SOURCE.replaceAll("body", "constructor"),
  SOURCE.replace("export function run()", "function run()"),
  SOURCE.replace("export function run()", "export declare function run()"),
  SOURCE.replace("export function run()", "export async function run()"),
  SOURCE.replace("run(): {", "run<T>(): {"),
  SOURCE.replace("run(): {", "run(value: string): {"),
  SOURCE.replace(
    "{ body: string; status: number }",
    "{ status: number; body: string }",
  ),
  SOURCE.replace(
    "{ body: string; status: number }",
    "{ body?: string; status: number }",
  ),
  SOURCE.replace("const [body, status]", "let [body, status]"),
  SOURCE.replace("const [body, status]", "const [body = 'fallback', status]"),
  SOURCE.replace("const [body, status]", "const [body, ...status]"),
  SOURCE.replace(
    "const [body, status]",
    "const [body, status]: [string, number]",
  ),
  SOURCE.replace("= download();", "= download(1);"),
  SOURCE.replace("= download();", "= download?.();"),
  SOURCE.replace("= download();", "= other();"),
  SOURCE.replace(
    "return { body, status }",
    "return { body: body, status: status }",
  ),
  SOURCE.replace("return { body, status }", "return { status, body }"),
  SOURCE.replace(
    "return { body, status }",
    "return { get body() { return body; }, status }",
  ),
  SOURCE.replace(
    "return { body, status }",
    "observe(); return { body, status }",
  ),
  SOURCE.replaceAll("body", "download"),
])("keeps unproven contracts and caller shapes manual", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});

it("preserves public values, key order, freshness and mutation isolation", () => {
  const expression =
    "(() => { const first = exports.run(); const values = JSON.stringify(first); first.body = 'changed'; const second = exports.run(); return [values, second, Object.keys(second), first !== second]; })()";
  for (const source of [
    SOURCE,
    SOURCE.replace("'ok'", "'𝄞\\u0000'"),
    SOURCE.replaceAll("status: number", "status: boolean").replace(
      "200",
      "false",
    ),
  ]) {
    const evaluate = (text: string): unknown => {
      const compiled = ts.transpileModule(text, {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          target: ts.ScriptTarget.ESNext,
        },
      }).outputText;
      return runInNewContext(`${compiled}\nJSON.stringify(${expression});`, {
        exports: {},
      });
    };
    expect(evaluate(apply(source).output)).toBe(evaluate(source));
  }
});

it("typechecks both source contracts and the unchanged public consumer", () => {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  expect(example?.files[0]?.source).toBe(SOURCE);
  expect(example?.fixedFiles?.[0]?.source).toBe(FIXED);
  const consumer =
    "\nconst observed: {body: string; status: number} = run(); void observed;";
  const virtual = new Map([
    [
      fileURLToPath(new URL("../autofix-tuple-before.ts", import.meta.url)),
      SOURCE + consumer,
    ],
    [
      fileURLToPath(new URL("../autofix-tuple-after.ts", import.meta.url)),
      FIXED + consumer,
    ],
  ]);
  const options: ts.CompilerOptions = {
    strict: true,
    noUnusedLocals: true,
    noUnusedParameters: true,
    noEmit: true,
    skipLibCheck: true,
    types: [],
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
  };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  const exists = host.fileExists.bind(host);
  host.fileExists = (filename) => virtual.has(filename) || exists(filename);
  host.getSourceFile = (filename, version, onError, fresh) => {
    const source = virtual.get(filename);
    return source === undefined
      ? original(filename, version, onError, fresh)
      : ts.createSourceFile(filename, source, version, true);
  };
  expect(
    ts.getPreEmitDiagnostics(
      ts.createProgram([...virtual.keys()], options, host),
    ),
  ).toEqual([]);
});
