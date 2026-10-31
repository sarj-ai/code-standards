import { join } from "node:path";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";
import ts from "typescript";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_ROOT = join(import.meta.dirname, "fixtures", "minimal-consumer");
const RULE = "@sarj/no-excess-jsx-props";
const WIDENING = "@sarj/no-known-value-widening";
const REDUNDANT = "@typescript-eslint/no-redundant-type-constituents";
const DEPENDENCY = "@sarj/prefer-minimal-parameter-contract";
const CONSUMER_UNION = "@sarj/no-redundant-consumer-union";
const SELECTED = new Set([RULE, DEPENDENCY, CONSUMER_UNION, WIDENING, REDUNDANT, "@sarj/no-broad-return-type", "react/jsx-props-no-spreading", "react/no-unused-prop-types"]);
const PREFIX = "export {}; declare namespace JSX { interface Element {} interface IntrinsicAttributes {key?: string} interface IntrinsicElements {span: {children?: unknown}} }\nconst Avatar = ({name}: {name: string}): JSX.Element => <span>{name}</span>;\n";
const PRIVATE_PREFIX = 'export {}; const account = {name: "Ada", email: "a"};\n';
const PRIVATE_CASES = [
  [DEPENDENCY, "function label(p: {readonly name: string; readonly email: string}): string {return p.name;} label(account);"],
  [DEPENDENCY, "const nullableAccount = {...account, email: null}; function label(p: {name: string; email: string | null}): string {return p.name;} label(nullableAccount);"],
  [DEPENDENCY, "const nullableAccount = {...account, email: undefined}; function label(p: {readonly name: string; readonly email: undefined | string}): string {return p.name;} label(nullableAccount);"],
  [DEPENDENCY, "const nullableAccount = {...account, name: null}; function label(p: {readonly name: string | null; readonly email: string}): string {return p.name ?? '';} label(nullableAccount);"],
  [CONSUMER_UNION, "interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string} function label(p: Dog | Animal): string {return p.name;} label(account);"],
  [CONSUMER_UNION, "interface Animal {readonly name: string} interface Dog extends Animal {readonly email?: string} function label(p: Dog | Animal): string {return p.name;} label(account);"],
  [CONSUMER_UNION, "interface Animal {readonly name: string | null} interface Dog extends Animal {readonly email: string} function label(p: Dog | Animal): string {return p.name ?? '';} label(account);"],
] as const;
type ConfigFactory = (options: {tsconfigRootDir: string; projectService?: boolean}) => Linter.Config[];
const FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createConfig as ConfigFactory],
  ["application", createApplicationConfig as ConfigFactory],
];

function selectedConfig(factory: ConfigFactory): Linter.Config[] {
  return factory({tsconfigRootDir: FIXTURE_ROOT, projectService: true}).map((entry) => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => SELECTED.has(id))),
  }));
}

