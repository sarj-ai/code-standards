/**
 * @fileoverview _docs — typed source-owned rule documentation and executable examples.
 *
 */

import { ESLintUtils } from "@typescript-eslint/utils";

export const REPO_BLOB = "https://github.com/sarj-ai/code-standards/blob/main";
export const TESTS_DIR = "packages/typescript/tests/rules";

export const examplesPath = (name: string): string =>
  `${TESTS_DIR}/${name}.test.ts`;

export const examplesUrl = (name: string): string =>
  `${REPO_BLOB}/${examplesPath(name)}`;

export type RuleCategory =
  | "architecture"
  | "correctness"
  | "maintainability"
  | "performance"
  | "security"
  | "style"
  | "testing";

export type AutofixPolicy = "none" | "safe" | "suggestion";
export type DefaultLevel = "error" | "warning";
export type ExampleOutcome = "match" | "no-match";

export interface ExampleFile {
  readonly path: string;
  readonly source: string;
}

export interface ExamplePoint {
  readonly line: number;
  readonly column: number;
}

export interface ExampleLocation extends ExamplePoint {
  readonly end?: ExamplePoint;
}

export interface SuggestionExpectation {
  readonly messageId: string;
  readonly output: string;
}

export interface DiagnosticExpectation {
  readonly messageId: string;
  readonly message: string;
  readonly location: ExampleLocation;
  readonly automaticFix: boolean;
  readonly suggestions: readonly SuggestionExpectation[];
}

/** A reviewed example. It remains private unless `public: true` is explicit. */
export interface RuleExample<Options extends readonly unknown[] = readonly unknown[]> {
  readonly ruleOptions?: Readonly<Options>;
  readonly installedDependencies?: readonly { readonly module: string; readonly version: string }[];
  readonly id: string;
  readonly scenarioId?: string;
  readonly title: string;
  readonly outcome: ExampleOutcome;
  readonly files: readonly ExampleFile[];
  readonly focusPath: string;
  readonly expectedCount: number;
  readonly expectedDiagnostics?: readonly DiagnosticExpectation[];
  readonly public?: boolean;
  readonly fixedFiles?: readonly ExampleFile[];
}

export type PublicRuleExample = Omit<RuleExample, "expectedDiagnostics">;

/** Human-authored fields that cannot be derived from the ESLint rule module. */
export interface RuleDocumentation<Options extends readonly unknown[] = readonly unknown[]> {
  readonly summary: string;
  readonly rationale: string;
  readonly remediation: string;
  readonly category: RuleCategory;
  readonly defaultLevel?: DefaultLevel;
  readonly languages?: readonly "typescript"[];
  readonly autofix?: AutofixPolicy;
  readonly aliases?: readonly string[];
  readonly limitations?: readonly string[];
  readonly filePatterns?: readonly string[];
  readonly references?: readonly string[];
  readonly since?: string;
  readonly examples?: readonly RuleExample<Options>[];
}

/** Complete native record exposed to catalog generation without changing ESLint metadata. */
export interface NativeRuleSpec extends Required<Omit<RuleDocumentation, "since">> {
  readonly engine: "eslint";
  readonly ruleId: string;
  readonly code: null;
  readonly messageIds: readonly string[];
  readonly optionsSchema: object | null;
  readonly since: string | null;
  readonly key: string;
  readonly publicExamples: readonly RuleExample[];
}

/** The explicit allowlist projection consumed by generated public documentation. */
export interface PublicRuleSpec {
  readonly engine: "eslint";
  readonly ruleId: string;
  readonly code: null;
  readonly summary: string;
  readonly rationale: string;
  readonly remediation: string;
  readonly category: RuleCategory;
  readonly defaultLevel: DefaultLevel;
  readonly languages: readonly "typescript"[];
  readonly autofix: AutofixPolicy;
  readonly aliases: readonly string[];
  readonly limitations: readonly string[];
  readonly filePatterns: readonly string[];
  readonly references: readonly string[];
  readonly since: string | null;
  readonly messageIds: readonly string[];
  readonly optionsSchema: object | null;
  readonly examples: readonly PublicRuleExample[];
}

const KEBAB_CASE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;
const MAX_SUMMARY_LENGTH = 160;
const eslintCreateRule = ESLintUtils.RuleCreator(examplesUrl);

type RuleConfiguration<
  Options extends readonly unknown[],
  MessageIds extends string,
