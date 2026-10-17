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
  ['primitive-wide acceptance exceeds a literal domain', 'function check(value:unknown):value is "ready"{return typeof value==="string";} function use(value:unknown){if(check(value)){const ready:"ready"=value;if(ready!=="ready")throw new Error("literal contract violated");}}use("later");', 'literal contract violated'],
  ['a successful branch cannot inhabit never', 'function check(value:unknown):value is never{return typeof value==="number";} function use(value:unknown){if(check(value)){const empty:never=value;throw new Error(`uninhabited target reached: ${String(empty)}`);}}use(1);', 'uninhabited target reached'],
  ['typeof-object accepts null outside the object contract', 'function check(value:unknown):value is object{return typeof value==="object";} function use(value:unknown){if(check(value))Object.keys(value);}use(null);', 'Cannot convert undefined or null to object'],
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
