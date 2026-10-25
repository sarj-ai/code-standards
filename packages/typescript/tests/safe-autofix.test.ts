// vitest: shared-module-graph
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import commentRule from "../src/rules/no-restated-jsdoc.js";
import conditionalRule from "../src/rules/no-conditional-empty-object-spread.js";
import schemaNameRule from "../src/rules/require-pascal-case-zod-schema-name.js";
import switchRule from "../src/rules/prefer-switch-for-repeated-equality.js";
import typedDocRule from "../src/rules/no-typed-doc-sections.js";

type TestedRule = typeof switchRule | typeof conditionalRule | typeof commentRule | typeof schemaNameRule | typeof typedDocRule;

function apply(rule: TestedRule, source: string): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(source, [{
    files: ["**/*.ts"],
    languageOptions: { parser },
    plugins: { sarj: { rules: { example: rule } } },
    rules: { "sarj/example": "error" },
  }], { filename: "src/example.ts" });
}

function expectConverged(rule: TestedRule, source: string): string {
  const first = apply(rule, source);
  expect(first.fixed).toBe(true);
  expect(first.messages).toEqual([]);
  const second = apply(rule, first.output);
  expect(second.fixed).toBe(false);
  expect(second.output).toBe(first.output);
  expect(second.messages).toEqual([]);
  return first.output;
}

function evaluate(source: string): unknown {
  return runInNewContext(`${source}\nJSON.stringify(result);`);
}

describe("safe automatic fixes preserve observable behavior", () => {
  it.each([false, true, 0, 1, "", "ready", null, undefined])("preserves conditional property omission and evaluation order for %s", (condition) => {
    const source = `const order = []; const condition = ${String(JSON.stringify(condition))};
      const value = { before: (order.push('before'), 0), ...((order.push('condition'), condition) ? { get item() { order.push('getter'); return 1; } } : {}), after: (order.push('after'), 2) };
      const result = [value, Object.keys(value), order];`;
    const fixed = expectConverged(conditionalRule, source);
    expect(evaluate(fixed)).toBe(evaluate(source));
  });

  it("preserves inverted conditional branches and symbol property ownership", () => {
    const source = `const key = Symbol('key'); const condition = false;
      const value = { ...(condition ? {} : { [key]: 1 }), x: 2 };
      const result = [Reflect.ownKeys(value).map(String), value[key]];`;
    expect(evaluate(expectConverged(conditionalRule, source))).toBe(evaluate(source));
  });

  it("preserves branch lexical scopes, fallthrough boundaries and loop continues", () => {
    const source = `const trace = []; for (const kind of ['a', 'b', 'c', 'd']) {
      if (kind === 'a') { const value = 'first'; trace.push(value); continue; }
      else if ('b' === kind) { const value = 'second'; trace.push(value); continue; }
      else if (kind === 'c') { const value = 'third'; trace.push(value); continue; }
      else { trace.push('last'); }
      trace.push('tail');
    } const result = trace;`;
    expect(evaluate(expectConverged(switchRule, source))).toBe(evaluate(source));
  });

  it("preserves duplicate cases, early returns and thrown exceptions", () => {
    const source = `function probe(kind) {
      if (kind === 'a') return 'first'; else if (kind === 'a') return 'unreachable'; else if (kind === 'c') throw new Error('third');
      else return 'other';
    } const result = ['a', 'b', 'c'].map((kind) => { try { return probe(kind); } catch (error) { return error.message; } });`;
    expect(evaluate(expectConverged(switchRule, source))).toBe(evaluate(source));
  });
});

describe("unsafe subsets remain report-only", () => {
  it.each([
    "function f(kind) { for (;;) { if (kind === 'a') break; else if (kind === 'b') stop(); else if (kind === 'c') finish(); } }",
    "function f(kind) { if (kind === 'a') { /* branch ownership */ a(); } else if (kind === 'b') b(); else if (kind === 'c') c(); }",
    "function f(kind) { if (kind === 'a') { function nested() {} nested(); } else if (kind === 'b') b(); else if (kind === 'c') c(); }",
  ])("preserves control-flow and comments in %s", (source) => {
    const result = apply(switchRule, source);
    expect(result.fixed).toBe(false);
    expect(result.messages).toHaveLength(1);
  });

  it.each([
    "const value = { ...(ready ? data : {}) };",
    "const value = { ...(ready ? {} : {}) };",
    "const value = { ...(ready ? { item: 1 } : { /* intentional omission */ }) };",
  ])("preserves unresolved branch contracts in %s", (source) => {
    const result = apply(conditionalRule, source);
    expect(result.fixed).toBe(false);
    expect(result.messages).toHaveLength(1);
  });

  it("does not retarget next-line TypeScript directives through JSDoc deletion", () => {
    const source = "// @ts-expect-error -- The following documentation line is intentionally targeted.\n/** Get user. */\nfunction getUser() { return 1; }";
    const result = apply(commentRule, source);
    expect(result.fixed).toBe(false);
    expect(result.messages).toHaveLength(1);
  });

  it("does not remove line terminators beside a preceding statement", () => {
    const source = "const prior = 1; /** Get user. */\nfunction getUser() { return prior; }";
    expect(apply(commentRule, source).fixed).toBe(false);
  });
});

