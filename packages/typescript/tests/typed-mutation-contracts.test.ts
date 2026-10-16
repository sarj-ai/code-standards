import { join } from "node:path";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { expect, it } from "vitest";

const COUNTER = 'const counter: { count: number } = { count: 1 };';

it("native mutation accepts incompatible writes that direct assignment rejects", () => {
  expect(diagnostics(`${COUNTER} Object.assign(counter, { count: "invalid" }); Reflect.set(counter, "count", "invalid"); Object.defineProperty(counter, "count", { value: "invalid" });`)).toEqual([]);
  expect(diagnostics(`${COUNTER} counter.count = "invalid";`)).toEqual([2322]);
});

function diagnostics(source: string, exactOptionalPropertyTypes = false): readonly number[] {
  const filename = join(import.meta.dirname, 'fixtures', 'mutation-proof.ts');
  const options: ts.CompilerOptions = { noEmit: true, strict: true, exactOptionalPropertyTypes, target: ts.ScriptTarget.ES2022, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, source, version, true) : original(path, version, onError, create);
  return ts.getPreEmitDiagnostics(ts.createProgram([filename], options, host)).map((diagnostic) => diagnostic.code);
}

it.each([
  ['assign', 'Object.assign(counter, { count: "invalid" });'],
  ['set', 'Reflect.set(counter, "count", "invalid");'],
  ['defineProperty', 'Object.defineProperty(counter, "count", { value: "invalid" });'],
])("%s corrupts the value while subsequent reads retain the original static type", (_method, mutation) => {
  const source = `${COUNTER} ${mutation} counter.count.toFixed();`;
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  expect(() => { runInNewContext(javascript); }).toThrow('is not a function');
});


it("the compiler policy distinguishes omitted optional fields from authored undefined", () => {
  const optional = 'const counter: { count?: number } = { count: 1 };';
  expect(diagnostics(`${optional} Object.assign(counter, { count: undefined });`, true)).toEqual([]);
  expect(diagnostics(`${optional} counter.count = undefined;`, true)).toEqual([2412]);
  expect(diagnostics(`${optional} counter.count = undefined;`, false)).toEqual([]);
  expect(diagnostics('const counter: { count?: number | undefined } = { count: 1 }; counter.count = undefined;', true)).toEqual([]);
});

it("a readonly annotation does not freeze a local own-data object", () => {
  const source = 'const counter: Readonly<{ count: number }> = { count: 1 }; Object.assign(counter, { count: "invalid" }); counter.count.toFixed();';
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  expect(() => { runInNewContext(javascript); }).toThrow('is not a function');
});

it("deletion can expose an inherited setter that preserves the numeric contract", () => {
  const source = `
    let stored = 1;
    Object.defineProperty(Object.prototype, "count", {
      get() { return stored; }, set(value: unknown) { stored = Number(value); }, configurable: true,
    });
    const counter: { count?: number } = { count: 1 };
    delete counter.count;
    Object.assign(counter, { count: "2" });
    [counter.count, Object.hasOwn(counter, "count")];
  `;
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const result: unknown = runInNewContext(javascript);
  expect(result).toEqual([2, false]);
});

it("a locked descriptor makes a later incompatible Reflect write harmless", () => {
  const source = `${COUNTER} Object.defineProperty(counter, "count", { value: 2, writable: false }); [Reflect.set(counter, "count", "ignored"), counter.count];`;
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const result: unknown = runInNewContext(javascript);
  expect(result).toEqual([false, 2]);
});

it("an escaped native namespace may install an adapter that ignores an incompatible patch", () => {
  const source = `
    function configure(namespace: ObjectConstructor): void {
      namespace.assign = new Proxy(namespace.assign, { apply(_target, _receiver, args) { return args[0]; } });
    }
    configure(Object);
    ${COUNTER}
    Object.assign(counter, { count: "ignored" });
    counter.count.toFixed();
  `;
  expect(diagnostics(source)).toEqual([]);
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const result: unknown = runInNewContext(javascript);
  expect(result).toBe("1");
});
