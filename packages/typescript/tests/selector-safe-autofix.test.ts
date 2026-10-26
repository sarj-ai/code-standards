// vitest: shared-module-graph
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import {
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import { literalSelectorFix } from "../src/rules/_literal-selector-fix.js";
import rule from "../src/rules/no-boolean-selector-parameter.js";

const SOURCE =
  "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nconst book = (premium: boolean) => premium ? premiumBook() : regularBook();\nexport function choices(): string[] { return [book(true), book(false), book(true)]; }";
const FIXED =
  "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nexport function choices(): string[] { return [premiumBook(), regularBook(), premiumBook()]; }";

/** Exercise source ownership independently of pending native typed detection. */
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
        ConditionalExpression(node: TSESTree.ConditionalExpression) {
          if (node.test.type !== AST_NODE_TYPES.Identifier) return;
          const fix = literalSelectorFix(context.sourceCode, node.test);
          if (fix !== null) context.report({ node, messageId: "check", fix });
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
    { filename: "src/selector.ts" },
  );
}

it.each(["\n", "\r\n"])(
  "routes exact literal calls and converges for %s endings",
  (ending) => {
    const source = SOURCE.replaceAll("\n", ending);
    const fixed = FIXED.replaceAll("\n", ending);
    const result = apply(source);
    expect(result.fixed).toBe(true);
    expect(result.output).toBe(fixed);
    expect(apply(fixed).fixed).toBe(false);
  },
);

it.each([
  SOURCE.replaceAll("premiumBook", "优先").replaceAll("regularBook", "普通"),
  SOURCE.replaceAll("'premium'", "'𝄞'").replaceAll("'regular'", "''"),
  SOURCE.replace(
    "premium ? premiumBook() : regularBook()",
    "premium ? regularBook() : premiumBook()",
  ),
  SOURCE.replace(
    "book(true), book(false), book(true)",
    "book(false), book(true), book(false), book(true)",
  ),
])("preserves existing operation names and literal choices", (source) => {
  expect(apply(source).fixed).toBe(true);
  expect(apply(apply(source).output).fixed).toBe(false);
});

it.each([
  SOURCE.replace("const book", "declare const book"),
  SOURCE.replace("function premiumBook", "declare function premiumBook"),
  SOURCE.replace("function regularBook", "declare function regularBook"),
  SOURCE.replace("export function choices", "export declare function choices"),
  "import 'setup';\n" + SOURCE,
  "// preserve ownership\n" + SOURCE,
  SOURCE + "\nexport const other = 1;",
  SOURCE.replace("const book", "export const book"),
  SOURCE.replace("const book", "let book"),
  SOURCE.replace("const book =", "const book: (value: boolean) => string ="),
  SOURCE.replace("(premium: boolean)", "(premium?: boolean)"),
  SOURCE.replace("(premium: boolean)", "(premium: boolean = true)"),
  SOURCE.replace("(premium: boolean)", "(premium: true)"),
  SOURCE.replace("(premium: boolean)", "(premium: boolean, extra: string)"),
  SOURCE.replace("(premium: boolean)", "<T>(premium: boolean)"),
  SOURCE.replace("(premium: boolean)", "async (premium: boolean)"),
  SOURCE.replace("=> premium ?", "=> !premium ?"),
  SOURCE.replace("=> premium ?", "=> Boolean(premium) ?"),
  SOURCE.replace(
    "premiumBook() : regularBook()",
    "premiumBook() : premiumBook()",
  ),
  SOURCE.replace(
    "premiumBook() : regularBook()",
    "premiumBook(1) : regularBook()",
  ),
  SOURCE.replace("function premiumBook()", "function premiumBook(value = 1)"),
  SOURCE.replace("function premiumBook()", "async function premiumBook()"),
  SOURCE.replace("function premiumBook()", "function* premiumBook()"),
  SOURCE.replace("return 'premium';", "return observe();"),
  SOURCE.replace("return 'premium';", "return { value: 'premium' };"),
  SOURCE.replace("return 'premium';", "throw new Error('observed stack');"),
  SOURCE.replace("return 'premium';", "book = other; return 'premium';"),
  SOURCE.replace(
    "function choices()",
    "function choices(book: (value: boolean) => string)",
  ),
  SOURCE.replace("function choices()", "async function choices()"),
  SOURCE.replace("choices(): string[]", "choices()"),
  SOURCE.replace("choices(): string[]", "choices(): readonly string[]"),
  SOURCE.replace("return [book(true)", "observe(); return [book(true)"),
  SOURCE.replace("book(false)", "book(true)"),
  SOURCE.replace("book(false)", "book(flag)"),
  SOURCE.replace("book(false)", "book(!true)"),
  SOURCE.replace("book(false)", "book"),
  SOURCE.replace("book(false)", "book(false, sideEffect())"),
  SOURCE.replace("book(false)", "book?.(false)"),
  SOURCE.replace("book(false)", "...book(false)"),
  SOURCE.replaceAll("premiumBook", "premium"),
])(
  "refuses unowned callers, observable operations or public contracts",
  (source) => {
    const result = apply(source);
    expect(result.fixed).toBe(false);
    expect(result.output).toBe(source);
  },
);

it("preserves repeated values, fresh result arrays and mutation isolation", () => {
  const expression =
    "(() => { const first = exports.choices(); const values = first.slice(); first.push('changed'); const second = exports.choices(); return [values, second, first !== second]; })()";
  for (const source of [
    SOURCE,
    SOURCE.replace(
      "premiumBook() : regularBook()",
      "regularBook() : premiumBook()",
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

it("typechecks both private operation contracts with unused bindings checked", () => {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  expect(example?.files[0]?.source).toBe(SOURCE);
  expect(example?.fixedFiles?.[0]?.source).toBe(FIXED);
  const virtual = new Map([
    [
      fileURLToPath(new URL("../autofix-selector-before.ts", import.meta.url)),
      SOURCE,
    ],
    [
      fileURLToPath(new URL("../autofix-selector-after.ts", import.meta.url)),
      FIXED,
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
