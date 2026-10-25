// vitest: shared-module-graph
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import rule, {
  NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION,
} from "../src/rules/no-json-stringify-object-equality.js";

const EXAMPLE = NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION.examples[2];
const SOURCE = EXAMPLE.files[0].source;
const FIXED = EXAMPLE.fixedFiles[0].source;
const COMPARISON =
  "JSON.stringify({ id: '1', state: 'ready', toJSON: 'data' }) === JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })";
const CALL =
  "sameShape({ id: '1', state: 'ready', toJSON: 'data' }, { id: '2', state: 'ready', toJSON: 'data' })";

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
    filename: "src/domain.ts",
  });
}

it.each(["\n", "\r\n"])(
  "reuses an authored comparator with %s endings and converges",
  (ending) => {
    const source = SOURCE.replaceAll("\n", ending);
    const messages = new Linter().verify(source, configuration(), {
      filename: "src/domain.ts",
    });
    expect(messages).toHaveLength(1);
    expect(messages[0]?.messageId).toBe("serializedObjectEquality");
    const result = apply(source);
    expect(result.fixed).toBe(true);
    expect(result.output).toBe(FIXED.replaceAll("\n", ending));
    expect(result.messages).toEqual([]);
    expect(apply(result.output).fixed).toBe(false);
  },
);

it.each([
  SOURCE.replaceAll("sameShape", "同形"),
  SOURCE.replaceAll("id", "recordKey").replaceAll("state", "status"),
  SOURCE.replaceAll("id:", "'id':")
    .replaceAll("state:", "'state':")
    .replaceAll("toJSON:", "'toJSON':"),
  SOURCE.replaceAll("'ready'", "'\\ud800'"),
  SOURCE.replaceAll("'ready'", "'𝄞雪'"),
])("retains existing field and helper spellings", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(true);
  expect(result.messages).toEqual([]);
  expect(apply(result.output).fixed).toBe(false);
  expect(evaluate(result.output)).toEqual(evaluate(source));
});

it.each([
  "import 'setup';\n" + SOURCE,
  "// Preserve domain ownership.\n" + SOURCE,
  SOURCE + "\nexport const extra = 1;",
  SOURCE.replace("function sameShape", "export function sameShape"),
  SOURCE.replace("function sameShape", "declare function sameShape"),
  SOURCE.replace("export function choices", "export declare function choices"),
  SOURCE.replace("function sameShape", "async function sameShape"),
  SOURCE.replace("function sameShape", "function* sameShape"),
  SOURCE.replace("function sameShape(", "function sameShape<T>("),
  SOURCE.replace("a: {", "a?: {"),
  SOURCE.replace("a: {", "a: Readonly<{"),
  SOURCE.replaceAll("state: string", "state?: string"),
  SOURCE.replaceAll("state: string", "state: number"),
  SOURCE.replaceAll("; toJSON: string", "")
    .replaceAll(" && a.toJSON === b.toJSON", "")
    .replaceAll(", toJSON: 'data'", ""),
  SOURCE.replaceAll(" && a.toJSON === b.toJSON", ""),
  SOURCE.replace("a.state === b.state", "a.state === b.id"),
  SOURCE.replace("a.id === b.id", "a.id == b.id"),
  SOURCE.replace(" && a.state === b.state", " || a.state === b.state"),
  SOURCE.replace("a.id === b.id", "observe(a.id, b.id)"),
  SOURCE.replace("return a.id", "observe(); return a.id"),
  SOURCE.replace("a.id", "a['id']"),
  SOURCE.replace("a.id", "a?.id"),
  SOURCE.replaceAll("id", "__proto__"),
  SOURCE.replaceAll("id", "constructor"),
  SOURCE.replaceAll("id", "prototype"),
  SOURCE.replace("choices(): boolean[]", "choices()"),
  SOURCE.replace("choices(): boolean[]", "choices(): readonly boolean[]"),
  SOURCE.replace("choices()", "choices(value: string)"),
  SOURCE.replace("choices()", "choices<T>()"),
  SOURCE.replace("export function", "export async function"),
  SOURCE.replace("return [sameShape", "observe(); return [sameShape"),
  SOURCE.replace("return [sameShape", "return [other"),
  SOURCE.replace("return [sameShape", "return [sameShape?."),
  SOURCE.replace("sameShape({ id:", "sameShape<{ id: string }>({ id:"),
  SOURCE.replace(COMPARISON, "true"),
  SOURCE.replace(COMPARISON, "true, " + COMPARISON),
  SOURCE.replace(
    "JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })",
    "JSON.stringify({ state: 'ready', id: '2', toJSON: 'data' })",
  ),
  SOURCE.replace("JSON.stringify({ id: '2'", "JSON.stringify({ id: 2"),
  SOURCE.replace(
    "JSON.stringify({ id: '2'",
    "JSON.stringify({ get id() { return '2'; }",
  ),
  SOURCE.replace("JSON.stringify({ id: '2'", "JSON.stringify({ ['id']: '2'"),
  SOURCE.replace(
    "JSON.stringify({ id: '2'",
    "JSON.stringify({ ...record, id: '2'",
  ),
  SOURCE.replace(
    "JSON.stringify({ id: '2'",
    "JSON.stringify({ id: 'extra', id: '2'",
  ),
  SOURCE.replace(
    "JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })",
    "JSON.stringify({ id: '2', state: 'ready' })",
  ),
  SOURCE.replace(
    "JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })",
    "JSON.stringify({ id: '2', state: 'ready', toJSON() { return 'data'; } })",
  ),
  SOURCE.replace(
    "JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })",
    "JSON.stringify({ id: '2', state: 'ready', toJSON: undefined })",
  ),
  SOURCE.replaceAll("JSON.stringify(", "JSON.stringify?.("),
  SOURCE.replaceAll("JSON.stringify(", "JSON['stringify']("),
  SOURCE.replace("'data' }) ===", "'data' }, null) ==="),
  SOURCE.replace(COMPARISON, COMPARISON.replace(" === ", " !== ")),
  SOURCE.replace(COMPARISON, COMPARISON.replace(" === ", " == ")),
  SOURCE.replaceAll("sameShape", "JSON"),
])("refuses ambiguous ownership, domains, hooks and evaluation", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});

