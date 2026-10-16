import { join } from "node:path";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { expect, it } from "vitest";

const WRONG_TRUE_BRANCH = `
  function isText(value: unknown): value is string { return typeof value === "number"; }
  function render(value: unknown): string { return isText(value) ? value.toUpperCase() : "other"; }
  render(3);
`;
const WRONG_FALSE_BRANCH = `
  function isTextOrNumber(value: string | number | boolean): value is string | number { return typeof value === "string"; }
  function inspect(value: string | number | boolean): void {
    if (!isTextOrNumber(value)) {
      const flag: boolean = value;
      if (typeof flag !== "boolean") throw new Error("false branch admitted a number as boolean");
    }
  }
  inspect(3);
`;

it.each([
  ['wrong primitive in the true branch', WRONG_TRUE_BRANCH, 'is not a function'],
  ['rejected promised alternative in the false branch', WRONG_FALSE_BRANCH, 'false branch admitted a number as boolean'],
])("explicit predicates compile but fail at runtime for %s", (_label, source, message) => {
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  expect(() => { runInNewContext(javascript); }).toThrow(message);
});

function diagnostics(source: string): readonly number[] {
  const filename = join(import.meta.dirname, 'fixtures', 'predicate-proof.ts');
  const options: ts.CompilerOptions = { noEmit: true, strict: true, target: ts.ScriptTarget.ES2022, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, source, version, true) : original(path, version, onError, create);
  return ts.getPreEmitDiagnostics(ts.createProgram([filename], options, host)).map((diagnostic) => diagnostic.code);
}
