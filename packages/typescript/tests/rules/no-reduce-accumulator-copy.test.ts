import rule from "../../src/rules/no-reduce-accumulator-copy.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const TESTER = ruleTester({ cwd: FIXTURES });

TESTER.run("no-reduce-accumulator-copy", rule, typed({
  valid: [
    "declare const calls: string[]; declare function append(done: number[], call: string): Promise<number[]>; calls.reduce<Promise<number[]>>(async (previous, call) => append(await previous, call), Promise.resolve([]));",
    "declare const calls: string[]; declare function run(call: string): Promise<number>; async function answers() { return calls.reduce<Promise<number[]>>(async (previous, call) => { const done = await previous; done.push(await run(call)); return done; }, Promise.resolve([])); }",
    "declare const calls: string[]; declare const first: number[]; declare function run(call: string): Promise<number>; async function answers() { return calls.reduce<Promise<number[]>>(async (done, call) => [...(await done), await run(call)], Promise.resolve(first)); }",
    "declare const calls: string[]; declare function run(call: string): Promise<number>; function answers() { return calls.reduce<Promise<number[]>>((chain, call) => chain.then(async (done) => [...done, await run(call)]), Promise.resolve([])); }",
    "declare const calls: string[]; function answers(Promise: { resolve(seed: number[]): PromiseLike<number[]> }) { return calls.reduce<PromiseLike<number[]>>(async (done, call) => [...(await done), call.length], Promise.resolve([])); }",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { for (const item of page) { consume(acc.slice()); } return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { { const acc: string[] = []; acc.slice(); } return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => page.slice(), []);",
    "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => Object.assign(acc, { [key]: value }), {});",
    "declare const values: string[]; const Object = { assign: (...args: unknown[]) => ({}) }; values.reduce((acc) => Object.assign({}, acc), {});",
    "declare const pages: string[][]; const rows = pages.flatMap(page => page);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { acc.push(...page); return acc; }, []);",
    "declare const pages: string[][]; declare const seed: string[]; pages.reduce((acc, page) => acc.concat(page), seed);",
    "declare const pages: string[][]; pages.reduce((acc, page) => acc.concat(page));",
    "declare const values: number[]; values.reduce((acc, value) => acc + value, 0);",
    "declare const values: string[]; values.reduce((acc, value) => acc.concat(value), '');",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const later = () => acc.slice(); return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { function copy(acc: string[]) { return acc.slice(); } return page; }, []);",
    "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { acc = page; return acc.slice(); }, []);",
    "declare const custom: { reduce(fn: (acc: string[], x: string[]) => string[], seed: string[]): string[] }; custom.reduce((acc, x) => acc.concat(x), []);",
    "declare const pages: string[][]; const Array = { from: (x: string[]) => x }; pages.reduce<string[]>((acc) => Array.from(acc), []);",
    {
      code: "// @generated\ndeclare const pages: string[][]; pages.reduce<string[]>((acc, page) => acc.concat(page), []);",
    },
  ],
  invalid: [
    {
      name: "reports copies of an awaited accumulator",
      code: "declare const calls: string[]; declare function run(call: string): Promise<number>; export async function answers(): Promise<number[]> { return calls.reduce<Promise<number[]>>(async (done, call) => [...(await done), await run(call)], Promise.resolve([])); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "follows a stable awaited accumulator alias",
      code: "declare const calls: string[]; declare function run(call: string): Promise<number>; export async function answers(): Promise<number[]> { return calls.reduce<Promise<number[]>>(async (previous, call) => { const done = await previous; const next = await run(call); return [...done, next]; }, Promise.resolve([])); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "returns the existing fresh identity collection",
      code: "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: "export function collect(): string[] { return ['a', 'b']; }",
      errors: [{ messageId: "copy" }],
    },
    {
      name: "preserves static computed reduce and CRLF",
      code: "export function collect(): string[] {\r\n  return ['a', 'b']['reduce']<string[]>((acc, item) => [...acc, item], []);\r\n}",
      output:
        "export function collect(): string[] {\r\n  return ['a', 'b'];\r\n}",
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains imported execution authority",
      code: "import \"setup\"; export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains comments",
      code: "/* collection policy */ export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains callback snapshots",
      code: "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => { consume(acc); return [...acc, item]; }, []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains sparse input arrays",
      code: "export function collect(): string[] { return ['a', , 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains reverse reductions",
      code: "export function collect(): string[] { return ['a', 'b'].reduceRight<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains reversed accumulation",
      code: "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [item, ...acc], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains flattening semantics",
      code: "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, ...item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains callback index contracts",
      code: "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item, index) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains readonly return contracts",
      code: "export function collect(): readonly string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains inferred return contracts",
      code: "export function collect() { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains function type parameters",
      code: "export function collect<T>(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains dynamic input values",
      code: "export function collect(value: string): string[] { return ['a', value].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains other function statements",
      code: "export function collect(): string[] { observe(); return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      name: "retains custom prototype authority",
      code: "Array.prototype.reduce = customReduce; export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => Object.assign({}, acc, { [key]: value }), {});",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pairs: [string, string][]; pairs.reduce<Record<string, string>>((acc, [key, value]) => ({ ...acc, [key]: value }), {});",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => acc.concat(page), []);",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduceRight<string[]>((acc, page) => [...acc, ...page], []);",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const next = acc.slice(); next.push(...page); return next; }, []);",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduce<string[]>((acc) => Array.from(acc), []);",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduce<string[]>((acc) => acc['toReversed'](), []);",
      errors: [{ messageId: "copy" }],
    },
    {
      code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page, index) => acc.concat(page), []);",
      errors: [{ messageId: "copy" }],
    },
  ],
}));