it("respects native inline disabling", () => {
  const source = "/* eslint-disable local/check */\n" + SOURCE;
  expect(apply(source).fixed).toBe(false);
  expect(apply(source).messages).toEqual([]);
});

it.each([
  ["'1'", "'1'"],
  ["'ready'", "''"],
  ["'ready'", "'雪𝄞'"],
  ["'ready'", "'\\ud800'"],
  ["'ready'", "'\\udfff'"],
  ["'ready'", "'\\u0000\\n\\\\\\\"'"],
])(
  "preserves exact primitive values and fresh arrays for %s/%s",
  (oldValue, newValue) => {
    const source = SOURCE.replaceAll(oldValue, newValue);
    const result = apply(source);
    expect(result.fixed).toBe(true);
    const fixed = result.output;
    expect(evaluate(fixed)).toEqual(evaluate(source));
    expect(
      evaluate(
        fixed,
        "Object.prototype.toJSON = function () { throw new Error('inherited hook'); };",
      ),
    ).toEqual(
      evaluate(
        source,
        "Object.prototype.toJSON = function () { throw new Error('inherited hook'); };",
      ),
    );
  },
);

it.each([
  COMPARISON.replace("{ id: '2'", "{ id: '1'"),
  COMPARISON.replace(
    "{ id: '2', state: 'ready', toJSON: 'data' }",
    "{ id: '1', state: 'different', toJSON: 'data' }",
  ),
  COMPARISON.replace(
    "{ id: '2', state: 'ready', toJSON: 'data' }",
    "{ id: '1', state: 'ready', toJSON: 'different' }",
  ),
])(
  "preserves every covered field and true/false runtime outcomes",
  (comparison) => {
    const source = SOURCE.replace(COMPARISON, comparison);
    const result = apply(source);
    expect(result.fixed).toBe(true);
    expect(evaluate(result.output)).toEqual(evaluate(source));
  },
);

function evaluate(source: string, setup = ""): unknown {
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ESNext,
    },
  }).outputText;
  const result: unknown = runInNewContext(
    `${compiled}\n${setup}\n(() => { const first = exports.choices(); const values = first.slice(); first.push(false); const second = exports.choices(); return [values.join(','), second.join(','), first !== second]; })()`,
    { exports: {} },
  );
  return Array.isArray(result) ? Array.from(result) : result;
}

it("retains the inherited-hook counterexample instead of relying on pristine prototypes", () => {
  const source = SOURCE.replaceAll("; toJSON: string", "")
    .replaceAll(" && a.toJSON === b.toJSON", "")
    .replaceAll(", toJSON: 'data'", "");
  const manual = source.replace(
    COMPARISON.replaceAll(", toJSON: 'data'", ""),
    CALL.replaceAll(", toJSON: 'data'", ""),
  );
  const setup =
    "Object.prototype.toJSON = function () { return 'collapsed'; };";
  const result = apply(source);
  expect(result.fixed).toBe(false);
  expect(result.messages).toHaveLength(1);
  expect(result.messages[0]?.messageId).toBe("serializedObjectEquality");
  expect(evaluate(source, setup)).not.toEqual(evaluate(manual, setup));
});

it("typechecks before and after with unused bindings checked", () => {
  const files = new Map([
    [resolve("autofix-domain-before.ts"), SOURCE],
    [resolve("autofix-domain-after.ts"), FIXED],
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
  host.fileExists = (filename) => files.has(filename) || exists(filename);
  host.getSourceFile = (filename, version, onError, fresh) => {
    const source = files.get(filename);
    return source === undefined
      ? original(filename, version, onError, fresh)
      : ts.createSourceFile(filename, source, version, true);
  };
  expect(
    ts.getPreEmitDiagnostics(
      ts.createProgram([...files.keys()], options, host),
    ),
  ).toEqual([]);
});
