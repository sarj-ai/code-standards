/**
 * @fileoverview no-string-concat-in-loop — `+=` on a string inside a loop rebuilds the whole string every pass, which is O(n^2).
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-string-concat-in-loop.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";
import type { Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noStringConcatInLoop" | "noStringReduce";
type Options = readonly [];

export const noStringConcatInLoopDocumentation = {
  summary:
    "Disallow O(n^2) string building via `+=` on a string variable inside a loop; push parts to an array and `join` instead.",
  rationale:
    "Repeatedly rebuilding a growing string can copy all prior content on each iteration, making total work grow quadratically.",
  remediation: "Collect each fragment in an array, then join the fragments after the loop.",
  category: "performance",
  limitations: [
    "Only local identifiers initialized with a string or template literal and accumulated in a loop body are inspected.",
  ],
  examples: [
    {
      id: "join-fragments",
      title: "Join collected fragments after the loop",
      outcome: "no-match",
      files: [{ path: "src/render.ts", source: "const parts = []; for (const item of items) { parts.push(item); } const output = parts.join(\"\");" }],
      focusPath: "src/render.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "rebuild-string",
      title: "Do not rebuild a growing string in a loop",
      outcome: "match",
      files: [{ path: "src/render.ts", source: "let output = ''; for (const item of items) { output = `${output}${item}`; }" }],
      focusPath: "src/render.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const LOOP_NODE_TYPES: ReadonlySet<string> = new Set([
  "ForStatement",
  "ForOfStatement",
  "ForInStatement",
  "WhileStatement",
  "DoWhileStatement",
]);

/** Resolves an identifier through its enclosing scopes. */
function findVariable(
  scope: Scope.Scope,
  name: string,
): Scope.Variable | undefined {
  let current: Scope.Scope | null = scope;
  while (current !== null) {
    const variable = current.variables.find((v) => v.name === name);
    if (variable !== undefined) {
      return variable;
    }
    current = current.upper;
  }
  return undefined;
}

/** Requires exactly one variable declaration with a string-literal initializer. */
function isStringInitializedVariable(variable: Scope.Variable): boolean {
  if (variable.defs.length !== 1) {
    return false;
  }
  const def = variable.defs[0];
  if (def === undefined || def.type !== "Variable") {
    return false;
  }
  const declarator = def.node;
  if (declarator.type !== "VariableDeclarator") {
    return false;
  }
  if (isStringLiteralInit(declarator.init)) return true;
  if (
    declarator.id.type === "Identifier" &&
    declarator.id.typeAnnotation?.typeAnnotation.type === "TSStringKeyword"
  ) {
    return true;
  }
  return isTemplateStringsArrayElement(declarator.init, variable.scope);
}

/** A tagged-template parameter is statically a string at every numeric index. */
function isTemplateStringsArrayElement(
  node: TSESTree.Expression | null,
  scope: Scope.Scope,
): boolean {
  if (
    node?.type !== "MemberExpression" ||
    !node.computed ||
    node.object.type !== "Identifier"
  ) {
    return false;
  }
  const source = findVariable(scope, node.object.name);
  if (source?.defs.length !== 1) return false;
  const name = source.defs[0]?.name;
  return (
    name?.type === "Identifier" &&
    name.typeAnnotation?.typeAnnotation.type === "TSTypeReference" &&
    name.typeAnnotation.typeAnnotation.typeName.type === "Identifier" &&
    name.typeAnnotation.typeAnnotation.typeName.name === "TemplateStringsArray"
  );
}

/** Checks whether an initializer is a string or template literal. */
function isStringLiteralInit(node: TSESTree.Expression | null): boolean {
  if (node === null) {
    return false;
  }
  if (node.type === "TemplateLiteral") {
    return true;
  }
  if (node.type === "Literal") {
    return typeof node.value === "string";
  }
  return false;
}