> = Parameters<typeof eslintCreateRule<Options, MessageIds>>[0];

export type DocumentedRule<
  Options extends readonly unknown[],
  MessageIds extends string,
> = ReturnType<typeof eslintCreateRule<Options, MessageIds>> & {
  /** Non-enumerable so the public ESLint rule shape remains unchanged. */
  readonly documentation?: NativeRuleSpec;
};

type SourceRuleConfiguration<
  Options extends readonly unknown[],
  MessageIds extends string,
> = RuleConfiguration<Options, MessageIds> & {
  readonly documentation?: RuleDocumentation<NoInfer<Options>>;
};

/** Create an ESLint rule and attach validated documentation as a non-enumerable native spec. */
export function createRule<
  Options extends readonly unknown[],
  MessageIds extends string,
>(config: SourceRuleConfiguration<Options, MessageIds>): DocumentedRule<Options, MessageIds> {
  const { documentation, ...eslintConfig } = config;
  const rule = eslintCreateRule<Options, MessageIds>(eslintConfig);
  if (documentation !== undefined) {
    Object.defineProperty(rule, "documentation", {
      configurable: false,
      enumerable: false,
      value: nativeSpec(eslintConfig, documentation),
      writable: false,
    });
  }
  return rule;
}

/** Non-blocking completeness report used while source-owned docs roll out rule by rule. */
export function documentationWarnings(
  rules: Readonly<Record<string, { readonly documentation?: NativeRuleSpec }>>,
): readonly string[] {
  return Object.entries(rules)
    .filter(([, rule]) => rule.documentation === undefined)
    .map(([name]) => `${name}: source-owned documentation has not been migrated`)
    .sort();
}

/** Serialize only reviewed fields; test-only examples never cross this boundary. */
export function publicDocumentation(
  rules: Readonly<Record<string, { readonly documentation?: NativeRuleSpec }>>,
): readonly PublicRuleSpec[] {
  const missing = documentationWarnings(rules);
  if (missing.length > 0) {
    throw new TypeError(`cannot publish an incomplete rule catalog:\n${missing.join("\n")}`);
  }
  return Object.entries(rules)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([ruleId, rule]) => {
      const spec = rule.documentation;
      if (spec === undefined || spec.ruleId !== ruleId) {
        throw new TypeError(`${ruleId}: native documentation identity mismatch`);
      }
      return deepFreeze({
        engine: spec.engine,
        ruleId: spec.ruleId,
        code: spec.code,
        summary: spec.summary,
        rationale: spec.rationale,
        remediation: spec.remediation,
        category: spec.category,
        defaultLevel: spec.defaultLevel,
        languages: spec.languages,
        autofix: spec.autofix,
        aliases: spec.aliases,
        limitations: spec.limitations,
        filePatterns: spec.filePatterns,
        references: spec.references,
        since: spec.since,
        messageIds: spec.messageIds,
        optionsSchema: spec.optionsSchema,
        examples: spec.publicExamples.map(publicExample),
      });
    });
}

/** Copy an example through a closed field list so future private fields stay private. */
function publicExample(example: RuleExample): PublicRuleExample {
  const copy: { -readonly [Field in keyof PublicRuleExample]: PublicRuleExample[Field] } = {
    id: example.id,
    scenarioId: example.scenarioId ?? "primary",
    title: example.title,
    outcome: example.outcome,
    files: example.files.map(publicFile),
    focusPath: example.focusPath,
    expectedCount: example.expectedCount,
    fixedFiles: (example.fixedFiles ?? []).map(publicFile),
  };
  if (example.ruleOptions !== undefined) copy.ruleOptions = example.ruleOptions;
  if (example.installedDependencies !== undefined) copy.installedDependencies = example.installedDependencies.map(({ module, version }) => ({ module, version }));
  return copy;
}

function publicFile(file: ExampleFile): ExampleFile {
  return { path: file.path, source: file.source };
}

