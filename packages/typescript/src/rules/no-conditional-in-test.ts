import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "noConditionalInTest";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/** The nearest enclosing function of `node`. */
function nearestEnclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current;
    }
  }
  return null;
}

/** The base callee name of a call, unwrapping `.only` / `.skip` / `.each` chains. */
function testCallerName(callee: TSESTree.Node): string | null {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return callee.name;
  }
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    return testCallerName(callee.object);
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return testCallerName(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return testCallerName(callee.tag);
  }
  return null;
}

/** True when `fn` is the callback argument of an `it` or `test` call. */
function isTestBody(fn: TSESTree.Node): boolean {
  const call = fn.parent;
  if (
    call?.type !== AST_NODE_TYPES.CallExpression ||
    !call.arguments.some((argument) => argument === fn)
  ) {
    return false;
  }
  const name = testCallerName(call.callee);
  return name !== null && TEST_CALLERS.has(name);
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-conditional-in-test",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow conditional logic (if, switch, ternary) in test bodies, which can hide missing assertions or test multiple code paths.",
    },
    schema: [],
    messages: {
      noConditionalInTest:
        "Avoid using conditional logic in tests. It can obscure intent and hide unexecuted assertions. Split the test instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    const report = (node: TSESTree.Node): void => {
      const enclosing = nearestEnclosingFunction(node);
      if (enclosing === null || !isTestBody(enclosing)) {
        return;
      }
      context.report({ node, messageId: "noConditionalInTest" });
    };
    return {
      IfStatement(node: TSESTree.IfStatement): void {
        report(node);
      },
      SwitchStatement(node: TSESTree.SwitchStatement): void {
        report(node);
      },
      ConditionalExpression(node: TSESTree.ConditionalExpression): void {
        report(node);
      },
      LogicalExpression(node: TSESTree.LogicalExpression): void {
        report(node);
      },
    };
  },
});