describe.each(FACTORIES)("%s minimal consumer policy", (_name, factory) => {
  const eslint = new ESLint({cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: selectedConfig(factory)});

  it.each([
    ["concrete data", "const user = {name: 'Ada', accountId: 'a'};", 1],
    ["ambient values remain outside the runtime proof", "declare const user: {name: string; accountId: string};", 0],
  ] as const)("preserves warning policy alongside existing owners: %s", async (_boundary, source, warnings) => {
    const code = `${PREFIX}type Role = string | 'reader';\n${source}\nconst erased: unknown = user;\nconst view = <Avatar {...{name: 'Ada', accountId: user.accountId}} />;`;
    const [result] = await eslint.lintText(code, {filePath: "policy.tsx"});
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[REDUNDANT, 2], [WIDENING, 2], ...(warnings ? [[RULE, 1]] : [])]);
    expect(result?.warningCount).toBe(warnings);
    expect(result?.errorCount).toBe(2);
    expect(new Set(result?.messages.map(({line, column}) => `${line}:${column}`)).size).toBe(2 + warnings);
  });

  it("does not treat an opaque source field annotation as primitive provenance", async () => {
    const [result] = await eslint.lintText(`${PREFIX}declare const user: {name: string; accountId: string}; const view = <Avatar {...{name: user.name, accountId: user.accountId}} />;`, {filePath: "policy.tsx"});
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages).toEqual([]);
  });

  it("supports an exact reasoned suppression", async () => {
    const [result] = await eslint.lintText(`${PREFIX}// eslint-disable-next-line ${RULE} -- this adapter intentionally preserves an independently reviewed runtime boundary\nconst view = <Avatar {...{name: 'Ada', accountId: 'a'}} />;`, {filePath: "policy.tsx"});
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ruleId}) => ruleId)).toEqual([RULE]);
  });

  it.each(PRIVATE_CASES)("stages %s once without duplicate upstream ownership", async (ruleId, source) => {
    const [result] = await eslint.lintText(`${PRIVATE_PREFIX}${source}`, {filePath: "policy.tsx"});
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[ruleId, 1]]);
    if (ruleId === DEPENDENCY) expect(result?.messages[0]?.fix).toBeDefined();
    else expect(result?.messages[0]?.fix).toBeUndefined();
    expect(result?.messages[0]?.suggestions).toBeUndefined();
  });

  it.each(PRIVATE_CASES)("honors an exact reviewed suppression for %s", async (ruleId, source) => {
    const [result] = await eslint.lintText(`${PRIVATE_PREFIX}// eslint-disable-next-line ${ruleId} -- preserve this independently reviewed private contract\n${source}`, {filePath: "policy.tsx"});
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ruleId}) => ruleId)).toEqual([ruleId]);
  });

  it("leaves runtime projection and API edits to the author", async () => {
    const fixer = new ESLint({cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: selectedConfig(factory), fix: true});
    const [result] = await fixer.lintText(`${PREFIX}const view = <Avatar {...{name: 'Ada', accountId: 'a'}} />;`, {filePath: "policy.tsx"});
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[RULE, 1]]);
  });

  it("preserves a malformed-input analysis failure without a confident finding", async () => {
    const [result] = await eslint.lintText(`${PREFIX}const view = <Avatar {...{name: }} />;`, {filePath: "policy.tsx"});
    expect(result?.fatalErrorCount).toBe(1);
    expect(result?.messages[0]?.message).toContain("Expression expected");
    expect(result?.messages.map(({ruleId}) => ruleId)).toEqual([null]);
  });
});


function nativeContract(source: string, noUnusedLocals = false): {readonly diagnostics: readonly number[]; readonly javascript: readonly string[]} {
  const filename = join(FIXTURE_ROOT, "autofix-native-contract.ts");
  const options: ts.CompilerOptions = {strict: true, target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], lib: ["lib.esnext.d.ts"], noEmitOnError: true, noUnusedLocals};
  const host = ts.createCompilerHost(options);
  const originalGetSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (name, languageVersion, onError, shouldCreateNewSourceFile) => name === filename
    ? ts.createSourceFile(name, source, languageVersion, true)
    : originalGetSourceFile(name, languageVersion, onError, shouldCreateNewSourceFile);
  const program = ts.createProgram([filename], options, host);
  const diagnostics = ts.getPreEmitDiagnostics(program).map((diagnostic) => diagnostic.code);
  const javascript: string[] = [];
  if (!diagnostics.length) program.emit(undefined, (name, text) => { if (name.endsWith(".js")) javascript.push(text); });
  return {diagnostics, javascript};
}