/** Recognizes longhand accumulation such as `s = s + x`. */
function isConcatOntoTarget(
  rhs: TSESTree.Expression,
  target: string,
): boolean {
  if (rhs.type === "TemplateLiteral") {
    return rhs.expressions.some(
      (expression) =>
        expression.type === "Identifier" && expression.name === target,
    );
  }
  if (rhs.type !== "BinaryExpression" || rhs.operator !== "+") {
    return false;
  }
  return isConcatOperand(rhs.left, target) || isConcatOperand(rhs.right, target);
}

/** Finds a target identifier in a chained `+` expression. */
function isConcatOperand(
  node: TSESTree.Expression | TSESTree.PrivateIdentifier,
  target: string,
): boolean {
  if (node.type === "Identifier") {
    return node.name === target;
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    return (
      isConcatOperand(node.left, target) || isConcatOperand(node.right, target)
    );
  }
  return false;
}

/** Checks whether the loop creates a fresh accumulator on every iteration. */
function isDeclaredInsideLoop(
  variable: Scope.Variable,
  repetition: TSESTree.Node,
): boolean {
  const def = variable.defs[0];
  if (def === undefined) {
    return false;
  }
  const body = repetition.type === "CallExpression"
    ? repetition.arguments[0]
    : (
        repetition as
          | TSESTree.ForStatement
          | TSESTree.ForOfStatement
          | TSESTree.ForInStatement
          | TSESTree.WhileStatement
          | TSESTree.DoWhileStatement
      ).body;
  if (body === undefined || body.type === "SpreadElement") return false;
  const [declStart, declEnd] = def.node.range;
  const [bodyStart, bodyEnd] = body.range;
  return declStart >= bodyStart && declEnd <= bodyEnd;
}

/** Finds the nearest loop whose body contains the assignment. */
function enclosingLoop(node: TSESTree.Node): TSESTree.Node | null {
  let child: TSESTree.Node = node;
  let parent = node.parent;
  while (parent !== undefined && parent !== null) {
    if (
      (parent.type === "ArrowFunctionExpression" ||
        parent.type === "FunctionExpression") &&
      parent.parent.type === "CallExpression" &&
      parent.parent.arguments[0] === parent &&
      parent.parent.callee.type === "MemberExpression" &&
      !parent.parent.callee.computed &&
      parent.parent.callee.property.type === "Identifier" &&
      parent.parent.callee.property.name === "forEach"
    ) {
      return parent.parent;
    }
    if (LOOP_NODE_TYPES.has(parent.type)) {
      const loop = parent as
        | TSESTree.ForStatement
        | TSESTree.ForOfStatement
        | TSESTree.ForInStatement
        | TSESTree.WhileStatement
        | TSESTree.DoWhileStatement;
      if (loop.body === child) {
        return loop;
      }
    }
    child = parent;
    parent = parent.parent;
  }
  return null;
}

/** A small literal loop cannot exhibit unbounded quadratic growth. */
function isSmallStaticForLoop(node: TSESTree.Node): boolean {
  if (
    node.type !== "ForStatement" ||
    node.init?.type !== "VariableDeclaration" ||
    node.init.declarations.length !== 1 ||
    node.test?.type !== "BinaryExpression" ||
    (node.test.operator !== "<" && node.test.operator !== "<=") ||
    node.update?.type !== "UpdateExpression" ||
    node.update.operator !== "++"
  ) {
    return false;
  }
  const declaration = node.init.declarations[0];
  if (
    declaration?.id.type !== "Identifier" ||
    declaration.init?.type !== "Literal" ||
    typeof declaration.init.value !== "number" ||
    !Number.isInteger(declaration.init.value) ||
    node.test.left.type !== "Identifier" ||
    node.test.left.name !== declaration.id.name ||
    node.test.right.type !== "Literal" ||
    typeof node.test.right.value !== "number" ||
    !Number.isInteger(node.test.right.value) ||
    node.update.argument.type !== "Identifier" ||
    node.update.argument.name !== declaration.id.name
  ) {
    return false;
  }
  const iterations =
    node.test.right.value -
    declaration.init.value +
    (node.test.operator === "<=" ? 1 : 0);
  return iterations >= 0 && iterations <= 8;
}

