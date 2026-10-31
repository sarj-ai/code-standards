import { join } from "node:path";

import ts from "typescript";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const PACKAGE_ROOT = join(import.meta.dirname, "..");
const FIXTURE = join(PACKAGE_ROOT, "src", "example-options-contract.ts").replaceAll("\\", "/");

const ACCEPTED = `
import { createRule, type RuleDocumentation, type RuleExample } from "./rules/_docs.js";

type Options = readonly [{ readonly mode: "strict" | "loose"; readonly libraries: readonly string[] }];
type OptionalOptions = readonly [{ readonly enabled: boolean }?];
const example = { id: "matching", title: "Reports the construct", outcome: "match", files: [{ path: "src/input.ts", source: "debugger;" }], focusPath: "src/input.ts", expectedCount: 1 } as const;
const documentation = { summary: "Report the construct.", rationale: "The construct violates the contract.", remediation: "Use the supported construct.", category: "correctness", examples: [example] } as const;
const defaults: Options = [{ mode: "strict", libraries: ["example"] }];
const base = { name: "options-probe", meta: { type: "problem", docs: { description: documentation.summary }, schema: [], messages: { found: "Found." } }, defaultOptions: defaults, create: () => ({}) } as const;
const readonlyOptions = [{ mode: "loose", libraries: ["first", "second"] }] as const;

export const typedExample = { ...example, ruleOptions: readonlyOptions } as const satisfies RuleExample<Options>;
export const typedDocumentation = { ...documentation, examples: [typedExample] } as const satisfies RuleDocumentation<Options>;
export const normalizedExample: RuleExample = typedExample;
export const normalizedDocumentation: RuleDocumentation = typedDocumentation;
export const required = createRule<Options, "found">({ ...base, documentation: typedDocumentation });
export const defaulted = createRule<Options, "found">({ ...base, documentation });
export const inferred = createRule({ ...base, documentation: typedDocumentation });
export const noOptions = createRule<[], "found">({ ...base, defaultOptions: [], documentation: { ...documentation, examples: [{ ...example, ruleOptions: [] as const }] } });
export const optionalEmpty = createRule<OptionalOptions, "found">({ ...base, defaultOptions: [], documentation: { ...documentation, examples: [{ ...example, ruleOptions: [] }] } });
export const optionalPresent = createRule<OptionalOptions, "found">({ ...base, defaultOptions: [], documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ enabled: true }] }] } });
`;

const REJECTED = `${ACCEPTED}
export const wrongScalar: RuleExample<Options> = { ...example, ruleOptions: [{ mode: 1, libraries: [] }] }; // wrong-scalar
export const wrongField = { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "strict", librarie: [] }] }] } as const satisfies RuleDocumentation<Options>; // wrong-field
createRule<Options, "found">({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "unknown", libraries: [] }] }] } }); // wrong-explicit-option
createRule<Options, "found">({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "strict", libraries: [1] }] }] } }); // wrong-nested-option
createRule<Options, "found">({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "strict", libraries: [] }, { mode: "strict", libraries: [] }] }] } }); // extra-tuple-entry
createRule<Options, "found">({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [] }] } }); // missing-required-option
createRule<[], "found">({ ...base, defaultOptions: [], documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ enabled: true }] }] } }); // unexpected-option
createRule<OptionalOptions, "found">({ ...base, defaultOptions: [], documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ enabled: "yes" }] }] } }); // wrong-optional-value
createRule({ ...base, documentation: { ...documentation, examples: [{ ...example, ruleOptions: [{ mode: "unknown", libraries: [] }] }] } }); // inferred-options-stay-authoritative
`;

interface CompilerIssue {
  readonly code: number;
  readonly path: string | undefined;
  readonly line: number | undefined;
  readonly message: string;
}

interface CompilerFixture {
  readonly program: ts.Program;
  readonly configIssues: readonly ts.Diagnostic[];
}

function prepareCompilerFixture(source: string): CompilerFixture {
  const loaded = ts.readConfigFile(join(PACKAGE_ROOT, "tsconfig.json"), (path) => ts.sys.readFile(path));
  const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, PACKAGE_ROOT);
  const options = { ...parsed.options, noEmit: true, incremental: false };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path.replaceAll("\\", "/") === FIXTURE
    ? ts.createSourceFile(path, source, version, true)
    : original(path, version, onError, create);
  const program = ts.createProgram([FIXTURE], options, host);
  if (program.getSourceFile(FIXTURE)?.text !== source) throw new Error("The compiler did not load the intended contract source.");
  return { program, configIssues: [...(loaded.error === undefined ? [] : [loaded.error]), ...parsed.errors] };
}

function compilerIssues(fixture: CompilerFixture): readonly CompilerIssue[] {
  return [...fixture.configIssues, ...ts.getPreEmitDiagnostics(fixture.program)]
    .map((issue) => ({
      code: issue.code,
      path: issue.file?.fileName.replaceAll("\\", "/"),
      line: issue.file !== undefined && issue.start !== undefined ? issue.file.getLineAndCharacterOfPosition(issue.start).line + 1 : undefined,
      message: ts.flattenDiagnosticMessageText(issue.messageText, "\n"),
    }));
}

describe("authored example option tuples", () => {
  describe("accepted compiler fixture", () => {
    let fixture: CompilerFixture | undefined;
    beforeAll(() => {
      fixture = prepareCompilerFixture(ACCEPTED);
    });
    afterAll(() => {
      fixture = undefined;
    });
    it("accepts actual readonly, defaulted, empty and optional rule configurations", () => {
      if (fixture === undefined) throw new Error("The accepted compiler fixture did not complete.");
      expect(compilerIssues(fixture)).toEqual([]);
    });
  });

  describe("rejected compiler fixture", () => {
    let fixture: CompilerFixture | undefined;
    beforeAll(() => {
      fixture = prepareCompilerFixture(REJECTED);
    });
    afterAll(() => {
      fixture = undefined;
    });
    it("rejects invalid options through RuleExample, RuleDocumentation and actual createRule calls", () => {
      if (fixture === undefined) throw new Error("The rejected compiler fixture did not complete.");
      const issues = compilerIssues(fixture);
      const rejectedLines = REJECTED.split("\n")
        .flatMap((line, index) => line.includes("// ") ? [index + 1] : []);
      for (const line of rejectedLines) {
        expect(issues.some((issue) => issue.path === FIXTURE && issue.line === line), REJECTED.split("\n")[line - 1]).toBe(true);
      }
      expect(issues.filter((issue) => issue.path !== FIXTURE || issue.line === undefined || !rejectedLines.includes(issue.line))).toEqual([]);
    });
  });
});
