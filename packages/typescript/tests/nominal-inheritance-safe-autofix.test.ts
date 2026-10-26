import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import type { TSESLint } from "@typescript-eslint/utils";
import ts from "typescript";
import { expect, it } from "vitest";

import { closedNominalInheritanceFix } from "../src/rules/_closed-nominal-inheritance-fix.js";
import rule from "../src/rules/require-explicit-contract-implementation.js";

function sources(): { readonly original: string; readonly fixed: string } {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.files[0] === undefined || example.fixedFiles?.[0] === undefined)
    throw new Error("Missing nominal inheritance fixture");
  return {
    original: example.files[0].source,
    fixed: example.fixedFiles[0].source,
  };
}

function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  const gate: TSESLint.RuleModule<"correct", readonly []> = {
    meta: {
      schema: [],
      fixable: "code",
      messages: { correct: "Closed nominal inheritance syntax" },
    },
    defaultOptions: [],
    create(context) {
      return {
        Program() {
          const file = ts.createSourceFile(
            "source.ts",
            context.sourceCode.text,
            ts.ScriptTarget.Latest,
            true,
          );
          const classes = file.statements.filter(ts.isClassDeclaration);
          const [contract, consumer, implementation] = classes;
          const statement = file.statements.find(ts.isExpressionStatement);
          if (
            contract === undefined ||
            consumer === undefined ||
            implementation === undefined ||
            statement === undefined ||
            !ts.isNewExpression(statement.expression)
          )
            return;
          const fix = closedNominalInheritanceFix(
            context.sourceCode,
            statement.expression,
            consumer,
            implementation,
            contract,
          );
          if (fix !== null)
            context.report({
              node: context.sourceCode.ast,
              messageId: "correct",
              fix,
            });
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
        plugins: { local: { rules: { gate } } },
        rules: { "local/gate": "error" },
      },
    ],
    { filename: "src/nominal.ts" },
  );
}

it("applies only the authored inert base and converges", () => {
  const { original, fixed } = sources();
  const first = apply(original),
    second = apply(first.output);
  expect(first.fixed).toBe(true);
  expect(first.output).toBe(fixed);
  expect(first.messages).toEqual([]);
  expect(second.fixed).toBe(false);
  expect(second.messages).toEqual([]);
});

it("repairs the actual nominal TypeError while retaining the guard and constructor", () => {
  const { original, fixed } = sources();
  const compile = (source: string): string =>
    ts.transpileModule(source, {
      compilerOptions: {
        target: ts.ScriptTarget.ESNext,
        module: ts.ModuleKind.CommonJS,
      },
    }).outputText;
  expect((): unknown =>
    runInNewContext(compile(original), { exports: {} }),
  ).toThrow("Nominal publisher required");
  expect((): unknown =>
    runInNewContext(compile(fixed), { exports: {} }),
  ).not.toThrow();
  expect(
    fixed.replace("FakePublisher extends Publisher", "FakePublisher"),
  ).toBe(original);
});

it("compiles both structural input and corrected nominal implementation strictly", () => {
  const { original, fixed } = sources();
  const files = new Map([
    [fileURLToPath(new URL("../nominal-before.ts", import.meta.url)), original],
    [fileURLToPath(new URL("../nominal-after.ts", import.meta.url)), fixed],
  ]);
  const options: ts.CompilerOptions = {
    strict: true,
    noEmit: true,
    noUnusedLocals: true,
    noUnusedParameters: true,
    skipLibCheck: true,
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
  };
  const host = ts.createCompilerHost(options),
    getSourceFile = host.getSourceFile.bind(host),
    fileExists = host.fileExists.bind(host);
  host.fileExists = (filename) => files.has(filename) || fileExists(filename);
  host.getSourceFile = (
    filename,
    languageVersion,
    onError,
    shouldCreateNewSourceFile,
  ) => {
    const source = files.get(filename);
    return source === undefined
      ? getSourceFile(
          filename,
          languageVersion,
          onError,
          shouldCreateNewSourceFile,
        )
      : ts.createSourceFile(filename, source, languageVersion, true);
  };
  const program = ts.createProgram([...files.keys()], options, host);
  expect(
    ts
      .getPreEmitDiagnostics(program)
      .map((diagnostic) =>
        ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      ),
  ).toEqual([]);
});
