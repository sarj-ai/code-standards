// vitest: shared-module-graph
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import explicitRule, {
  REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION,
} from "../src/rules/require-explicit-service-contract.js";
import exportedRule, {
  REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION,
} from "../src/rules/require-interface-for-exported-class.js";
import portRule, {
  REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION,
} from "../src/rules/require-port-for-service.js";

const SCENARIOS = [
  {
    name: "require-explicit-service-contract",
    rule: explicitRule,
    example: REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION.examples[2],
  },
  {
    name: "require-interface-for-exported-class",
    rule: exportedRule,
    example: REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[2],
  },
  {
    name: "require-port-for-service",
    rule: portRule,
    example: REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION.examples[2],
  },
] as const;
type Scenario = (typeof SCENARIOS)[number];

function configuration(scenario: Scenario): Linter.Config[] {
  return [
    {
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { local: { rules: { check: scenario.rule } } },
      rules: { "local/check": "error" },
    },
  ];
}

function apply(
  scenario: Scenario,
  source: string,
): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(source, configuration(scenario), {
    filename: "src/service.ts",
  });
}

it.each(SCENARIOS)(
  "uses the actual %s finding, existing factory annotation and exact output",
  (scenario) => {
    for (const ending of ["\n", "\r\n"]) {
      const source = scenario.example.files[0].source.replaceAll("\n", ending);
      const before = new Linter().verify(source, configuration(scenario), {
        filename: "src/service.ts",
      });
      expect(before).toHaveLength(1);
      expect(before[0]?.ruleId).toBe("local/check");
      const result = apply(scenario, source);
      expect(result.fixed).toBe(true);
      expect(result.output).toBe(
        scenario.example.fixedFiles[0].source.replaceAll("\n", ending),
      );
      expect(result.messages).toEqual([]);
      expect(apply(scenario, result.output).fixed).toBe(false);
      expect(javascript(result.output)).toBe(javascript(source));
    }
  },
);

const RENAMINGS = [
  ["Port", "Capability"],
  ["Worker", "Collaborator"],
  ["Service", "CoordinatorService"],
  ["run", "execute"],
  ["worker", "collaborator"],
  ["Port", "能力"],
  [
    "create(worker: Worker): Port { return new Service(worker); }",
    "create(dependency: Worker): Port { return new Service(dependency); }",
  ],
] as const;

it.each(SCENARIOS)(
  "retains all existing operation, interface and binding names for %s",
  (scenario) => {
    for (const [original, renamed] of RENAMINGS) {
      const source = scenario.example.files[0].source.replaceAll(
        original,
        renamed,
      );
      const expected = scenario.example.fixedFiles[0].source.replaceAll(
        original,
        renamed,
      );
      const result = apply(scenario, source);
      expect(result.fixed).toBe(true);
      expect(result.output).toBe(expected);
      expect(result.messages).toEqual([]);
      expect(javascript(result.output)).toBe(javascript(source));
    }
  },
);