TESTER.run("no-reduce-accumulator-copy without a type project", rule, {
  valid: [{ code: "items.reduce((acc, item) => acc.concat(item), []);", settings: { sarj: { typeAware: false } } }],
  invalid: [],
});

TESTER.run("no-reduce-accumulator-copy retained extensions", rule, typed({
  valid: [
    { name: "preserves a mutated alias", code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { let previous = acc; previous = page; return previous.concat(page); }, []);" },
    { name: "preserves an escaped seed", code: "declare const pages: string[][]; const seed: string[] = []; observe(seed); pages.reduce((acc, page) => acc.concat(page), seed);" },
    { name: "preserves seed snapshots after reduction", code: "declare const pages: string[][]; const seed: string[] = []; const rows = pages.reduce((acc, page) => acc.concat(page), seed); observe(seed);" },
    { name: "preserves nested callback aliases", code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const copy = () => { const previous = acc; return previous.concat(page); }; return page; }, []);" },
  ],
  invalid: [
    { name: "follows a stable accumulator alias", code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const previous = acc; return previous.concat(page); }, []);", output: null, errors: [{ messageId: "copy" }] },
    { name: "follows an alias chain", code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { const first = acc; const second = first; return [...second, ...page]; }, []);", output: null, errors: [{ messageId: "copy" }] },
    { name: "recognizes a single-use seed alias", code: "declare const pages: string[][]; const seed: string[] = []; pages.reduce((acc, page) => acc.concat(page), seed);", output: null, errors: [{ messageId: "copy" }] },
    { name: "recognizes a seed alias chain", code: "declare const pages: string[][]; const first: string[] = []; const seed = first; pages.reduce((acc, page) => acc.concat(page), seed);", output: null, errors: [{ messageId: "copy" }] },
    { name: "keeps reverse reduction manual", code: "declare const pages: string[][]; pages.reduceRight<string[]>((acc, page) => { const previous = acc; return previous.concat(page); }, []);", output: null, errors: [{ messageId: "copy" }] },
    { name: "keeps retained accumulator snapshots manual", code: "declare const pages: string[][]; pages.reduce<string[]>((acc, page) => { observe(acc); const previous = acc; return previous.concat(page); }, []);", output: null, errors: [{ messageId: "copy" }] },
  ],
}));
