import { join } from "node:path";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { expect, it } from "vitest";

const FAILING_CONTRACTS = [
  ["partial numeric range", `
    function isSmall(value: string | number): value is number { return typeof value === "number" && value < 10; }
    function render(value: string | number): string { return isSmall(value) ? value.toFixed() : value.toUpperCase(); }
    render(20);
  `],
  ["nonempty string", `
    function isText(value: string | number): value is string { return typeof value === "string" && value.length > 0; }
    function render(value: string | number): string { return isText(value) ? value.toUpperCase() : value.toFixed(); }
    render("");
  `],
  ["primitive truthiness", `
    function isNumber(value: string | number): value is number { return !!value; }
    function render(value: string | number): string { return isNumber(value) ? value.toFixed() : value.toUpperCase(); }
    render(0);
  `],
] as const;

it.each(FAILING_CONTRACTS)("%s compiles while its false branch fails at runtime", (_name, source) => {
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  expect(() => { runInNewContext(javascript); }).toThrow("is not a function");
});

it("overloads and contextual callbacks can establish sound contracts narrower than the implementation annotation", () => {
  const source = `
    function isText(value: string | number): value is string;
    function isText(value: unknown): value is string | number { return typeof value === "string"; }
    const callback: (value: string) => boolean = (value: unknown): value is string | number => typeof value === "string";
    function render(value: string | number): string { return isText(value) ? value.toUpperCase() : value.toFixed(); }
    [render(1), render("text"), callback("text")];
  `;
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  expect(runInNewContext(javascript)).toEqual(["1", "TEXT", true]);
});

function diagnostics(source: string): readonly number[] {
  const filename = join(import.meta.dirname, "fixtures", "partial-predicate-proof.ts");
  const options: ts.CompilerOptions = { noEmit: true, strict: true, target: ts.ScriptTarget.ES2022, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, source, version, true) : original(path, version, onError, create);
  return ts.getPreEmitDiagnostics(ts.createProgram([filename], options, host)).map((diagnostic) => diagnostic.code);
}