function nativeSpec<Options extends readonly unknown[], MessageIds extends string>(
  config: RuleConfiguration<Options, MessageIds>,
  documentation: RuleDocumentation<Options>,
): NativeRuleSpec {
  const { name, meta } = config;
  if (!KEBAB_CASE.test(name)) throw new TypeError("rule ID must be lowercase kebab-case");
  for (const [label, value] of [
    ["summary", documentation.summary],
    ["rationale", documentation.rationale],
    ["remediation", documentation.remediation],
  ] as const) {
    if (value.trim().length === 0) throw new TypeError(`rule ${label} must not be empty`);
  }
  if (documentation.summary.includes("\n") || documentation.summary.length > MAX_SUMMARY_LENGTH) {
    throw new TypeError(`rule summary must be one line of at most ${MAX_SUMMARY_LENGTH} characters`);
  }
  if (documentation.summary !== meta.docs?.description) {
    throw new TypeError(`${name}: ESLint description must equal the authored documentation summary`);
  }
  const aliases = [...(documentation.aliases ?? [])];
  assertUnique(aliases, "rule aliases");
  if (aliases.some((alias) => !KEBAB_CASE.test(alias) || alias === name)) {
    throw new TypeError("rule aliases must be historical lowercase kebab-case IDs");
  }
  const limitations = [...(documentation.limitations ?? [])];
  const filePatterns = [...(documentation.filePatterns ?? [])];
  if ([...limitations, ...filePatterns].some((value) => value.trim().length === 0)) {
    throw new TypeError("rule limitations and file patterns must not be empty");
  }
  const references = [...(documentation.references ?? [])];
  if (references.some((reference) => !reference.startsWith("https://"))) {
    throw new TypeError("rule references must use https");
  }
  const examples = [...(documentation.examples ?? [])];
  const messageIds = Object.keys(meta.messages).sort();
  const knownMessages = new Set(messageIds);
  examples.forEach((example) => validateExample(example, knownMessages));
  assertUnique(examples.map((example) => example.id), "rule example IDs");
  const publicExamples = examples.filter((example) => example.public === true);
  const scenarios = new Set(publicExamples.map((example) => example.scenarioId ?? "primary"));
  for (const scenario of scenarios) {
    const pair = publicExamples.filter((example) => (example.scenarioId ?? "primary") === scenario);
    const outcomes = new Set(pair.map((example) => example.outcome));
    if (pair.length !== 2 || !outcomes.has("match") || !outcomes.has("no-match")) {
      throw new TypeError(`published example scenario ${scenario} must contain both matching and non-matching cases exactly once`);
    }
  }
  const schema = optionsSchema(meta.schema);
  const spec: NativeRuleSpec = {
    engine: "eslint",
    ruleId: name,
    code: null,
    key: `eslint:${name}`,
    summary: documentation.summary,
    rationale: documentation.rationale,
    remediation: documentation.remediation,
    category: documentation.category,
    defaultLevel: documentation.defaultLevel ?? "error",
    languages: [...(documentation.languages ?? ["typescript"])],
    autofix: documentation.autofix ?? "none",
    aliases,
    limitations,
    filePatterns,
    references,
    since: documentation.since ?? null,
    examples,
    publicExamples,
    messageIds,
    optionsSchema: schema,
  };
  return deepFreeze(spec);
}

function optionsSchema(value: unknown): object | null {
  if (!Array.isArray(value)) return isObject(value) ? value : null;
  const items: readonly unknown[] = value;
  if (items.length === 0) return null;
  const [only] = items;
  return items.length === 1 && isObject(only)
    ? only
    : { type: "array", items };
}

function isObject(value: unknown): value is object {
  return value !== null && typeof value === "object";
}

function validateExample(example: RuleExample, messageIds: ReadonlySet<string>): void {
  if (!KEBAB_CASE.test(example.id)) {
    throw new TypeError("example ID must be lowercase kebab-case");
  }
  if (!KEBAB_CASE.test(example.scenarioId ?? "primary")) {
    throw new TypeError("example scenario must be lowercase kebab-case");
  }
  if (example.title.trim().length === 0) {
    throw new TypeError("example title must not be empty");
  }
  if (!Number.isSafeInteger(example.expectedCount) || example.expectedCount < 0) {
    throw new TypeError("example expected count must be a non-negative integer");
  }
  if (example.outcome === "match" && example.expectedCount < 1) {
    throw new TypeError("matching examples must expect at least one diagnostic");
  }
  if (example.outcome === "no-match" && example.expectedCount !== 0) {
    throw new TypeError("non-matching examples must expect zero diagnostics");
  }
  if (example.files.length === 0) {
    throw new TypeError("example files must not be empty");
  }
  const paths = example.files.map((file) => file.path);
  assertUnique(paths, "example file paths");
  for (const file of [...example.files, ...(example.fixedFiles ?? [])]) {
    assertSafeRelativePath(file.path, "example file path");
    if (file.source.length === 0) {
      throw new TypeError("example file source must not be empty");
    }
  }
  assertSafeRelativePath(example.focusPath, "example focus path");
  if (!paths.includes(example.focusPath)) {
    throw new TypeError("example focus path must name one example file");
  }
  assertUnique((example.fixedFiles ?? []).map((file) => file.path), "fixed example file paths");
  if (example.expectedDiagnostics !== undefined) {
    validateExpectedDiagnostics(example.expectedDiagnostics, example, messageIds);
  }
}