describe.each(FACTORIES)("%s closed private contract safe fixes", (_name, factory) => {
  const fixer = new ESLint({cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: selectedConfig(factory), fix: true});
  it.each(PRIVATE_CASES)("fixes %s without changing producer, JavaScript or caller validity", async (_rule, declaration) => {
    const body = _rule === CONSUMER_UNION ? declaration.replace("function label", "export type KeptDog = Dog; const typedAccount: Dog = account; function label").replace("label(account)", "label(typedAccount)") : declaration;
    const source = `${PRIVATE_PREFIX}${body}`;
    const before = nativeContract(source, true);
    expect(before.diagnostics).toEqual([]);
    const [result] = await fixer.lintText(source, {filePath: "policy.tsx"});
    expect(result?.output).toBeDefined();
    expect(result?.output).not.toBe(source);
    expect(result?.messages).toEqual([]);
    const after = nativeContract(result?.output ?? source, true);
    expect(after.diagnostics).toEqual([]);
    expect(after.javascript).toEqual(before.javascript);
    const [second] = await fixer.lintText(result?.output ?? source, {filePath: "policy.tsx"});
    expect(second?.output).toBeUndefined();
    expect(second?.messages).toEqual([]);
  });
  it("does not use another removable producer annotation as its survival proof", async () => {
    const source = `${PRIVATE_PREFIX}interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string} const typedAccount: Dog = account; function label(p: Dog | Animal): string {return p.name;} label(typedAccount);`;
    expect(nativeContract(source, true).diagnostics).toEqual([]);
    const [result] = await fixer.lintText(source, {filePath: "policy.tsx"});
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[CONSUMER_UNION, 1]]);
  });
  it("retains sole covered type uses under native and strict lint unused checks", async () => {
    const prefix = "export {}; interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string} const account = {name: 'Ada', email: 'a'};";
    const source = `${prefix}function label(p: Dog | Animal): string {return p.name;} label(account);`;
    expect(nativeContract(source, true).diagnostics).toEqual([]);
    const naive = source.replace("Dog | Animal", "Animal");
    expect(nativeContract(naive, true).diagnostics.some((code) => code === 6196 || code === 6133)).toBe(true);
    const strict = new ESLint({cwd: FIXTURE_ROOT, overrideConfigFile: true,
      overrideConfig: [...selectedConfig(factory), {rules: {"@typescript-eslint/no-unused-vars": "error"}}], fix: true});
    const [result] = await strict.lintText(source, {filePath: "policy.tsx"});
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[CONSUMER_UNION, 1]]);
    const [counterexample] = await strict.lintText(naive, {filePath: "policy.tsx"});
    expect(counterexample?.messages.some(({ruleId, severity}) => ruleId === "@typescript-eslint/no-unused-vars" && severity === 2)).toBe(true);
    const pair = `${prefix}function first(p: Dog | Animal): string {return p.name;} function second(p: Dog | Animal): string {return p.name;} first(account); second(account);`;
    expect(nativeContract(pair, true).diagnostics).toEqual([]);
    expect(nativeContract(pair.replaceAll("Dog | Animal", "Animal"), true).diagnostics.some((code) => code === 6196 || code === 6133)).toBe(true);
    const [two] = await strict.lintText(pair, {filePath: "policy.tsx"});
    expect(two?.output).toBeUndefined();
    expect(two?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[CONSUMER_UNION, 1], [CONSUMER_UNION, 1]]);
  });
  it("refuses the fresh-literal TS2353 and invalid-identifier TS2345 counterexamples", async () => {
    const declaration = "function label(p: {readonly name: string; readonly email: string}): string {return p.name;}";
    const fresh = `export {}; ${declaration} label({name: 'Ada', email: 'a'});`;
    expect(nativeContract(fresh).diagnostics).toEqual([]);
    expect(nativeContract(fresh.replace("readonly email: string", "")).diagnostics).toContain(2353);
    const [freshResult] = await fixer.lintText(fresh, {filePath: "policy.tsx"});
    expect(freshResult?.output).toBeUndefined();
    const invalid = `export {}; const account = {name: 'Ada', email: 42}; ${declaration} label(account);`;
    expect(nativeContract(invalid).diagnostics).toContain(2345);
    expect(nativeContract(invalid.replace("readonly email: string", "")).diagnostics).toEqual([]);
    const [invalidResult] = await fixer.lintText(invalid, {filePath: "policy.tsx"});
    expect(invalidResult?.output).toBeUndefined();
    expect(invalidResult?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[DEPENDENCY, 1]]);
  });
  it("preserves an optional covering field that can reject an existing identifier", async () => {
    const source = "export {}; interface Source {readonly name: string; readonly email: string} interface Covering {readonly name: string; readonly extra?: string} const account = {name: 'Ada', email: 'a', extra: 123}; function label(p: Source | Covering): string {return p.name;} label(account);";
    expect(nativeContract(source).diagnostics).toEqual([]);
    expect(nativeContract(source.replace("Source | Covering", "Covering")).diagnostics).toContain(2345);
    const [result] = await fixer.lintText(source, {filePath: "policy.tsx"});
    expect(result?.output).toBeUndefined();
    expect(result?.messages).toEqual([]);
  });
  it("retains a necessary ts-expect-error instead of creating TS2578", async () => {
    const source = "export {}; const account = {name: 'Ada'}; function label(p: {readonly name: string; readonly email: string}): string {return p.name;}\n// @ts-expect-error the original contract requires email\nlabel(account);";
    expect(nativeContract(source).diagnostics).toEqual([]);
    expect(nativeContract(source.replace("readonly email: string", "")).diagnostics).toContain(2578);
    const [result] = await fixer.lintText(source, {filePath: "policy.tsx"});
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[DEPENDENCY, 1]]);
  });
});