const REFUSALS = [
  ["export type Port", "type Port"],
  [
    "export type Port = { run(): void; };",
    "export interface Port { run(): void; }",
  ],
  ["interface Worker", "export interface Worker"],
  ["interface Worker", "declare interface Worker"],
  ["interface Worker", "interface Worker<T>"],
  ["interface Worker {", "interface Worker extends Other {"],
  [
    "interface Worker { run(): void; }",
    "interface Worker { run(): void; extra(): void; }",
  ],
  [
    "interface Worker { run(): void; }",
    "interface Worker { run(value: string): void; }",
  ],
  ["interface Worker { run(): void; }", "interface Worker { run?(): void; }"],
  ["interface Worker { run(): void; }", "interface Worker { run(): number; }"],
  ["interface Worker", "interface Port"],
  ["class Service", "abstract class Service"],
  ["class Service", "declare class Service"],
  ["class Service", "class Service<T>"],
  ["class Service {", "class Service extends Base {"],
  ["private readonly worker", "private worker"],
  ["private readonly worker", "public readonly worker"],
  ["worker: Worker) {}", "worker: Worker = fallback) {}"],
  ["worker: Worker) {}", "worker?: Worker) {}"],
  ["worker: Worker) {}", "worker: Worker, other: Worker) {}"],
  [
    "constructor(private readonly worker: Worker) {}",
    "constructor(private readonly worker: Worker) { observe(); }",
  ],
  ["run(): void {", "private run(): void {"],
  ["run(): void {", "static run(): void {"],
  ["run(): void {", "async run(): void {"],
  ["run(): void {", "run<T>(): void {"],
  ["run(): void {", "run(value: string): void {"],
  ["this.worker.run();", "return this.worker.run();"],
  ["this.worker.run();", "this.worker.run(); observe();"],
  ["this.worker.run();", "this.worker.run('value');"],
  ["this.worker.run();", "this.worker.other();"],
  ["this.worker.run();", "this.other.run();"],
  ["this.worker.run();", "this.worker?.run();"],
  ["this.worker.run();", "this.worker.run?.();"],
  ["this.worker.run();", "this.worker['run']();"],
  ["this.worker.run();", "this.worker.run<string>();"],
  ["export function create", "function create"],
  ["export function create", "export declare function create"],
  ["export function create", "export async function create"],
  ["function create(", "function create<T>("],
  ["create(worker: Worker): Port", "create(worker: Worker = fallback): Port"],
  ["create(worker: Worker): Port", "create(worker?: Worker): Port"],
  ["create(worker: Worker): Port", "create(worker: Other): Port"],
  ["create(worker: Worker): Port", "create(worker: Worker)"],
  ["create(worker: Worker): Port", "create(worker: Worker): Worker"],
  ["create(worker: Worker): Port", "create(worker: Worker): Port<string>"],
  ["return new Service(worker);", "return new Service(worker) as Port;"],
  ["return new Service(worker);", "return new Other(worker);"],
  ["return new Service(worker);", "return new Service(other);"],
  ["return new Service(worker);", "return new Service(...[worker]);"],
  ["return new Service(worker);", "observe(); return new Service(worker);"],
] as const;

it.each(SCENARIOS)(
  "refuses unproven factory authority or contract shape for %s",
  (scenario) => {
    for (const [original, replacement] of REFUSALS) {
      const source = scenario.example.files[0].source.replaceAll(
        original,
        replacement,
      );
      const result = apply(scenario, source);
      expect(result.fixed).toBe(false);
      expect(result.output).toBe(source);
    }
    for (const prefix of ["import 'setup';\n", "// Maintained boundary.\n"]) {
      const source = prefix + scenario.example.files[0].source;
      expect(apply(scenario, source).fixed).toBe(false);
    }
    const competing =
      scenario.example.files[0].source +
      "\nexport function other(worker: Worker): Port { return new Service(worker); }";
    expect(apply(scenario, competing).fixed).toBe(false);
  },
);

it.each(SCENARIOS)(
  "preserves callback effects, receiver identity and fresh instances for %s",
  (scenario) => {
    const source = scenario.example.files[0].source;
    const result = apply(scenario, source);
    expect(result.fixed).toBe(true);
    expect(javascript(result.output)).toBe(javascript(source));
    expect(evaluate(result.output)).toBe(evaluate(source));
  },
);

function javascript(source: string): string {
  return ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
}

function evaluate(source: string): unknown {
  return runInNewContext(
    javascript(source) +
      "\n(() => { const events = []; const worker = { get run() { events.push('get'); return function() { events.push(this === worker ? 'receiver' : 'wrong'); }; } }; const first = exports.create(worker); const second = exports.create(worker); first.run(); second.run(); let error; try { exports.create({run() { throw new Error('failure'); }}).run(); } catch (observed) { error = observed.message; } return JSON.stringify([events, first !== second, error]); })();",
    { exports: {} },
  );
}

it.each(SCENARIOS)("respects native disabling for %s", (scenario) => {
  const source =
    "/* eslint-disable local/check */\n" + scenario.example.files[0].source;
  const result = apply(scenario, source);
  expect(result.fixed).toBe(false);
  expect(result.messages).toEqual([]);
});