function validateExpectedDiagnostics(value: unknown, example: RuleExample, messageIds: ReadonlySet<string>): void {
  if (!Array.isArray(value) || value.length !== example.expectedCount) {
    throw new TypeError(`${example.id}: expectedDiagnostics must be an array matching expectedCount`);
  }
  const diagnostics: readonly unknown[] = value;
  for (const diagnostic of diagnostics) {
    validateExpectedDiagnostic(diagnostic, example.id, messageIds);
  }
}

function validateExpectedDiagnostic(value: unknown, exampleId: string, messageIds: ReadonlySet<string>): void {
  if (!isObject(value) ||
      !("messageId" in value) || typeof value.messageId !== "string" || !messageIds.has(value.messageId) ||
      !("message" in value) || typeof value.message !== "string" ||
      !("location" in value) ||
      !("automaticFix" in value) || typeof value.automaticFix !== "boolean" ||
      !("suggestions" in value) || !Array.isArray(value.suggestions)) {
    throw new TypeError(`${exampleId}: invalid expected diagnostic identity, message or delivery`);
  }
  assertFields(value, ["messageId", "message", "location", "automaticFix", "suggestions"], exampleId);
  validateExpectedLocation(value.location, exampleId);
  const suggestions: readonly unknown[] = value.suggestions;
  for (const suggestion of suggestions) {
    validateExpectedSuggestion(suggestion, exampleId, messageIds);
  }
}

function validateExpectedSuggestion(value: unknown, exampleId: string, messageIds: ReadonlySet<string>): void {
  if (!isObject(value) ||
      !("messageId" in value) || typeof value.messageId !== "string" || !messageIds.has(value.messageId) ||
      !("output" in value) || typeof value.output !== "string") {
    throw new TypeError(`${exampleId}: invalid expected suggestion identity or output`);
  }
  assertFields(value, ["messageId", "output"], exampleId);
}

function validateExpectedLocation(value: unknown, exampleId: string): void {
  if (!isObject(value) || !("line" in value) || !positiveCoordinate(value.line) ||
      !("column" in value) || !positiveCoordinate(value.column)) {
    throw new TypeError(`${exampleId}: expected diagnostic location requires positive integer coordinates`);
  }
  if (!("end" in value)) {
    assertFields(value, ["line", "column"], exampleId);
    return;
  }
  if (!isObject(value.end) || !("line" in value.end) || !positiveCoordinate(value.end.line) ||
      !("column" in value.end) || !positiveCoordinate(value.end.column) ||
      value.end.line < value.line || (value.end.line === value.line && value.end.column < value.column)) {
    throw new TypeError(`${exampleId}: expected diagnostic end point must be complete and ordered`);
  }
  assertFields(value.end, ["line", "column"], exampleId);
  assertFields(value, ["line", "column", "end"], exampleId);
}

function positiveCoordinate(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

function assertFields(value: object, expected: readonly string[], exampleId: string): void {
  const fields = Object.keys(value);
  if (fields.length !== expected.length || fields.some((field) => !expected.includes(field))) {
    throw new TypeError(`${exampleId}: unexpected or missing diagnostic expectation fields`);
  }
}

function assertSafeRelativePath(path: string, label: string): void {
  if (
    path.length === 0 ||
    path.startsWith("/") ||
    path.startsWith("\\") ||
    /^[A-Za-z]:[\\/]/u.test(path) ||
    path.split(/[\\/]/u).includes("..")
  ) {
    throw new TypeError(`${label} must be a safe relative path`);
  }
}

function assertUnique(values: readonly string[], label: string): void {
  if (new Set(values).size !== values.length) {
    throw new TypeError(`${label} must be unique`);
  }
}

function deepFreeze<Value>(value: Value): Readonly<Value> {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}
