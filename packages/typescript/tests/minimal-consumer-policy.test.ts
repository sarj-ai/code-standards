import { join } from "node:path";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

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
  [CONSUMER_UNION, "interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string} function label(p: Dog | Animal): string {return p.name;} label(account);"],
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

  it("stages the semantic finding as one warning alongside existing owners", async () => {
    const code = `${PREFIX}type Role = string | 'reader';\ndeclare const user: {name: string; accountId: string};\nconst erased: unknown = user;\nconst view = <Avatar {...{name: user.name, accountId: user.accountId}} />;`;
    const [result] = await eslint.lintText(code, {filePath: "policy.tsx"});
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ruleId, severity}) => [ruleId, severity])).toEqual([[REDUNDANT, 2], [WIDENING, 2], [RULE, 1]]);
    expect(result?.warningCount).toBe(1);
    expect(result?.errorCount).toBe(2);
    expect(new Set(result?.messages.map(({line, column}) => `${line}:${column}`)).size).toBe(3);
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
    expect(result?.messages[0]?.fix).toBeUndefined();
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
