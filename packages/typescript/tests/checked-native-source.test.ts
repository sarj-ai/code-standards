import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import { checkedNativeSource } from "../src/rules/_checked-native-source.js";
import noExcessJSXProps from "../src/rules/no-excess-jsx-props.js";
import noRedundantConsumerUnion from "../src/rules/no-redundant-consumer-union.js";
import preferMinimalParameterContract from "../src/rules/prefer-minimal-parameter-contract.js";
import { CONSUMER_PREFIX, INLINE_CONTRACT, UNION_DECLARATIONS } from "./private-consumer-cases.js";

it("requires active native checking while preserving literal and JSX comment near misses", () => {
  const root = mkdtempSync(join(tmpdir(), "native-source-check-"));
  try {
    const cases = [
      ["healthy.ts", "const value = 1;", true, []],
      ["error.ts", "const value: string = 1;", false, [2322]],
      ["ignore.ts", "// @ts-ignore\nconst value: string = 1;", false, []],
      ["expect.ts", "// @ts-expect-error\nconst value: string = 1;", false, []],
      ["inline.ts", "const first = 1; // @ts-ignore\nconst value: string = 1;", false, []],
      ["punctuation.ts", "const object = {first: 1,\n// @ts-ignore\n}; const value: string = 1;", false, []],
      ["block.ts", "/* @ts-ignore */\nconst value: string = 1;", false, []],
      ["unicode-line.ts", "/* ordinary\u2028 @ts-ignore */\nconst value: string = 1;", false, []],
      ["prefix.ts", "// @ts-ignore-extra\nconst value: string = 1;", false, []],
      ["nocheck.ts", "// @TS-NOCHECK\nconst value: string = 1;", false, []],
      ["mixed-nocheck.ts", "// @Ts-NoCheck: fixture\nconst value: string = 1;", false, []],
      ["eof.ts", "const value = 1;\n// @ts-ignore", false, []],
      ["string.ts", 'const value = "// @ts-ignore";', true, []],
      ["template.ts", "const value = `// @ts-ignore\nordinary text`;", true, []],
      ["template-expression.ts", "const value = `before${ // @ts-ignore\nmissing }after`;", false, []],
      ["regexp.ts", "const value = /[//] @ts-ignore/;", true, []],
      ["documentation.ts", "/** Documentation showing // @ts-ignore */\nconst value = 1;", true, []],
      ["four-slashes.ts", "//// @ts-ignore\nconst value = 1;", true, []],
      ["unknown-pragma.ts", "// @ts-nocheck-extra\nconst value = 1;", true, []],
      ["late-nocheck.ts", "const first = 1; // @TS-NOCHECK\nconst value = 1;", true, []],
      ["jsx.tsx", "declare global {namespace JSX {interface Element {} interface IntrinsicElements {span: {children?: unknown}}}} const value = <span>// @ts-ignore\nordinary text</span>;", true, []],
    ] as const;
    for (const [file, source] of cases) writeFileSync(join(root, file), `${source.startsWith("// @") ? source + "\nexport {};" : "export {};\n" + source}\n`);
    const options: ts.CompilerOptions = {strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], jsx: ts.JsxEmit.Preserve};
    const program = ts.createProgram(cases.map(([file]) => join(root, file)), options);
    expect(program.getOptionsDiagnostics()).toEqual([]);
    expect(program.getGlobalDiagnostics()).toEqual([]);
    expect(program.getSyntacticDiagnostics()).toEqual([]);
    for (const [file, , available, codes] of cases) {
      const source = program.getSourceFile(join(root, file));
      if (!source) throw new Error(`Native checking fixture was not loaded: ${file}`);
      expect(program.getSemanticDiagnostics(source).map((diagnostic) => diagnostic.code), file).toEqual(codes);
      expect(checkedNativeSource(program, source), file).toBe(available);
      expect(checkedNativeSource(program, source), `repeated ${file}`).toBe(available);
    }
    const disabled = ts.createProgram([join(root, "healthy.ts")], {...options, noCheck: true});
    const disabledSource = disabled.getSourceFile(join(root, "healthy.ts"));
    const healthy = program.getSourceFile(join(root, "healthy.ts"));
    if (!disabledSource || !healthy) throw new Error("Native checking policy fixtures were not loaded");
    expect(disabled.getSemanticDiagnostics(disabledSource)).toEqual([]);
    expect(checkedNativeSource(disabled, disabledSource)).toBe(false);
    expect(checkedNativeSource(program, disabledSource)).toBe(false);
    expect(checkedNativeSource(program, healthy)).toBe(true);
    const referenced = ts.createProgram({rootNames: [join(root, "healthy.ts")], options, projectReferences: [{path: join(root, "unavailable-reference")}]});
    const redirected = referenced.getSourceFile(join(root, "healthy.ts"));
    if (!redirected) throw new Error("Referenced native fixture was not loaded");
    expect(checkedNativeSource(referenced, redirected)).toBe(false);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it("does not mistake local JSX contracts for an available automatic runtime module", () => {
  const root = mkdtempSync(join(tmpdir(), "native-jsx-check-"));
  try {
    const file = join(root, "consumer.tsx");
    writeFileSync(file, "export {}; declare namespace JSX {interface Element {} interface IntrinsicElements {span: {children?: unknown}}} const Avatar = ({name}: {name: string}): JSX.Element => <span>{name}</span>; const element = <Avatar {...{name: 'Ada', extra: 'unused'}}/>; const shown = (element as {props: {name: string}}).props.name; export {shown};");
    const options: ts.CompilerOptions = {strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], jsx: ts.JsxEmit.ReactJSX};
    const missing = ts.createProgram([file], options);
    const incomplete = missing.getSourceFile(file);
    if (!incomplete) throw new Error("Native JSX fixture was not loaded");
    expect(missing.getSemanticDiagnostics(incomplete).map((diagnostic) => diagnostic.code)).toContain(2875);
    expect(checkedNativeSource(missing, incomplete)).toBe(false);
    const runtime = join(root, "jsx-runtime.d.ts");
    writeFileSync(runtime, readFileSync(join(import.meta.dirname, "fixtures", "minimal-consumer", "jsx-runtime.d.ts")));
    const available = ts.createProgram([file, runtime], options);
    const complete = available.getSourceFile(file);
    if (!complete) throw new Error("Complete native JSX fixture was not loaded");
    expect(ts.getPreEmitDiagnostics(available)).toEqual([]);
    expect(checkedNativeSource(available, complete)).toBe(true);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

function suppliedConsumerConfiguration(program: ts.Program): Linter.Config {
  const identity: Rule.RuleModule = {create(context) {
    const services: unknown = context.sourceCode.parserServices;
    if (typeof services !== "object" || services === null || !("program" in services)) throw new Error("Supplied native Program is unavailable");
    expect(services.program).toBe(program);
    return {};
  }};
  return {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {parser: tsParser, parserOptions: {programs: [program], projectService: false, ecmaFeatures: {jsx: true}}},
    plugins: {local: {rules: {
      minimal: preferMinimalParameterContract as unknown as Rule.RuleModule,
      redundant: noRedundantConsumerUnion as unknown as Rule.RuleModule,
      excess: noExcessJSXProps as unknown as Rule.RuleModule,
      identity,
    }}},
    rules: {"local/minimal": "warn", "local/redundant": "warn", "local/excess": "warn", "local/identity": "warn"},
  };
}

it("rejects changed text against a warmed supplied Program without losing current consumer findings", () => {
  const root = mkdtempSync(join(tmpdir(), "native-source-text-"));
  try {
    const readonly = `${CONSUMER_PREFIX}function label(p: ${INLINE_CONTRACT}): string {return p.name ;} label(account);`;
    const ordinary = readonly.replaceAll("readonly ", "");
    const union = `${CONSUMER_PREFIX}${UNION_DECLARATIONS} export type KeptDog = Dog; function label(p: Dog | Animal): string {return p.name;} label(account);`;
    const jsx = "export {}; declare namespace JSX {interface Element {} interface IntrinsicElements {span: {children?: unknown}}} const Avatar = ({name}: {name: string}): JSX.Element => <span>{name}</span>; const element = <Avatar {...{name: 'Ada', email: 'a'}}/>; const shown = (element as {props: {name: string}}).props.name;";
    const cases = [
      {file: "readonly.ts", original: readonly, current: readonly.replace("p.name ;", "p.email;"), rule: "minimal", messageId: "minimal", originalDetail: "reads only name but also requires email", currentDetail: "reads only email but also requires name", fix: true},
      {file: "ordinary.ts", original: ordinary, current: ordinary.replace("p.name ;", "p.email;"), rule: "minimal", messageId: "minimal", originalDetail: "reads only name but also requires email", currentDetail: "reads only email but also requires name", fix: true},
      {file: "union.ts", original: union, current: union.replace("Dog | Animal", "Dog & Animal"), rule: "redundant", messageId: "redundant", originalDetail: "Dog is already accepted by Animal", currentDetail: null, fix: true},
      {file: "element.tsx", original: jsx, current: jsx.replace("email: 'a'", "title: 'a'"), rule: "excess", messageId: "excess", originalDetail: "email", currentDetail: "title", fix: false},
    ] as const;
    const runtime = join(root, "jsx-runtime.d.ts");
    writeFileSync(runtime, readFileSync(join(import.meta.dirname, "fixtures", "minimal-consumer", "jsx-runtime.d.ts")));
    for (const entry of cases) {
      expect(entry.current).not.toBe(entry.original);
      expect(entry.current.length).toBe(entry.original.length);
      writeFileSync(join(root, entry.file), entry.original);
    }
    const roots = [...cases.map((entry) => join(root, entry.file)), runtime];
    const options: ts.CompilerOptions = {strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], jsx: ts.JsxEmit.ReactJSX};
    const original = ts.createProgram(roots, options);
    expect(ts.getPreEmitDiagnostics(original)).toEqual([]);
    const linter = new Linter({cwd: root});
    const configuration = suppliedConsumerConfiguration(original);
    const expectMatching = (config: Linter.Config, current: boolean): void => {
      for (const entry of cases) {
        const text = current ? entry.current : entry.original;
        const detail = current ? entry.currentDetail : entry.originalDetail;
        const messages = linter.verify(text, config, {filename: join(root, entry.file)});
        expect(messages.filter((message) => message.fatal || message.ruleId !== `local/${entry.rule}`), entry.file).toEqual([]);
        expect(messages, entry.file).toHaveLength(detail === null ? 0 : 1);
        for (const message of messages) {
          expect(message.messageId).toBe(entry.messageId);
          expect(message.message).toContain(detail);
          expect(message.severity).toBe(1);
          expect(message.fix !== undefined).toBe(entry.fix);
          expect(message.suggestions).toBeUndefined();
        }
        expect(linter.verify(text, config, {filename: join(root, entry.file)})).toEqual(messages);
      }
    };
    expectMatching(configuration, false);
    for (const entry of cases) writeFileSync(join(root, entry.file), entry.current);
    for (const entry of cases) {
      const filename = join(root, entry.file);
      expect(linter.verify(entry.current, configuration, {filename}), entry.file).toEqual([]);
      expect(linter.verify(entry.current, configuration, {filename}), `repeated ${entry.file}`).toEqual([]);
      expect(linter.verifyAndFix(entry.current, configuration, {filename}), entry.file).toEqual({fixed: false, messages: [], output: entry.current});
    }
    const current = ts.createProgram(roots, options);
    expect(ts.getPreEmitDiagnostics(current)).toEqual([]);
    expectMatching(suppliedConsumerConfiguration(current), true);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});
