/**
 * @fileoverview no-flake-masking — keep retries disabled and explicit test budgets within framework defaults.
 *
 * Ported from interfere-inc/landmines `no-flake-masking` (MIT), narrowed to framework-proven bindings
 * and to timeouts that exceed the framework default.
 */

import { defineRule, type ESTree, type Identifier, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { stableConstInitializer } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName, staticValue } from "../utils/static-string.js";
import {
  importedTestMockNamespace,
  isUnshadowedTestMockGlobal,
  runtimeNamedImport,
  runtimeTestFrameworkName,
  vitestFixtureTestName,
} from "../utils/test-mock-provenance.js";

const NAME = "no-flake-masking";

const UNIT_DEFAULT_TIMEOUT_MS = 5000;
const PLAYWRIGHT_DEFAULT_TIMEOUT_MS = 30_000;
const MAX_LITERAL_RETRY_DEPTH = 8;

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test", "describe", "suite"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set([
  "only", "skip", "todo", "concurrent", "sequential", "shuffle", "fails", "skipIf", "runIf", "each", "for",
]);
const CONFIG_FACTORIES: ReadonlySet<string> = new Set(["defineConfig", "defineProject", "mergeConfig"]);
const CONFIG_MODULES: ReadonlySet<string> = new Set(["vitest/config", "@playwright/test"]);

interface OptionKeys {
  readonly retry: string;
  readonly timeouts: ReadonlySet<string>;
  readonly defaultMs: number;
}

const UNIT_TEST_OPTIONS: OptionKeys = { retry: "retry", timeouts: new Set(["timeout"]), defaultMs: UNIT_DEFAULT_TIMEOUT_MS };
const VITEST_SET_CONFIG_OPTIONS: OptionKeys = {
  retry: "retry", timeouts: new Set(["testTimeout", "hookTimeout"]), defaultMs: UNIT_DEFAULT_TIMEOUT_MS,
};
const PLAYWRIGHT_CONFIGURE_OPTIONS: OptionKeys = {
  retry: "retries", timeouts: new Set(["timeout"]), defaultMs: PLAYWRIGHT_DEFAULT_TIMEOUT_MS,
};

type Report = (node: Node, messageId: "retry" | "timeout") => void;

function objectArgument(node: Node | undefined): ESTree.ObjectExpression | null {
  if (node === undefined) return null;
  const unwrapped = unwrapExpression(node);
  return unwrapped.type === "ObjectExpression" ? unwrapped : null;
}

/** The static value of a literal expression or an earlier unchanged local const, else null. */
function resolvedStaticValue(node: Node, source: Readonly<SourceCode>): ReturnType<typeof staticValue> {
  const unwrapped = unwrapExpression(node);
  if (unwrapped.type === "Identifier" && unwrapped.name === "undefined" &&
    (findVariable(source.getScope(unwrapped), unwrapped.name)?.defs.length ?? 0) === 0) return { value: undefined };
  return unwrapped.type === "Identifier"
    ? staticValue(stableConstInitializer(source, unwrapped)?.value)
    : staticValue(unwrapped);
}

/** A retry count enables reruns unless it is statically zero or false. */
function enablesRetry(node: Node, source: Readonly<SourceCode>, objectCount = false, depth = 0): boolean {
  const options = objectCount ? objectArgument(node) : null;
  if (options !== null) return retryObjectEnables(options, source, depth);
  const value = resolvedStaticValue(node, source);
  return value === null || (value.value !== undefined && value.value !== 0 && value.value !== false);
}

function retryObjectEnables(options: ESTree.ObjectExpression, source: Readonly<SourceCode>, depth: number): boolean {
  const count = retryObjectCount(options, source, depth);
  return count !== undefined && count !== "disabled" && count !== "set";
}

type RetryCount = "enabled" | "disabled" | "get" | "set" | "unknown";

function retryObjectCount(
  options: ESTree.ObjectExpression,
  source: Readonly<SourceCode>,
  depth: number,
  includePrototype = true,
): RetryCount | undefined {
  if (depth >= MAX_LITERAL_RETRY_DEPTH) return "unknown";
  let count: RetryCount | undefined;
  let inherited: RetryCount | undefined;
  for (const property of options.properties) {
    if (property.type !== "Property") {
      count = spreadRetryCount(property.argument, source, depth) ?? count;
      continue;
    }
    const key = getPropertyName(property);
    if (key === null) count = "unknown";
    else if (key === "count") count = nextRetryCount(property, source, count);
    else if (includePrototype && isPrototypeInitializer(property)) {
      inherited = prototypeEnablesRetry(property.value, source, depth) ? "enabled" : "disabled";
    }
  }
  return count ?? inherited;
}

function nextRetryCount(
  property: ESTree.ObjectProperty,
  source: Readonly<SourceCode>,
  previous: RetryCount | undefined,
): RetryCount {
  if (property.kind === "set") return previous === "get" || previous === "unknown" ? previous : "set";
  if (property.kind === "get") return "get";
  const value = resolvedStaticValue(property.value, source);
  return value === null || (value.value !== null && value.value !== undefined && value.value !== 0 && value.value !== false)
    ? "enabled" : "disabled";
}

