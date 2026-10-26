// vitest: shared-module-graph
import { webcrypto } from "node:crypto";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { NIL, v4, validate, version } from "uuid";
import { expect, it } from "vitest";

import packageRule from "../src/rules/prefer-native-random-uuid.js";
import recipeRule from "../src/rules/no-insecure-random-id.js";

const PACKAGE =
  "import { v4, NIL } from 'uuid'; const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function packageId(): string { return v4(); } export function ids(): string[] { return [nativeId(), packageId(), NIL]; }";
const RECIPE =
  "const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function recipeId(): string { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const uuidDigit = Math.random() * 16 | 0; return (c === 'x' ? uuidDigit : (uuidDigit & 3) | 8).toString(16); }); } export function ids(): string[] { return [nativeId(), recipeId()]; }";
const PACKAGE_FIXED = PACKAGE.replace("v4, ", "").replace(
  "return v4();",
  "return nativeUuid();",
);
const RECIPE_FIXED =
  RECIPE.slice(0, RECIPE.indexOf("return 'xxxxxxxx")) +
  "return nativeUuid(); }" +
  RECIPE.slice(RECIPE.indexOf(" export function"));

function apply(
  source: string,
  kind: "package" | "recipe",
): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(
    source,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser },
        plugins: {
          local: {
            rules: { check: kind === "package" ? packageRule : recipeRule },
          },
        },
        rules: { "local/check": "error" },
      },
    ],
    { filename: "src/ids.ts" },
  );
}

it.each(["\n", "\r\n"])(
  "reuses authored providers and preserves %s endings",
  (ending) => {
    for (const [kind, source, expected] of [
      ["package", PACKAGE, PACKAGE_FIXED],
      ["recipe", RECIPE, RECIPE_FIXED],
    ] as const) {
      const input = source.replaceAll("; ", `;${ending}`);
      const output = expected.replaceAll("; ", `;${ending}`);
      const result = apply(input, kind);
      expect(result.fixed).toBe(true);
      expect(result.output).toBe(output);
      expect(result.messages).toEqual([]);
      expect(apply(result.output, kind).fixed).toBe(false);
      expect(apply(result.output, kind).messages).toEqual([]);
    }
  },
);

it("preserves multiline import endings and UTF-16 binding ranges", () => {
  const source = PACKAGE.replace("v4, NIL", "v4,\r\n NIL").replaceAll(
    "nativeUuid",
    "nativeÜuid",
  );
  const result = apply(source, "package");
  expect(result.fixed).toBe(true);
  expect(result.output).toContain("import { \r\n NIL }");
  expect(result.output).toContain("return nativeÜuid();");
  expect(result.output.split("\r\n").length).toBe(source.split("\r\n").length);
  expect(apply(result.output, "package").fixed).toBe(false);
});

const PACKAGE_REFUSALS = [
  PACKAGE.replace("{ v4, NIL }", "{ v4 } ").replace(", NIL]", "]"),
  PACKAGE.replace("'uuid'", "'other'"),
  PACKAGE.replace("NIL", "MAX"),
  PACKAGE.replace("v4();", "v4?.();"),
  PACKAGE.replace("v4();", "v4<string>();"),
  PACKAGE.replace("v4();", "v4({});"),
  PACKAGE.replace("bind(crypto)", "bind(other)"),
  PACKAGE.replace("randomUUID.bind", "randomUUID.call"),
  PACKAGE.replace("crypto.randomUUID", "globalThis.crypto.randomUUID"),
  PACKAGE.replace("const nativeUuid", "let nativeUuid"),
  PACKAGE.replace("const nativeUuid", "const nativeUuid: () => string"),
  PACKAGE.replace("return nativeUuid();", "return 'already';"),
  PACKAGE.replace(
    "return [nativeId(), packageId(), NIL]",
    "return [packageId(), nativeId(), NIL]",
  ),
  PACKAGE.replace("packageId(): string", "packageId()"),
  PACKAGE.replace("nativeId(): string", "nativeId()"),
  PACKAGE.replace("ids(): string[]", "ids()"),
  PACKAGE.replace("function packageId()", "async function packageId()"),
  PACKAGE.replace("function packageId()", "function* packageId()"),
  PACKAGE.replace("function packageId()", "function packageId<T>()"),
  PACKAGE.replace("function packageId()", "function packageId(value: string)"),
  PACKAGE.replace("return v4();", "observe(); return v4();"),
  PACKAGE.replace("return v4();", "return v4(/* retain */);"),
  PACKAGE.replace("function nativeId", "export function nativeId"),
  PACKAGE + " const extra = 1;",
  "import 'setup'; " + PACKAGE,
  "// preserve rationale\n" + PACKAGE,
];

