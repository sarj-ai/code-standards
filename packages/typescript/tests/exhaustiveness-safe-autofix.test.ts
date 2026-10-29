// vitest: shared-module-graph
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import { emptyAssertionFix } from "../src/rules/_empty-assertion-fix.js";
import rule from "../src/rules/require-assert-never.js";

const SOURCE =
  "function assertNever(_value: never): void {}\nexport function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: break; } return 0; }";
const FIXED = SOURCE.replace("default:", "default: assertNever(kind);");


function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  const adapter: TSESLint.RuleModule<"check", []> = {
    meta: {
      type: "suggestion",
      fixable: "code",
      schema: [],
      messages: { check: "check" },
    },
    defaultOptions: [],
    create(context) {
      return {
        SwitchStatement(node: TSESTree.SwitchStatement) {
          const branch = node.cases.at(-1);
          if (branch === undefined || branch.test !== null) return;
          const fix = emptyAssertionFix(context.sourceCode, node, branch);
          if (fix !== null)
            context.report({ node: branch, messageId: "check", fix });
        },
      };
    },
  };
  return new Linter().verifyAndFix(
    source,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser },
        plugins: { local: { rules: { check: adapter } } },
        rules: { "local/check": "error" },
      },
    ],
    { filename: "src/exhaustive.ts" },
  );
}

it.each(["\n", "\r\n"])(
  "preserves exact bytes and converges with %s endings",
  (ending) => {
    const source = SOURCE.replaceAll("\n", ending);
    const fixed = FIXED.replaceAll("\n", ending);
    expect(apply(source).output).toBe(fixed);
    expect(apply(source).fixed).toBe(true);
    expect(apply(fixed).fixed).toBe(false);
  },
);

it("supports an empty final default and string or boolean literal returns", () => {
  for (const source of [
    SOURCE.replace("default: break;", "default:"),
    SOURCE.replace(": number", ": string")
      .replace("return 1", "return 'one'")
      .replace("return 2", "return 'two'")
      .replace("return 0", "return 'other'"),
    SOURCE.replace(": number", ": boolean")
      .replace("return 1", "return true")
      .replace("return 2", "return false")
      .replace("return 0", "return false"),
  ]) {
    expect(apply(source).fixed).toBe(true);
    expect(apply(apply(source).output).fixed).toBe(false);
  }
});

it.each([
  SOURCE.replace("function assertNever", "declare function assertNever"),
  SOURCE.replace("export function render", "export declare function render"),
  SOURCE.replace("void {}", "void { throw new Error(); }"),
  SOURCE.replace("void {}", "void { return; }"),
  SOURCE.replace("_value: never", "_value: string"),
  SOURCE.replace("_value: never", "_value?: never"),
  SOURCE.replace("_value: never", "..._value: never[]"),
  SOURCE.replace("_value: never", "_value: never = undefined as never"),
  SOURCE.replace("function assertNever(", "function assertNever<T>("),
  SOURCE.replace("function assertNever(", "async function assertNever("),
  SOURCE.replace("function assertNever(", "export function assertNever("),
  SOURCE.replace("assertNever", "otherGuard"),
  "// policy boundary\n" + SOURCE,
  "import 'setup';\n" + SOURCE,
  SOURCE + "\nexport const other = 1;",
  SOURCE.replace("export function render", "function render"),
  SOURCE.replace("export function render(", "export function render<T>("),
  SOURCE.replace("export function render(", "export async function render("),
  SOURCE.replace("kind: 'a' | 'b'", "kind?: 'a' | 'b'"),
  SOURCE.replace("kind: 'a' | 'b'", "kind: 'a' | 'b' = 'a'"),
  SOURCE.replace("kind: 'a' | 'b'", "kind: string"),
  SOURCE.replace("kind: 'a' | 'b'", "kind: 'a' | 'b' | 'c'"),
  SOURCE.replace("kind: 'a' | 'b'", "kind: 'a' | 'a'"),
  SOURCE.replace(": number {", " {"),
  SOURCE.replace("switch (kind)", "switch (String(kind))"),
  SOURCE.replace("case 'b': return 2;", "case 'a': return 2;"),
  SOURCE.replace("case 'b': return 2;", "case 'b': break;"),
  SOURCE.replace("case 'b': return 2;", "case 'b': return compute();"),
  SOURCE.replace("default: break;", "default: {}"),
  SOURCE.replace("default: break;", "default: return 0;"),
  SOURCE.replace("return 0;", "return compute();"),
  SOURCE.replace("switch (kind)", "const guard = assertNever; switch (kind)"),
  SOURCE.replaceAll("kind", "assertNever"),
])("refuses an unproven helper, scope or dispatch", (source) => {
  const result = apply(source);
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});

it("preserves handled and unexpected runtime results without observing arguments", () => {
  const oracle =
    "[exports.render('a'), exports.render('b'), exports.render('other'), exports.render(null), exports.render(undefined), exports.render(3), exports.render(Symbol('other')), exports.render(new Proxy({}, {get(){throw Error('observed');}}))]";
  const evaluate = (source: string): unknown => {
    const compiled = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ESNext,
      },
    }).outputText;
    return runInNewContext(`${compiled}\nJSON.stringify(${oracle});`, {
      exports: {},
    });
  };
  expect(evaluate(apply(SOURCE).output)).toBe(evaluate(SOURCE));
});

it("typechecks both versions and catches a future union member at the existing guard", () => {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  expect(example?.files[0]?.source).toBe(SOURCE);
  expect(example?.fixedFiles?.[0]?.source).toBe(FIXED);
  const futureName = fileURLToPath(
    new URL("../autofix-never-future.ts", import.meta.url),
  );
  const virtual = new Map([
    [
      fileURLToPath(new URL("../autofix-never-before.ts", import.meta.url)),
      SOURCE,
    ],
    [
      fileURLToPath(new URL("../autofix-never-after.ts", import.meta.url)),
      FIXED,
    ],
    [futureName, FIXED.replace("'a' | 'b'", "'a' | 'b' | 'c'")],
  ]);
  const options: ts.CompilerOptions = {
    strict: true,
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
  const diagnostics = ts.getPreEmitDiagnostics(
    ts.createProgram([...virtual.keys()], options, host),
  );
  expect(diagnostics).toHaveLength(1);
  expect(diagnostics[0]?.file?.fileName).toBe(futureName);
  expect(diagnostics[0]?.code).toBe(2345);
});