function prototypeEnablesRetry(node: Node, source: Readonly<SourceCode>, depth: number): boolean {
  const prototype = resolvedStaticValue(node, source);
  if (prototype !== null && (prototype.value === null ||
    (typeof prototype.value !== "object" && typeof prototype.value !== "function"))) return false;
  return enablesRetry(node, source, true, depth + 1);
}

function spreadRetryCount(node: Node, source: Readonly<SourceCode>, depth: number): RetryCount | undefined {
  const spread = objectArgument(node);
  if (spread !== null) {
    const count = retryObjectCount(spread, source, depth + 1, false);
    if (count === "get") return "enabled";
    return count === "set" ? "disabled" : count;
  }
  const value = resolvedStaticValue(node, source);
  return value !== null && (value.value === null ||
    (typeof value.value !== "object" && typeof value.value !== "function")) ? undefined : "unknown";
}

function isPrototypeInitializer(property: ESTree.ObjectExpression["properties"][number]): boolean {
  return property.type === "Property" && getPropertyName(property) === "__proto__" &&
    property.kind === "init" && !property.computed && !property.shorthand && !property.method;
}

/** A timeout is raised when it statically exceeds the framework default. */
function raisesTimeout(node: Node, source: Readonly<SourceCode>, defaultMs: number): boolean {
  const value = staticNumber(node, source);
  return value !== null && value > defaultMs;
}

function staticNumber(node: Node, source: Readonly<SourceCode>): number | null {
  const value = resolvedStaticValue(node, source);
  return typeof value?.value === "number" ? value.value : null;
}

function inspectOptions(
  options: ESTree.ObjectExpression,
  source: Readonly<SourceCode>,
  report: Report,
  keys: OptionKeys,
): void {
  for (const property of options.properties) {
    if (property.type !== "Property") continue;
    const key = getPropertyName(property);
    if (key === keys.retry && enablesRetry(property.value, source, keys.retry === "retry")) report(property, "retry");
    else if (key !== null && keys.timeouts.has(key) && raisesTimeout(property.value, source, keys.defaultMs)) {
      report(property, "timeout");
    }
  }
}

/** A Vitest/Jest/Bun test or suite callee, through modifiers and `.each` tables. */
function isUnitTestCallee(callee: Node, source: Readonly<SourceCode>): boolean {
  const unwrapped = unwrapExpression(callee);
  if (unwrapped.type === "Identifier") {
    if (runtimeNamedImport(source, unwrapped)?.module === "@playwright/test") return false;
    const name = runtimeTestFrameworkName(source, unwrapped, "test") ?? vitestFixtureTestName(source, unwrapped);
    return name !== null && TEST_CALLERS.has(name);
  }
  if (unwrapped.type === "MemberExpression") {
    const member = getPropertyName(unwrapped);
    return member !== null && TEST_MODIFIERS.has(member) && isUnitTestCallee(unwrapped.object, source);
  }
  if (unwrapped.type === "CallExpression") return isUnitTestCallee(unwrapped.callee, source);
  if (unwrapped.type === "TaggedTemplateExpression") return isUnitTestCallee(unwrapped.tag, source);
  return false;
}

/** `test(name, options?, fn, options | timeout?)` — retry options and raised per-test timeouts. */
function inspectTestCall(node: ESTree.CallExpression, source: Readonly<SourceCode>, report: Report): void {
  const [, second, third] = node.arguments.map((argument) => unwrapExpression(argument));
  for (const argument of [second, third]) {
    const options = objectArgument(argument);
    if (options !== null) inspectOptions(options, source, report, UNIT_TEST_OPTIONS);
  }
  if (second !== undefined && third !== undefined && isFunction(second) && third.type !== "ObjectExpression" &&
      raisesTimeout(third, source, UNIT_DEFAULT_TIMEOUT_MS)) {
    report(third, "timeout");
  }
}

function isFunction(node: Node): boolean {
  return node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression";
}

/** `vi.setConfig`, `jest.setTimeout` and `jest.retryTimes` on the framework's own mock namespace. */
function inspectNamespaceCall(
  node: ESTree.CallExpression,
  callee: ESTree.MemberExpression,
  source: Readonly<SourceCode>,
  report: Report,
): void {
  const receiver = unwrapExpression(callee.object);
  if (receiver.type !== "Identifier") return;
  const namespace = importedTestMockNamespace(source, receiver) ??
    (isUnshadowedTestMockGlobal(source, receiver) ? (receiver.name === "vi" ? "vitest" : "jest") : null);
  const method = getPropertyName(callee);
  const [first] = node.arguments;
  if (first === undefined || namespace === null) return;
  if (namespace === "vitest" && method === "setConfig") {
    const options = objectArgument(first);
    if (options !== null) inspectOptions(options, source, report, VITEST_SET_CONFIG_OPTIONS);
  } else if (namespace === "jest" && method === "retryTimes" && enablesRetry(first, source)) {
    report(node, "retry");
  } else if (namespace === "jest" && method === "setTimeout" && raisesTimeout(first, source, UNIT_DEFAULT_TIMEOUT_MS)) {
    report(node, "timeout");
  }
}