describe("private schema renames retain public keys and binding identity", () => {
  it("retains shorthand object property names and type queries", () => {
    const source = 'import { z } from "zod"; const USER_SCHEMA = z.string(); const exposed = { USER_SCHEMA }; type Contract = typeof USER_SCHEMA; consume(USER_SCHEMA);';
    const fixed = expectConverged(schemaNameRule, source);
    expect(fixed).toBe('import { z } from "zod"; const UserSchema = z.string(); const exposed = { USER_SCHEMA: UserSchema }; type Contract = typeof UserSchema; consume(UserSchema);');
  });

  it("converges across one thousand independent private schema bindings", () => {
    const source = ['import { z } from "zod";', ...Array.from({ length: 1000 }, (_, index) => `const value${String(index)} = z.string();`)].join("\n");
    const fixed = expectConverged(schemaNameRule, source);
    expect(fixed).toContain("const Value0Schema = z.string();");
    expect(fixed).toContain("const Value999Schema = z.string();");
  });

  it.each([
    'import { z } from "zod"; const USER_SCHEMA = z.string(); export { USER_SCHEMA };',
    'import { z } from "zod"; const USER_SCHEMA = z.string(); export { USER_SCHEMA as publicSchema };',
    'import { z } from "zod"; const USER_SCHEMA = z.string(); export default USER_SCHEMA;',
    'import { z } from "zod"; const UserSchema = 1; const USER_SCHEMA = z.string();',
    'import { z } from "zod"; const USER_SCHEMA = z.string(); function f(UserSchema) { return USER_SCHEMA; }',
    'import { z } from "zod"; const USER_SCHEMA = z.string(); eval("USER_SCHEMA");',
    'import { z } from "zod"; const user = z.string(); consume(UserSchema); consume(user);',
    "import { z } from \"zod\"; const user = z.string(); consume(\\u0055serSchema); consume(user);",
  ])("preserves exports, collisions and dynamic references in %s", (source) => {
    expect(apply(schemaNameRule, source).fixed).toBe(false);
  });
});

describe("typed JSDoc removal retains useful documentation", () => {
  it("removes only the vacuous tag and preserves continuation paragraphs and custom tags", () => {
    const source = "/** Fetches the most recent version.\n * @param id the identifier\n * @returns The current version after validation.\n *   Throws before mutation when validation fails.\n * @custom owner=platform\n */\nfunction read(id: string): string { return id; }";
    const result = expectConverged(typedDocRule, source);
    expect(result).toBe("/**\n * Fetches the most recent version.\n * @returns The current version after validation.\n *   Throws before mutation when validation fails.\n * @custom owner=platform\n */\nfunction read(id: string): string { return id; }");
  });

  it("retains CRLF and indentation when deleting a multiline JSDoc block", () => {
    const source = "class Client {\r\n\t/**\r\n\t * Get user.\r\n\t */\r\n\tgetUser() { return 1; }\r\n}";
    expect(expectConverged(commentRule, source)).toBe("class Client {\r\n\r\n\r\n\r\n\tgetUser() { return 1; }\r\n}");
  });
});


it("preserves strict spread inference and switch branch narrowing", () => {
  const source = [
    "declare const unknownCondition: unknown;",
    "declare const numberCondition: number;",
    "declare const stringCondition: string;",
    "declare const anyCondition: any;",
    "declare const booleanCondition: boolean | undefined;",
    ...["unknown", "number", "string", "any", "boolean"].map((name) => `export const ${name}Value = { ...( ${name}Condition ? { item: 1 } : {}) };`),
    "export function generic<T>(condition: T) { return { ...(condition ? { item: condition } : {}) }; }",
    "export function genericInverted<T>(condition: T) { return { ...(condition ? {} : { item: condition }) }; }",
    "export function exhaustive(kind: 'a' | 'b' | 'c' | 'd') { if (kind === 'a') { const a: 'a' = kind; return a; } else if (kind === 'b') { const b: 'b' = kind; return b; } else if (kind === 'c') { const c: 'c' = kind; return c; } else { const d: 'd' = kind; return d; } }",
    "export function loop(values: readonly ('a' | 'b' | 'c' | 'd')[]) { let result = ''; for (const kind of values) { if (kind === 'a') { const a: 'a' = kind; result += a; continue; } else if (kind === 'b') { const b: 'b' = kind; result += b; continue; } else if (kind === 'c') { const c: 'c' = kind; result += c; continue; } else { const d: 'd' = kind; result += d; } } return result; }",
  ].join("\n");
  const fixed = expectConverged(switchRule, expectConverged(conditionalRule, source));
  const virtual = new Map([["/autofix-before.ts", source], ["/autofix-after.ts", fixed]]);
  const options: ts.CompilerOptions = { strict: true, noEmit: true, types: [], target: ts.ScriptTarget.ESNext, skipLibCheck: true, allowUnreachableCode: false, noFallthroughCasesInSwitch: true };
  const host = ts.createCompilerHost(options);
  const getSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (filename, languageVersion, onError, shouldCreateNewSourceFile) => {
    const text = virtual.get(filename);
    return text === undefined ? getSourceFile(filename, languageVersion, onError, shouldCreateNewSourceFile) : ts.createSourceFile(filename, text, languageVersion, true);
  };
  const program = ts.createProgram([...virtual.keys()], options, host);
  expect(ts.getPreEmitDiagnostics(program).map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))).toEqual([]);
  const checker = program.getTypeChecker();
  const contracts = [...virtual.keys()].map((filename) => {
    const file = program.getSourceFile(filename)!;
    const symbol = checker.getSymbolAtLocation(file)!;
    return checker.getExportsOfModule(symbol).map((exported) => [exported.name, checker.typeToString(checker.getTypeOfSymbolAtLocation(exported, file))]);
  });
  expect(contracts[1]).toEqual(contracts[0]);
});
