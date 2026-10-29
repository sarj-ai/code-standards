import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { Linter, type Rule } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import { ordinaryObjectEffects } from "../src/rules/_ordinary-object-effects.js";
import noExcessJSXProps from "../src/rules/no-excess-jsx-props.js";

it("stops identity requests after proven unsafety while retaining later module edges", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-unsafe-work-"));
  try {
    const target = join(root, "target.ts");
    const isolated = join(root, "isolated.ts");
    const owner = join(root, "owner.ts");
    writeFileSync(target, "export const value = 'Ada';\n");
    writeFileSync(isolated, "export const value = 'Ada';\n");
    const counts = [0, 256].map((tail) => {
      writeFileSync(owner, `export const escapedObject = Object;\n${Array.from({length: tail}, (_, index) => `export const tail${index} = ${index};`).join("\n")}\nimport './target.js';\n`);
      const program = ts.createProgram([owner, target, isolated], {
        strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.Bundler, types: [],
      });
      const source = program.getSourceFile(owner);
      const dependency = program.getSourceFile(target);
      const independent = program.getSourceFile(isolated);
      if (!source || !dependency || !independent) throw new Error("Native work fixture was not loaded");
      const checker = program.getTypeChecker();
      const getSymbol = checker.getSymbolAtLocation.bind(checker);
      let queries = 0;
      checker.getSymbolAtLocation = (node) => {
        if (node.getSourceFile() === source) queries++;
        return getSymbol(node);
      };
      expect(ordinaryObjectEffects(program, dependency)).toBe(true);
      const initialQueries = queries;
      expect(ordinaryObjectEffects(program, source)).toBe(true);
      expect(ordinaryObjectEffects(program, independent)).toBe(false);
      expect(queries).toBe(initialQueries);
      expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
      return initialQueries;
    });
    expect(counts[0]).toBeGreaterThan(0);
    expect(counts[1]).toBe(counts[0]);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it("keeps source-graph and alias-depth limits independent of cache order", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-effects-"));
  try {
    const files = new Map<string, string>();
    for (let index = 0; index < 129; index++) files.set(`chain${index}.ts`, `${index < 128 ? `import './chain${index + 1}.js';\n` : ""}export {};\n`);
    for (const entry of ["cold", "warm"]) files.set(`${entry}.ts`, "import './chain0.js';\nexport {};\n");
    files.set("independent.ts", "export const value = 'Ada';\n");
    files.set("independent-parent.ts", "export {value} from './independent.js';\n");
    files.set("aliases.ts", `const seed = {}; export const value0 = seed;\n${Array.from({length: 80}, (_, index) => `export const value${index + 1} = value${index};`).join("\n")}`);
    for (const entry of ["alias-cold", "alias-warm"]) files.set(`${entry}.ts`, "import {value80} from './aliases.js'; const value = value80;\n");
    for (const [file, source] of files) writeFileSync(join(root, file), source);
    const program = ts.createProgram([...files.keys()].map((file) => join(root, file)), {
      strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [],
    });
    expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
    const cold = program.getSourceFile(join(root, "cold.ts"));
    const warm = program.getSourceFile(join(root, "warm.ts"));
    const child = program.getSourceFile(join(root, "chain1.ts"));
    if (!cold || !warm || !child) throw new Error("Native graph fixture was not loaded");
    expect(ordinaryObjectEffects(program, cold)).toBe(true);

    expect(ordinaryObjectEffects(program, child)).toBe(true);
    expect(ordinaryObjectEffects(program, warm)).toBe(true);
    const independent = program.getSourceFile(join(root, "independent.ts"));
    if (!independent) throw new Error("Independent graph fixture was not loaded");
    expect(ordinaryObjectEffects(program, independent)).toBe(false);
    const aliasCold = program.getSourceFile(join(root, "alias-cold.ts"));
    const aliasWarm = program.getSourceFile(join(root, "alias-warm.ts"));
    const aliases = program.getSourceFile(join(root, "aliases.ts"));
    if (!aliasCold || !aliasWarm || !aliases) throw new Error("Native alias fixture was not loaded");
    expect(ordinaryObjectEffects(program, aliasCold)).toBe(true);

    expect(ordinaryObjectEffects(program, aliases)).toBe(true);
    expect(ordinaryObjectEffects(program, aliasWarm)).toBe(true);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it("includes known incoming runtime contexts without connecting erased type imports", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-context-"));
  try {
    const files = new Map([
      ["entry.ts", "export const value = 'Ada';\n"],
      ["barrel.ts", "export {value} from './entry.js';\n"],
      ["parent.ts", "Object.defineProperty(Object.prototype, 'ref', {value: null});\nimport {value} from './barrel.js';\nexport const shown = value;\n"],
      ["dynamic-entry.ts", "export const value = 'Ada';\n"],
      ["dynamic-parent.ts", "Object.defineProperty(Object.prototype, 'ref', {value: null});\nvoid import('./dynamic-entry.js');\nexport {};\n"],
      ["type-entry.ts", "export interface Contract {readonly name: string}\nexport const value = 'Ada';\n"],
      ["type-parent.ts", "Object.defineProperty(Object.prototype, 'ref', {value: null});\nimport type {Contract} from './type-entry.js';\nexport type Alias = Contract;\n"],
      ["isolated.ts", "export const value = 'Ada';\n"],
      ["ambient-values.d.ts", "declare const contractRuntime: {readonly ready: boolean};\n"],
      ["ambient-read.ts", "export {}; const installed = contractRuntime.ready;\n"],
      ["global-read.ts", "export {}; const installed = (globalThis as unknown as {contractRuntime: {readonly ready: boolean}}).contractRuntime.ready;\n"],
      ["global-shorthand.ts", "export {}; const context = {globalThis}; const installed = (context.globalThis as unknown as {contractRuntime: {readonly ready: boolean}}).contractRuntime.ready;\n"],
      ["ambient-coercion.ts", "export {}; const installed = `${contractRuntime}`;\n"],
      ["local-shadow.ts", "export {}; const contractRuntime = {ready: true}; const installed = contractRuntime.ready;\n"],
    ]);
    for (const [file, source] of files) writeFileSync(join(root, file), source);
    const program = ts.createProgram([...files.keys()].map((file) => join(root, file)), {
      strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [],
    });
    expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
    for (const [file, unsafe] of [["entry.ts", true], ["barrel.ts", true], ["dynamic-entry.ts", true], ["type-entry.ts", false], ["isolated.ts", false], ["parent.ts", true],
      ["ambient-read.ts", true], ["global-read.ts", true], ["global-shorthand.ts", true], ["ambient-coercion.ts", true], ["local-shadow.ts", false]] as const) {
      const source = program.getSourceFile(join(root, file));
      if (!source) throw new Error(`Native context fixture was not loaded: ${file}`);
      expect(ordinaryObjectEffects(program, source), file).toBe(unsafe);
    }
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it.each([false, true])("follows per-specifier type imports only when native emit retains them: verbatim=%s", (verbatimModuleSyntax) => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-type-import-"));
  try {
    const files = new Map([
      ["imported.ts", "export interface Contract {readonly name: string}\nexport const value = 'Ada';\n"],
      ["reexported.ts", "export interface Contract {readonly name: string}\nexport const value = 'Ada';\n"],
      ["parent.ts", "Object.defineProperty(Object.prototype, 'ref', {value: null});\nimport {type Contract} from './imported.js';\nexport {type Contract} from './reexported.js';\nexport type Alias = Contract;\n"],
    ]);
    for (const [file, source] of files) writeFileSync(join(root, file), source);
    const program = ts.createProgram([...files.keys()].map((file) => join(root, file)), {
      strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], verbatimModuleSyntax,
    });
    expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
    const emitted = new Map<string, string>();
    program.emit(undefined, (file, source) => {emitted.set(file, source);});
    const parent = emitted.get(join(root, "parent.js"));
    expect(parent?.includes("./imported.js")).toBe(verbatimModuleSyntax);
    expect(parent?.includes("./reexported.js")).toBe(verbatimModuleSyntax);
    for (const file of ["imported.ts", "reexported.ts"]) {
      const source = program.getSourceFile(join(root, file));
      if (!source) throw new Error(`Native type-import fixture was not loaded: ${file}`);
      expect(ordinaryObjectEffects(program, source), file).toBe(verbatimModuleSyntax);
    }
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it("distinguishes unavailable runtime bindings from keys, labels and erased types", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-value-roles-"));
  try {
    const cases = [
      ["missing.ts", "export {}; runtimeCapability;", true, 2304],
      ["shorthand.ts", "export {}; const state = {runtimeCapability};", true, 18004],
      ["type-as-value.ts", "export {}; type RuntimeCapability = string; RuntimeCapability;", true, 2693],
      ["namespace-as-value.ts", "export {}; namespace RuntimeCapability {export interface Contract {readonly name: string}} RuntimeCapability;", true, 2708],
      ["const-enum-as-value.ts", "export {}; const enum RuntimeCapability {Ready = 1} RuntimeCapability;", true, 2475],
      ["labels.ts", "export {}; runtimeCapability: {break runtimeCapability;}", false, null],
      ["keys.ts", "export {}; const state = {runtimeCapability: true}; const {runtimeCapability: ready} = state;", false, null],
      ["types.ts", "export {}; type RuntimeCapability = string; const value: RuntimeCapability = 'Ada'; export {RuntimeCapability};", false, null],
      ["type-parameter.ts", "export {}; function value<RuntimeCapability>() {return 'Ada';}", false, null],
      ["type-namespace.ts", "export {}; namespace Types {export interface Contract {readonly name: string}}", false, null],
      ["implements.ts", "export {}; interface Contract {readonly name: string} class Value implements Contract {readonly name = 'Ada';}", false, null],
      ["local.ts", "export {}; const runtimeCapability = true; const ready = runtimeCapability;", false, null],
      ["value-source.ts", "export const value = true;", false, null],
      ["type-export.ts", "export type {value} from './value-source.js';", true, null],
      ["type-star.ts", "export type * from './value-source.js';", true, null],
      ["erased-import.ts", "import type {value as runtimeCapability} from './value-source.js'; runtimeCapability;", true, 1361],
      ["erased-export.ts", "import {value as runtimeCapability} from './type-export.js'; runtimeCapability;", true, 1362],
      ["erased-star.ts", "import {value as runtimeCapability} from './type-star.js'; runtimeCapability;", true, 1362],
      ["suppressed-star.ts", "import {value as runtimeCapability} from './type-star.js';\n// @ts-ignore\nruntimeCapability;", true, null],
      ["runtime-import.ts", "import {value as runtimeCapability} from './value-source.js'; runtimeCapability;", false, null],
      ["const-enum-namespace.ts", "export {}; namespace RuntimeCapability {export const enum Ready {Yes = 1}} RuntimeCapability;", true, null],
      ["value-namespace.ts", "export {}; namespace RuntimeCapability {export const ready = true} RuntimeCapability;", true, null],
      ["namespace-declaration.ts", "export {}; namespace RuntimeCapability {export const ready = true} const value = 'Ada';", false, null],
      ["ambient-namespace.ts", "export {}; declare global {const ambientCapability = true;} ambientCapability;", true, null],
      ["global-owner.ts", "export interface Marker {} declare global {const foreignCapability = true;}", true, null],
      ["foreign-global.ts", "import type {Marker} from './global-owner.js'; foreignCapability;", true, null],
      ["foreign-global-shadow.ts", "export {}; const foreignCapability = true; const ready = foreignCapability;", false, null],
    ] as const;
    for (const [file, source] of cases) writeFileSync(join(root, file), source);
    const program = ts.createProgram(cases.map(([file]) => join(root, file)), {
      strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [],
    });
    expect(program.getOptionsDiagnostics()).toEqual([]);
    expect(program.getGlobalDiagnostics()).toEqual([]);
    expect(program.getSyntacticDiagnostics()).toEqual([]);
    for (const [file, , unsafe, error] of cases) {
      const source = program.getSourceFile(join(root, file));
      if (!source) throw new Error(`Native value-role fixture was not loaded: ${file}`);

      expect(program.getSemanticDiagnostics(source).map((diagnostic) => diagnostic.code), file).toEqual(error === null ? [] : [error]);
      expect(ordinaryObjectEffects(program, source), file).toBe(unsafe);
      expect(ordinaryObjectEffects(program, source), `repeated ${file}`).toBe(unsafe);
    }
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

const JSX_BOUNDARY_CONSUMER = "export function observe() {const Box = ({name}: {name: string}) => <span>{name}</span>; const element = <Box {...{name: 'Ada', email: 'needed'}}/>; const selectedName = (element as {props: {name: string}}).props.name; return selectedName;}\n";
const JSX_BOUNDARY_NAMESPACE = "export namespace JSX {export interface Element {} export interface IntrinsicElements {span: {children?: unknown}}}\n";


const JSX_BOUNDARY_IMPLEMENTATION = JSX_BOUNDARY_NAMESPACE + "export function jsx(_type: unknown, props: {readonly name?: string; readonly email?: string}): JSX.Element {return {props: {name: props.email ?? props.name}};} export {jsx as jsxs, jsx as jsxDEV};\n";

interface RuntimeBindings {
  readonly runtime: string;
  readonly sources: ReadonlyMap<string, ts.SourceFile>;
  readonly bindings: ReadonlyMap<string, ts.StringLiteral>;
}

interface RuntimeObservation {
  readonly program: ts.Program;
  readonly queries: ReadonlyMap<ts.Node, number>;
}

function createRuntimeFixture(root: string): ReadonlyMap<string, string> {
  const consumers = new Map([
    ["standard/consumer.tsx", JSX_BOUNDARY_CONSUMER],
    ["standard/bridge.tsx", "import '../dependency.js';\n" + JSX_BOUNDARY_CONSUMER],
    ["standard/missing.tsx", JSX_BOUNDARY_CONSUMER],
    ["standard/ambiguous.tsx", JSX_BOUNDARY_CONSUMER],
    ["standard/foreign.tsx", JSX_BOUNDARY_CONSUMER],
    ["standard/unavailable-symbol.tsx", JSX_BOUNDARY_CONSUMER],
    ["pure/consumer.tsx", JSX_BOUNDARY_CONSUMER],
    ["switch.tsx", JSX_BOUNDARY_CONSUMER],
    ["dependency.ts", "export const value = 'Ada';\n"],
    ["isolated.ts", "export const value = 'Ada';\n"],
  ]);
  const files = new Map(consumers);
  for (const [directory, version, normal, development] of [
    ["standard/node_modules/react", "0.0.0-standard-fixture", "jsx-runtime.d.ts", "jsx-dev-runtime.d.ts"],
    ["node_modules/react", "0.0.0-switch-fixture", "jsx-runtime.d.ts", "jsx-dev-runtime.ts"],
    ["pure", "0.0.0-implementation-fixture", "runtime.ts", "runtime.ts"],
  ] as const) {
    files.set(`${directory}/package.json`, JSON.stringify({name: "react", version, exports: {
      "./jsx-runtime": {types: `./${normal}`}, "./jsx-dev-runtime": {types: `./${development}`},
    }}));
    files.set(`${directory}/${normal}`, normal.endsWith(".d.ts") ? JSX_BOUNDARY_NAMESPACE : JSX_BOUNDARY_IMPLEMENTATION);
    files.set(`${directory}/${development}`, development.endsWith(".d.ts") ? JSX_BOUNDARY_NAMESPACE : JSX_BOUNDARY_IMPLEMENTATION);
  }
  for (const [file, source] of files) {
    const path = join(root, file);
    mkdirSync(dirname(path), {recursive: true});
    writeFileSync(path, source);
  }
  return consumers;
}

function readRuntimeBindings(program: ts.Program, root: string, consumers: ReadonlyMap<string, string>, jsx: ts.JsxEmit): RuntimeBindings {
  const runtime = jsx === ts.JsxEmit.ReactJSX ? "react/jsx-runtime" : "react/jsx-dev-runtime";
  const sources = new Map([...consumers.keys()].map((file) => {
    const source = program.getSourceFile(join(root, file));
    if (!source) throw new Error(`Native automatic-runtime fixture was not loaded: ${file}`);
    return [file, source] as const;
  }));
  const bindings = new Map([...sources].map(([file, source]) => [file, implicitRuntimeNode(source, runtime)] as const));
  for (const [file, node] of bindings) {
    const declarations = program.getTypeChecker().getSymbolAtLocation(node)?.declarations;
    expect(declarations?.length, `native binding: ${file}`).toBeGreaterThan(0);
    if (!declarations) throw new Error(`Missing native automatic-runtime declarations: ${file}`);
    const implemented = file === "pure/consumer.tsx" || (jsx === ts.JsxEmit.ReactJSXDev && ["switch.tsx", "dependency.ts", "isolated.ts"].includes(file));
    for (const declaration of declarations) {
      const owner = declaration.getSourceFile();
      expect(program.getSourceFile(owner.fileName)).toBe(owner);
      expect(owner.isDeclarationFile, `declaration policy: ${file}`).toBe(!implemented);
      expect(program.isSourceFileFromExternalLibrary(owner), `native library ownership: ${file}`).toBe(file !== "pure/consumer.tsx");
    }
  }
  return {runtime, sources, bindings};
}

function observeRuntimeQueries(program: ts.Program, binding: RuntimeBindings): RuntimeObservation {
  const {sources, bindings} = binding;



  const missing = sources.get("standard/missing.tsx");
  const ambiguous = sources.get("standard/ambiguous.tsx");
  const foreign = sources.get("standard/foreign.tsx");
  const pureNode = bindings.get("pure/consumer.tsx");
  const ambiguousNode = bindings.get("standard/ambiguous.tsx");
  const unavailable = bindings.get("standard/unavailable-symbol.tsx");
  if (!missing || !ambiguous || !foreign || !pureNode || !ambiguousNode || !unavailable) throw new Error("Missing metadata fault controls");
  delete (missing as NativeJSXSource).imports;
  (ambiguous as NativeJSXSource).imports = [...((ambiguous as NativeJSXSource).imports ?? []), ambiguousNode];
  (foreign as NativeJSXSource).imports = [pureNode];
  const implicitNodes = new Set<ts.Node>(bindings.values());
  const queries = new Map<ts.Node, number>();
  const checker = program.getTypeChecker();
  const observedChecker = new Proxy(checker, {
    get(target, property): unknown {
      if (property === "getSymbolAtLocation") return (node: ts.Node) => {
        if (implicitNodes.has(node)) queries.set(node, (queries.get(node) ?? 0) + 1);
        return node === unavailable ? undefined : target.getSymbolAtLocation(node);
      };
      const member: unknown = Reflect.get(target, property);
      return typeof member === "function" ? member.bind(target) : member;
    },
  });
  const observedProgram = new Proxy(program, {
    get(target, property): unknown {
      if (property === "getTypeChecker") return () => observedChecker;
      const member: unknown = Reflect.get(target, property);
      return typeof member === "function" ? member.bind(target) : member;
    },
  });
  return {program: observedProgram, queries};
}

function expectRuntimeEffects(observed: RuntimeObservation, binding: RuntimeBindings, jsx: ts.JsxEmit): void {
  const {program: observedProgram, queries} = observed;
  const {runtime, sources, bindings} = binding;
  const isolated = sources.get("isolated.ts");
  if (!isolated) throw new Error("Missing isolated non-JSX source");
  expect(ordinaryObjectEffects(observedProgram, isolated)).toBe(false);

  expect(queries.size).toBe(0);
  const expectations = [
    ["standard/bridge.tsx", false], ["dependency.ts", false], ["standard/consumer.tsx", false],
    ["pure/consumer.tsx", true], ["switch.tsx", jsx === ts.JsxEmit.ReactJSXDev],
    ["standard/missing.tsx", true], ["standard/ambiguous.tsx", true],
    ["standard/foreign.tsx", true], ["standard/unavailable-symbol.tsx", true],
  ] as const;
  for (const [file, unsafe] of expectations) {
    const source = sources.get(file);
    if (!source) throw new Error(`Missing graph root: ${file}`);
    expect(ordinaryObjectEffects(observedProgram, source), `${runtime}: ${file}`).toBe(unsafe);
  }
  const firstQueries = new Map(queries);
  for (const [file, unsafe] of [...expectations].reverse()) {
    const source = sources.get(file);
    if (!source) throw new Error(`Missing repeated graph root: ${file}`);
    expect(ordinaryObjectEffects(observedProgram, source), `repeated ${runtime}: ${file}`).toBe(unsafe);
  }
  expect(queries).toEqual(firstQueries);
  const dependencyNode = bindings.get("dependency.ts");
  const isolatedNode = bindings.get("isolated.ts");
  if (!dependencyNode || !isolatedNode) throw new Error("Missing non-JSX compiler metadata controls");
  expect(queries.has(dependencyNode)).toBe(false);
  expect(queries.has(isolatedNode)).toBe(false);
  expect([...queries.values()]).toEqual([1, 1, 1, 1, 1]);
}

function expectRuntimeForwarding(program: ts.Program, root: string, consumers: ReadonlyMap<string, string>, jsx: ts.JsxEmit): void {


  for (const [file, count] of [["standard/consumer.tsx", 1], ["standard/bridge.tsx", 1], ["pure/consumer.tsx", 0], ["switch.tsx", jsx === ts.JsxEmit.ReactJSXDev ? 0 : 1]] as const) {
    const code = consumers.get(file);
    if (code === undefined) throw new Error(`Missing forwarding source: ${file}`);
    expectForwardingBoundary(program, root, file, code, count);
  }
}

it("requires the reached native automatic runtime, with Program-owned caches", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-jsx-runtime-"));
  try {
    const consumers = createRuntimeFixture(root);
    const qualified: {program: ts.Program; source: ts.SourceFile}[] = [];
    for (const jsx of [ts.JsxEmit.ReactJSX, ts.JsxEmit.ReactJSXDev]) {


      const program = ts.createProgram([...consumers.keys()].map((file) => join(root, file)), {
        strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], jsx,
      });
      expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
      const binding = readRuntimeBindings(program, root, consumers, jsx);
      const observed = observeRuntimeQueries(program, binding);
      expectRuntimeEffects(observed, binding, jsx);
      expectRuntimeForwarding(program, root, consumers, jsx);
      const switched = binding.sources.get("switch.tsx");
      if (!switched) throw new Error("Missing shared-path compiler-policy root");
      qualified.push({program: observed.program, source: switched});
    }
    expect(qualified).toHaveLength(2);
    expect(qualified[0]?.source.fileName).toBe(qualified[1]?.source.fileName);
    expect(qualified[0]?.source).not.toBe(qualified[1]?.source);
    for (const [index, entry] of qualified.entries()) expect(ordinaryObjectEffects(entry.program, entry.source)).toBe(index === 1);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

it("retains the owned ambient declaration assumption through the native runtime binding", () => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-ambient-jsx-"));
  try {


    const files = new Map([
      ["jsx-runtime.d.ts", readFileSync(join(import.meta.dirname, "fixtures", "minimal-consumer", "jsx-runtime.d.ts"), "utf8")],
      ["scalar.tsx", JSX_BOUNDARY_CONSUMER],
      ["unused.tsx", "export {}; const Box = ({name}: {name: string}) => <span>{name}</span>; const element = <Box {...{name: 'Ada', email: 'unused'}}/>;\n"],
    ]);
    for (const [file, source] of files) writeFileSync(join(root, file), source);
    const program = ts.createProgram([...files.keys()].map(file => join(root, file)), {
      strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], jsx: ts.JsxEmit.ReactJSX,
    });
    expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
    for (const file of ["scalar.tsx", "unused.tsx"]) {
      const source = program.getSourceFile(join(root, file));
      if (!source) throw new Error(`Owned ambient source was not loaded: ${file}`);
      const node = implicitRuntimeNode(source, "react/jsx-runtime");
      const declarations = program.getTypeChecker().getSymbolAtLocation(node)?.declarations;
      expect(declarations?.length).toBeGreaterThan(0);
      if (!declarations) throw new Error("Owned ambient native runtime binding unavailable");
      for (const declaration of declarations) {
        expect(ts.isModuleDeclaration(declaration)).toBe(true);
        const owner = declaration.getSourceFile();
        expect(owner).toBe(program.getSourceFile(join(root, "jsx-runtime.d.ts")));
        expect(owner.isDeclarationFile).toBe(true);
        expect(program.isSourceFileFromExternalLibrary(owner)).toBe(false);
      }
      expect(ordinaryObjectEffects(program, source)).toBe(false);
      expect(ordinaryObjectEffects(program, source)).toBe(false);
      const code = files.get(file);
      if (code === undefined) throw new Error(`Missing owned ambient forwarding source: ${file}`);
      expectForwardingBoundary(program, root, file, code, 1);
    }
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

type NativeJSXSource = ts.SourceFile & {imports?: readonly ts.Node[]};

function implicitRuntimeNode(source: ts.SourceFile, name: string): ts.StringLiteral {
  const imports = (source as NativeJSXSource).imports;
  if (!Array.isArray(imports)) throw new Error("Pinned native implicit-import metadata is unavailable");
  const selected = (imports as readonly ts.Node[]).filter((node): node is ts.StringLiteral => ts.isStringLiteral(node) && node.text === name);
  expect(selected).toHaveLength(1);
  const node = selected[0];
  if (!node || !ts.isImportDeclaration(node.parent)) throw new Error("Pinned native implicit-import parent is unavailable");
  expect(node.parent.moduleSpecifier).toBe(node);
  expect(node.parent.parent).toBe(source);
  expect(node.getSourceFile()).toBe(source);
  expect(source.statements.includes(node.parent)).toBe(false);
  return node;
}

function expectForwardingBoundary(program: ts.Program, root: string, file: string, source: string, count: number): void {
  const linter = new Linter({cwd: root});
  const filename = join(root, file);
  const configuration: Linter.Config = {
    files: ["**/*.tsx"],
    languageOptions: {parser: tsParser, parserOptions: {programs: [program], projectService: false, ecmaFeatures: {jsx: true}}},
    plugins: {local: {rules: {forwarding: noExcessJSXProps as unknown as Rule.RuleModule}}},
    rules: {"local/forwarding": "warn"},
  };
  const messages = linter.verify(source, configuration, {filename});
  expect(messages.filter(message => message.fatal || message.ruleId !== "local/forwarding"), file).toEqual([]);
  expect(messages, file).toHaveLength(count);
  for (const message of messages) {
    expect(message.messageId).toBe("excess");
    expect(message.message).toContain("email");
    expect(message.severity).toBe(1);
    expect(message.fix).toBeUndefined();
    expect(message.suggestions).toBeUndefined();
  }
  expect(linter.verify(source, configuration, {filename})).toEqual(messages);
  const fixed = linter.verifyAndFix(source, configuration, {filename});
  expect(fixed.fixed).toBe(false);
  expect(fixed.output).toBe(source);
  expect(fixed.messages).toEqual(messages);
}

it.each([
  { mode: "invalid", suppression: "", noCheck: false, aliasDiagnostics: [1361] },
  { mode: "suppressed", suppression: "// @ts-ignore\n", noCheck: false, aliasDiagnostics: [] },
  { mode: "noCheck", suppression: "", noCheck: true, aliasDiagnostics: [] },
])("checks erased alias effects before native diagnostics in both source orders: $mode", ({ suppression, noCheck, aliasDiagnostics }) => {
  const root = mkdtempSync(join(tmpdir(), "ordinary-object-erased-alias-"));
  try {
    const files = new Map([
      ["globals.d.ts", "declare const runtimeCapability: boolean;\n"],
      ["seed.ts", "export const seed = {};\n"],
      ["owner.ts", `import type {Marker} from './unsafe.js'; import type {seed} from './seed.js';\n${suppression}export const forwarded = seed;\nexport type Echo = Marker;\n`],
      ["unsafe.ts", `import type {forwarded} from './owner.js'; export interface Marker {}\nruntimeCapability;\n${suppression}const copy = forwarded;\n`],
      ["isolated.ts", "export const value = 'Ada';\n"],
    ]);
    for (const [file, source] of files) writeFileSync(join(root, file), source);
    const expected = new Map([
      ["seed.ts", { unsafe: false, diagnostics: [] }],
      ["owner.ts", { unsafe: true, diagnostics: aliasDiagnostics }],
      ["unsafe.ts", { unsafe: true, diagnostics: aliasDiagnostics }],
      ["isolated.ts", { unsafe: false, diagnostics: [] }],
    ]);
    const sourceOrders: boolean[] = [];
    for (const reverse of [false, true]) {
      const roots = [...files.keys()].map((file) => join(root, file));
      const program = ts.createProgram(reverse ? roots.reverse() : roots, {
        strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.Bundler, types: [], noCheck,
      });
      const nativeOrder = program.getSourceFiles().map((source) => source.fileName);
      sourceOrders.push(nativeOrder.indexOf(join(root, "owner.ts")) < nativeOrder.indexOf(join(root, "unsafe.ts")));
      const queries = reverse ? ["owner.ts", "unsafe.ts", "isolated.ts", "seed.ts"] : ["unsafe.ts", "owner.ts", "seed.ts", "isolated.ts"];
      for (const file of [...queries, ...queries.reverse()]) {
        const source = program.getSourceFile(join(root, file));
        if (!source) throw new Error(`Missing erased-alias root: ${file}`);
        expect(ordinaryObjectEffects(program, source), `${reverse}: ${file}`).toBe(expected.get(file)?.unsafe);
      }
      expect(program.getOptionsDiagnostics()).toEqual([]);
      expect(program.getGlobalDiagnostics()).toEqual([]);
      expect(program.getSyntacticDiagnostics()).toEqual([]);
      for (const [file, { diagnostics }] of expected) {
        const source = program.getSourceFile(join(root, file));
        if (!source) throw new Error(`Missing erased-alias audit root: ${file}`);
        expect(program.getSemanticDiagnostics(source).map((diagnostic) => diagnostic.code), file).toEqual(diagnostics);
      }
    }
    expect(sourceOrders).toContain(true);
    expect(sourceOrders).toContain(false);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});