/** Playwright `test.setTimeout(n)` and `test.describe.configure({ retries, timeout })`. */
function inspectPlaywrightCall(
  node: ESTree.CallExpression,
  callee: ESTree.MemberExpression,
  source: Readonly<SourceCode>,
  report: Report,
): void {
  const root = memberRoot(callee.object);
  const origin = root === null ? null : runtimeNamedImport(source, root);
  if (origin?.module !== "@playwright/test" || origin.name !== "test") return;
  const method = getPropertyName(callee);
  const [first] = node.arguments;
  if (first === undefined) return;
  if (method === "setTimeout" && raisesTimeout(first, source, PLAYWRIGHT_DEFAULT_TIMEOUT_MS)) {
    report(node, "timeout");
  } else if (method === "configure") {
    const options = objectArgument(first);
    if (options !== null) inspectOptions(options, source, report, PLAYWRIGHT_CONFIGURE_OPTIONS);
  }
}

/** The root identifier of a member chain such as `test.describe.configure`. */
function memberRoot(node: Node): Identifier | null {
  const unwrapped = unwrapExpression(node);
  if (unwrapped.type === "Identifier") return unwrapped;
  return unwrapped.type === "MemberExpression" ? memberRoot(unwrapped.object) : null;
}

function eachObjectElement(node: Node, visit: (element: ESTree.ObjectExpression) => void): void {
  const array = unwrapExpression(node);
  if (array.type !== "ArrayExpression") return;
  for (const element of array.elements) {
    const object = element === null ? null : objectArgument(element);
    if (object !== null) visit(object);
  }
}

/** Vitest config: `test.retry`, recursing into `test.projects` and top-level `projects`. */
function inspectVitestConfig(config: ESTree.ObjectExpression, source: Readonly<SourceCode>, report: Report): void {
  for (const property of config.properties) {
    if (property.type !== "Property") continue;
    const key = getPropertyName(property);
    if (key === "projects") eachObjectElement(property.value, (project) => { inspectVitestConfig(project, source, report); });
    const test = key === "test" ? objectArgument(property.value) : null;
    if (test !== null) inspectVitestTestOptions(test, source, report);
  }
}

function inspectVitestTestOptions(test: ESTree.ObjectExpression, source: Readonly<SourceCode>, report: Report): void {
  for (const option of test.properties) {
    if (option.type !== "Property") continue;
    const key = getPropertyName(option);
    if (key === "retry" && enablesRetry(option.value, source, true)) report(option, "retry");
    if (key === "projects") eachObjectElement(option.value, (project) => { inspectVitestConfig(project, source, report); });
  }
}

/** Playwright config: top-level and per-project `retries`. */
function inspectPlaywrightConfig(config: ESTree.ObjectExpression, source: Readonly<SourceCode>, report: Report): void {
  for (const property of config.properties) {
    if (property.type !== "Property") continue;
    const key = getPropertyName(property);
    if (key === "retries" && enablesRetry(property.value, source)) report(property, "retry");
    if (key === "projects") eachObjectElement(property.value, (project) => { inspectPlaywrightConfig(project, source, report); });
  }
}

function inspectConfigCall(node: ESTree.CallExpression, callee: Identifier, source: Readonly<SourceCode>, report: Report): void {
  const origin = runtimeNamedImport(source, callee);
  if (origin === null || !CONFIG_FACTORIES.has(origin.name)) return;
  const inspect = origin.module === "vitest/config"
    ? inspectVitestConfig
    : origin.module === "@playwright/test" ? inspectPlaywrightConfig : null;
  if (inspect === null) return;
  for (const argument of node.arguments) {
    const config = objectArgument(argument);
    if (config !== null) inspect(config, source, report);
  }
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep test retries disabled and explicit test timeouts within framework defaults.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      retry:
        "Do not retry tests. A test that passes on rerun is a flake: await the event it depends on and fix the race instead of hiding it.",
      timeout:
        "Do not raise a test timeout above the framework default. Await the event the test depends on, or move slow shared setup into a beforeAll hook.",
    },
  },
  createOnce(context) {
    let testFile = false;
    let importsConfigModule = false;
    const report: Report = (node, messageId) => { context.report({ node, messageId }); };
    return {
      before() {
        testFile = isTestFile({ filename: context.filename, cwd: context.cwd });
        importsConfigModule = context.sourceCode.ast.body.some((statement) =>
          statement.type === "ImportDeclaration" && CONFIG_MODULES.has(statement.source.value));
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const source = context.sourceCode;
        const callee = unwrapExpression(node.callee);
        if (importsConfigModule && callee.type === "Identifier") inspectConfigCall(node, callee, source, report);
        if (!testFile) return;
        if (callee.type === "MemberExpression") {
          inspectNamespaceCall(node, callee, source, report);
          inspectPlaywrightCall(node, callee, source, report);
        }
        if (isUnitTestCallee(callee, source)) inspectTestCall(node, source, report);
      },
    };
  },
});
