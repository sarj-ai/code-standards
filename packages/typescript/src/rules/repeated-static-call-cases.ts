/**
 * @fileoverview repeated-static-call-cases — repeated literal call assertions should be named, independently reported cases.
 *
 * Port of the 18.x `repeated-static-call-cases` rule. The rule is
 * untyped, so the port covers all of it. Its duplicate-test-body exclusion
 * uses the fingerprint the duplicate-test-body port exports.
 */

import { defineRule, type Context, type ESTree, type Node, type SourceCode } from "../types.js";
import { directArgumentCall, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { duplicateTestBodyCandidate } from "./duplicate-test-body.js";

const NAME = "repeated-static-call-cases";

const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const EXPECT_MODIFIERS: ReadonlySet<string> = new Set(["not", "rejects", "resolves"]);
const SNAPSHOT_MATCHERS = /snapshot/iu;
const MIN_CASES = 3;

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

interface AssertionShape {
  statement: ESTree.ExpressionStatement;
  skeleton: string;
  values: string;
}

interface PendingFinding {
  readonly callback: FunctionNode;
  readonly count: number;
  readonly statement: ESTree.ExpressionStatement;
}

/** The test-module export an identifier imports; its own name when it is an unbound global. */
function importedName(identifier: Node & { name: string }, context: Context): string | null {
  const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return identifier.name;
  for (const definition of variable.defs) {
    if (definition.node.type !== "ImportSpecifier") continue;
    const declaration = definition.node.parent;
    if (declaration.type !== "ImportDeclaration" || !TEST_MODULES.has(declaration.source.value)) continue;
    return importSpecifierName(definition.node);
  }
  return null;
}

function isDirectTestCallback(node: Node, context: Context) {
  if (node.type !== "ArrowFunctionExpression" && node.type !== "FunctionExpression") return false;
  const call = directArgumentCall(node);
  if (call === null) return false;
  const root = testRoot(call.callee);
  return root !== null && TEST_NAMES.has(importedName(root, context) ?? "");
}

function testRoot(callee: Node): ESTree.IdentifierReference | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return callee as ESTree.IdentifierReference;
  if (callee.type !== "MemberExpression") return null;
  const modifier = getPropertyName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function isStatic(input: Node): boolean {
  const node = unwrapExpression(input);
  switch (node.type) {
    case "Literal": return true;
    case "TemplateLiteral": return node.expressions.length === 0;
    case "UnaryExpression": return (node.operator === "+" || node.operator === "-") && isStatic(node.argument);
    case "ArrayExpression": return node.elements.every((item) => item !== null && item.type !== "SpreadElement" && isStatic(item));
    case "ObjectExpression": return node.properties.every((property) => property.type === "Property" && !property.computed && property.kind === "init" && (property.value as Node).type !== "AssignmentPattern" && isStatic(property.value));
    default: return false;
  }
}

/** Preserve literal container/operator structure while replacing the values. */
function staticShape(input: Node): string {
  const node = unwrapExpression(input);
  switch (node.type) {
    case "Literal": return `literal:${typeof node.value}`;
    case "TemplateLiteral": return "template";
    case "UnaryExpression": return `unary:${node.operator}:${staticShape(node.argument)}`;
    case "ArrayExpression": return `array(${node.elements.map((item) => item === null || item.type === "SpreadElement" ? "invalid" : staticShape(item)).join(",")})`;
    case "ObjectExpression":
      return `object(${node.properties.map((property) => {
        if (property.type !== "Property" || property.computed || (property.value as Node).type === "AssignmentPattern") return "invalid";
        const key = property.key.type === "Identifier" ? property.key.name : String((property.key as { value: unknown }).value);
        return `${key}:${staticShape(property.value)}`;
      }).join(",")})`;
    default: return "dynamic";
  }
}

interface StaticCallAssertion {
  readonly observed: ESTree.CallExpression;
  readonly observedCallee: Extract<Node, { type: "Identifier" }>;
  readonly expected: Node;
  readonly modifiers: readonly string[];
  readonly matcher: string;
}

function assertionShape(statement: Node, context: Context, callback: FunctionNode): AssertionShape | null {
  if (statement.type !== "ExpressionStatement") return null;
  const assertion = staticCallAssertion(statement, context);
  if (assertion === null) return null;
  const { observed, observedCallee, expected, modifiers, matcher } = assertion;
  // A callee defined inside the test is setup, not a shared subject.
  const binding = findVariable(context.sourceCode.getScope(observedCallee), observedCallee.name);
  if (binding?.defs.some((definition) =>
    definition.node.range[0] >= callback.range[0] && definition.node.range[1] <= callback.range[1],
  )) return null;
  const skeleton = `${observedCallee.name}/${observed.arguments.map((item) => staticShape(item)).join(",")}/${modifiers.join(".")}/${matcher}/${staticShape(expected)}`;
  const values = [...observed.arguments, expected].map((item) => context.sourceCode.getText(item)).join("\u0000");
  return { statement, skeleton, values };
}

/** `expect(fn(...static))[.modifiers].matcher(static)` from an imported `expect`. */
function staticCallAssertion(statement: ESTree.ExpressionStatement, context: Context): StaticCallAssertion | null {
  const matcherCall = unwrapExpression(statement.expression);
  if (matcherCall.type !== "CallExpression" || matcherCall.arguments.length !== 1) return null;
  const matcherCallee = unwrapExpression(matcherCall.callee);
  const matcher = matcherCallee.type === "MemberExpression" ? getPropertyName(matcherCallee) : null;
  if (matcherCallee.type !== "MemberExpression" || matcher === null || SNAPSHOT_MATCHERS.test(matcher)) return null;
  const chain = importedExpectCall(matcherCallee, context);
  if (chain === null) return null;
  const [expected] = matcherCall.arguments;
  if (expected === undefined || expected.type === "SpreadElement" || !isStatic(expected)) return null;
  const observed = staticCall(chain.call.arguments[0]);
  return observed === null ? null : { ...observed, expected, modifiers: chain.modifiers, matcher };
}

/** The one-argument `expect(…)` call, from a test module, under a matcher's modifiers. */
function importedExpectCall(matcherCallee: ESTree.MemberExpression, context: Context): ReturnType<typeof expectCallFromMatcher> {
  const chain = expectCallFromMatcher(matcherCallee);
  if (chain === null || chain.call.arguments.length !== 1) return null;
  const expectCallee = unwrapExpression(chain.call.callee);
  return expectCallee.type === "Identifier" && importedName(expectCallee, context) === "expect" ? chain : null;
}

/** `fn(...)` on a plain identifier, with at least one argument and only static ones. */
function staticCall(argument: ESTree.Argument | undefined): Pick<StaticCallAssertion, "observed" | "observedCallee"> | null {
  const observed = argument === undefined ? undefined : unwrapExpression(argument);
  if (observed?.type !== "CallExpression" || observed.arguments.length === 0 ||
    observed.arguments.some((arg) => arg.type === "SpreadElement" || !isStatic(arg))) return null;
  const observedCallee = unwrapExpression(observed.callee);
  return observedCallee.type === "Identifier" ? { observed, observedCallee } : null;
}

function expectCallFromMatcher(node: ESTree.MemberExpression): { call: ESTree.CallExpression; modifiers: string[] } | null {
  const modifiers: string[] = [];
  let receiver: Node = node.object;
  while (receiver.type === "MemberExpression") {
    const modifier = getPropertyName(receiver);
    if (modifier === null || !EXPECT_MODIFIERS.has(modifier)) return null;
    modifiers.unshift(modifier);
    receiver = receiver.object;
  }
  return receiver.type === "CallExpression" ? { call: receiver, modifiers } : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Review three or more consecutive static-input call assertions as potential named cases.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { repeatedStaticCallCases: "These {{count}} consecutive assertions repeat a call with static inputs. If independent, use named parameterized cases or subtests; preserve ordered scenarios as one test." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const duplicateGroups = new Map<Node, Map<string, FunctionNode[]>>();
    const pending: PendingFinding[] = [];

    function visitFunction(node: FunctionNode): void {
      const call = directArgumentCall(node);
      if (call !== null) {
        const duplicate = duplicateTestBodyCandidate(call, sourceCode);
        if (duplicate !== null && duplicate.body === node) {
          const groups = duplicateGroups.get(duplicate.container) ?? new Map<string, FunctionNode[]>();
          const owners = groups.get(duplicate.fingerprint) ?? [];
          owners.push(node);
          groups.set(duplicate.fingerprint, owners);
          duplicateGroups.set(duplicate.container, groups);
        }
      }
      if (!isDirectTestCallback(node, context) || node.body?.type !== "BlockStatement") return;
      let run: AssertionShape[] = [];
      const flush = (): void => {
        const first = run[0];
        const last = run.at(-1);
        if (first !== undefined && last !== undefined && run.length >= MIN_CASES &&
          new Set(run.map((item) => item.values)).size > 1 &&
          !sourceCode.getAllComments().some((comment) => comment.range[0] >= first.statement.range[0] && comment.range[1] <= last.statement.range[1])) {
          pending.push({ callback: node, count: run.length, statement: first.statement });
        }
        run = [];
      };
      for (const statement of node.body.body) {
        const shape = assertionShape(statement, context, node);
        if (shape === null || (run.length > 0 && run[0]?.skeleton !== shape.skeleton)) flush();
        if (shape !== null) run.push(shape);
      }
      flush();
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        duplicateGroups.clear();
        pending.length = 0;
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, sourceCode.text)) return false;
        return undefined;
      },
      ArrowFunctionExpression: visitFunction,
      FunctionExpression: visitFunction,
      "Program:exit"(): void {
        const duplicateOwners = new Set<FunctionNode>();
        for (const groups of duplicateGroups.values()) {
          for (const owners of groups.values()) {
            if (owners.length > 1) owners.forEach((owner) => duplicateOwners.add(owner));
          }
        }
        for (const finding of pending) {
          if (duplicateOwners.has(finding.callback)) continue;
          context.report({
            node: finding.statement,
            messageId: "repeatedStaticCallCases",
            data: { count: String(finding.count) },
          });
        }
      },
    };
  },
});