it.each(SCENARIOS)(
  "typechecks public factory compatibility and declaration output for %s",
  (scenario) => {
    const before = resolve(`autofix-factory-before-${scenario.name}.ts`);
    const after = resolve(`autofix-factory-after-${scenario.name}.ts`);
    const caller = resolve(`autofix-factory-caller-${scenario.name}.ts`);
    const files = new Map([
      [before, scenario.example.files[0].source],
      [after, scenario.example.fixedFiles[0].source],
      [
        caller,
        `import { create as beforeCreate } from './autofix-factory-before-${scenario.name}';\nimport { create as afterCreate } from './autofix-factory-after-${scenario.name}';\nexport const acceptsBefore: typeof beforeCreate = afterCreate;\nexport const acceptsAfter: typeof afterCreate = beforeCreate;\nbeforeCreate({run(): void {}}).run();\nafterCreate({run(): void {}}).run();`,
      ],
    ]);
    const outputs = declarations(files);
    const beforeDeclaration = outputs.get(before.replace(/\.ts$/u, ".d.ts"));
    const afterDeclaration = outputs.get(after.replace(/\.ts$/u, ".d.ts"));
    expect(typeof beforeDeclaration).toBe("string");
    expect(afterDeclaration?.replace(" implements Port", "")).toBe(
      beforeDeclaration,
    );
    const downstream = new Map(
      [...outputs].filter(
        ([filename]) => filename !== caller.replace(/\.ts$/u, ".d.ts"),
      ),
    );
    const callerSource = files.get(caller);
    if (callerSource === undefined)
      throw new Error("missing authored consumer fixture");
    downstream.set(caller, callerSource);
    expect(compilerDiagnostics(downstream)).toEqual([]);
  },
);

it("typechecks the rejected public-interface declaration augmentation counterexample", () => {
  const library = resolve("autofix-open-library.ts");
  const declaration = library.replace(/\.ts$/u, ".d.ts");
  const caller = resolve("autofix-open-consumer.ts");
  const source = SCENARIOS[1].example.files[0].source.replace(
    "export type Port = { run(): void; };",
    "export interface Port { run(): void; }",
  );
  const hypothetical = source.replace(
    "class Service {",
    "class Service implements Port {",
  );
  expect(apply(SCENARIOS[1], source).fixed).toBe(false);
  const before = declarations(new Map([[library, source]]));
  const after = declarations(new Map([[library, hypothetical]]));
  const consumer =
    "import { create } from './autofix-open-library';\ndeclare module './autofix-open-library' { interface Port { readonly worker?: {run(): void}; } }\nconst port = create({run(): void {}});\nport.worker?.run();";
  const beforeDeclaration = before.get(declaration);
  const afterDeclaration = after.get(declaration);
  if (beforeDeclaration === undefined || afterDeclaration === undefined)
    throw new Error("missing emitted library fixture");
  expect(
    compilerDiagnostics(
      new Map([
        [declaration, beforeDeclaration],
        [caller, consumer],
      ]),
    ),
  ).toEqual([]);
  const diagnostics = compilerDiagnostics(
    new Map([
      [declaration, afterDeclaration],
      [caller, consumer],
    ]),
  );
  expect(diagnostics.map((diagnostic) => diagnostic.code)).toEqual([2420]);
  expect(
    diagnostics.some((diagnostic) =>
      ts
        .flattenDiagnosticMessageText(diagnostic.messageText, " ")
        .includes("private"),
    ),
  ).toBe(true);
});

function declarations(files: ReadonlyMap<string, string>): Map<string, string> {
  const outputs = new Map<string, string>();
  const program = compilerProgram(
    files,
    { declaration: true, emitDeclarationOnly: true },
    outputs,
  );
  expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
  const emitted = program.emit();
  expect(emitted.emitSkipped).toBe(false);
  expect(emitted.diagnostics).toEqual([]);
  return outputs;
}

function compilerDiagnostics(
  files: ReadonlyMap<string, string>,
): readonly ts.Diagnostic[] {
  return ts.getPreEmitDiagnostics(compilerProgram(files, { noEmit: true }));
}

function compilerProgram(
  files: ReadonlyMap<string, string>,
  extra: ts.CompilerOptions,
  outputs?: Map<string, string>,
): ts.Program {
  const options: ts.CompilerOptions = {
    strict: true,
    noUnusedLocals: true,
    noUnusedParameters: true,
    skipLibCheck: false,
    types: [],
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    ...extra,
  };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  const exists = host.fileExists.bind(host);
  host.fileExists = (filename) => files.has(filename) || exists(filename);
  host.getSourceFile = (filename, version, onError, fresh) => {
    const source = files.get(filename);
    return source === undefined
      ? original(filename, version, onError, fresh)
      : ts.createSourceFile(filename, source, version, true);
  };
  if (outputs !== undefined)
    host.writeFile = (filename, text) => {
      outputs.set(resolve(filename), text);
    };
  return ts.createProgram([...files.keys()], options, host);
}