const RECIPE_REFUSALS = [
  RECIPE.replace(
    "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx",
    "xxxxxxxx-xxxx-xxxx-yxxx-xxxxxxxxxxxx",
  ),
  RECIPE.replace("/[xy]/g", "/[xy]/"),
  RECIPE.replace("/[xy]/g", "/[xy]/gi"),
  RECIPE.replace("Math.random() * 16", "Math.random() * 15"),
  RECIPE.replace("uuidDigit & 3", "uuidDigit & 7"),
  RECIPE.replace("| 8)", "| 4)"),
  RECIPE.replace(".toString(16)", ".toString(36)"),
  RECIPE.replace("const uuidDigit", "let uuidDigit"),
  RECIPE.replace("const uuidDigit", "declare const uuidDigit"),
  RECIPE.replace("const uuidDigit", "const uuidDigit: number"),
  RECIPE.replace("c =>", "async c =>"),
  RECIPE.replace("c =>", "(c: string) =>"),
  RECIPE.replace("return (c ===", "observe(); return (c ==="),
  RECIPE.replace("recipeId(): string", "recipeId()"),
  RECIPE.replace("ids(): string[]", "ids()"),
  RECIPE.replace("return nativeUuid();", "return 'already';"),
  RECIPE.replace("bind(crypto)", "bind(other)"),
  RECIPE.replace("const nativeUuid", "let nativeUuid"),
  RECIPE.replace(
    "return [nativeId(), recipeId()]",
    "return [recipeId(), nativeId()]",
  ),
  RECIPE + " export const provider = nativeUuid;",
  "// preserve recipe\n" + RECIPE,
];

it.each(PACKAGE_REFUSALS)(
  "leaves unproven package authority manual",
  (source) => {
    const result = apply(source, "package");
    expect(result.fixed).toBe(false);
    expect(result.output).toBe(source);
  },
);
it.each(RECIPE_REFUSALS)("leaves other random recipes manual", (source) => {
  const result = apply(source, "recipe");
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});

it("retains the detector's Math-shadow and unrelated-name exclusions", () => {
  for (const source of [
    RECIPE.replace("c =>", "Math =>"),
    RECIPE.replaceAll("uuidDigit", "r"),
  ]) {
    const result = apply(source, "recipe");
    expect(result.fixed).toBe(false);
    expect(result.output).toBe(source);
    expect(result.messages).toEqual([]);
  }
});

function execute(source: string): string[] {
  const emitted = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ESNext,
    },
  }).outputText;
  return runInNewContext(`${emitted}\nexports.ids();`, {
    exports: {},
    crypto: webcrypto,
    require: () => ({ v4, NIL }),
  }) as string[];
}

it("smokes the pinned real uuid library and existing native provider", () => {
  for (const source of [
    PACKAGE,
    apply(PACKAGE, "package").output,
    RECIPE,
    apply(RECIPE, "recipe").output,
  ]) {
    const values = execute(source);
    expect(values).toHaveLength(source.includes("NIL") ? 3 : 2);
    for (const value of values.slice(0, 2)) {
      expect(validate(value)).toBe(true);
      expect(version(value)).toBe(4);
      expect(value).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u,
      );
    }
    if (source.includes("NIL")) expect(values[2]).toBe(NIL);
  }
});

it("strictly typechecks both APIs without changing public declarations", () => {
  for (const [kind, source, fixed] of [
    ["package", PACKAGE, PACKAGE_FIXED],
    ["recipe", RECIPE, RECIPE_FIXED],
  ] as const) {
    const virtual = new Map([
      [
        fileURLToPath(new URL(`../uuid-${kind}-before.ts`, import.meta.url)),
        source,
      ],
      [
        fileURLToPath(new URL(`../uuid-${kind}-after.ts`, import.meta.url)),
        fixed,
      ],
    ]);
    const options: ts.CompilerOptions = {
      strict: true,
      declaration: true,
      skipLibCheck: true,
      types: [],
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.NodeNext,
      moduleResolution: ts.ModuleResolutionKind.NodeNext,
    };
    const host = ts.createCompilerHost(options);
    const original = host.getSourceFile.bind(host);
    const exists = host.fileExists.bind(host);
    host.fileExists = (filename) => virtual.has(filename) || exists(filename);
    host.getSourceFile = (filename, version, onError, fresh) => {
      const text = virtual.get(filename);
      return text === undefined
        ? original(filename, version, onError, fresh)
        : ts.createSourceFile(filename, text, version, true);
    };
    const outputs = new Map<string, string>();
    host.writeFile = (filename, text) => {
      outputs.set(filename, text);
    };
    const program = ts.createProgram([...virtual.keys()], options, host);
    expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
    expect(program.emit().emitSkipped).toBe(false);
    const declaration = (suffix: string): string | undefined =>
      [...outputs].find(([filename]) => filename.endsWith(suffix))?.[1];
    const before = declaration(`uuid-${kind}-before.d.ts`);
    expect(before).toBeDefined();
    expect(declaration(`uuid-${kind}-after.d.ts`)).toBe(before);
    expect(before).toContain("ids(): string[]");
  }
});