/** Recognizes an exact Array.reduce-style string accumulator. */
function isStringSeededReduce(node: TSESTree.CallExpression): boolean {
  if (
    node.callee.type !== "MemberExpression" ||
    node.callee.computed ||
    node.callee.property.type !== "Identifier" ||
    node.callee.property.name !== "reduce" ||
    node.arguments.length !== 2
  ) {
    return false;
  }
  const [callback, initial] = node.arguments;
  if (
    node.callee.object.type === "ArrayExpression" &&
    node.callee.object.elements.length <= 8
  ) {
    return false;
  }
  if (
    callback === undefined ||
    initial === undefined ||
    callback.type === "SpreadElement" ||
    initial.type === "SpreadElement" ||
    (callback.type !== "ArrowFunctionExpression" && callback.type !== "FunctionExpression") ||
    callback.params[0]?.type !== "Identifier" ||
    !isStringLiteralInit(initial)
  ) {
    return false;
  }
  const accumulator = callback.params[0].name;
  if (callback.body.type !== "BlockStatement") {
    return isConcatOntoTarget(callback.body, accumulator);
  }
  if (callback.body.body.length !== 1 || callback.body.body[0]?.type !== "ReturnStatement") {
    return false;
  }
  const returned = callback.body.body[0].argument;
  return returned !== null && isConcatOntoTarget(returned, accumulator);
}

export default createRule<Options, MessageIds>({
  name: "no-string-concat-in-loop",
  documentation: noStringConcatInLoopDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow O(n^2) string building via `+=` on a string variable inside a loop; push parts to an array and `join` instead.",
    },
    schema: [],
    messages: {
      noStringConcatInLoop:
        "Avoid building a string with `+=` inside a loop — this is O(n^2). Push the parts onto an array and use `arr.join(\"\")` after the loop.",
      noStringReduce:
        "Avoid concatenating a growing string in `reduce` — this is O(n^2). Map the fragments and join them once instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    // Report each accumulator once per loop.
    const reported = new WeakMap<TSESTree.Node, Set<string>>();

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (isStringSeededReduce(node)) {
          context.report({ node, messageId: "noStringReduce" });
        }
      },
      AssignmentExpression(node: TSESTree.AssignmentExpression): void {
        // The LHS must be a plain variable reference.
        if (node.left.type !== "Identifier") {
          return;
        }
        // Accept both the compound `s += x` and the longhand `s = s + x`; any
        // other operator/shape (`s = x + y`, `s -= x`, ...) is not accumulation.
        const isAccumulation =
          node.operator === "+=" ||
          (node.operator === "=" &&
            isConcatOntoTarget(node.right, node.left.name));
        if (!isAccumulation) {
          return;
        }
        // Must occur inside a loop body, else it's a one-shot append.
        const loop = enclosingLoop(node);
        if (loop === null) {
          return;
        }
        if (isSmallStaticForLoop(loop)) {
          return;
        }

        const scope = context.sourceCode.getScope(node);
        const variable = findVariable(scope, node.left.name);
        // Conservative: can't resolve the declaration -> don't flag.
        if (variable === undefined) {
          return;
        }
        if (!isStringInitializedVariable(variable)) {
          return;
        }
        if (isDeclaredInsideLoop(variable, loop)) {
          return;
        }

        let seen = reported.get(loop);
        if (seen === undefined) {
          seen = new Set<string>();
          reported.set(loop, seen);
        }
        if (seen.has(node.left.name)) {
          return;
        }
        seen.add(node.left.name);

        context.report({
          node,
          messageId: "noStringConcatInLoop",
        });
      },
    };
  },
});
