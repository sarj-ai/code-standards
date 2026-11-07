/**
 * @fileoverview no-string-concat-in-loop — repeated string accumulation in loops.
 *
 * Port of the 18.x `no-string-concat-in-loop` rule. The rule is untyped,
 * so the port covers all of it.
 */

import { defineRule, type ESTree, type Node, type Scope, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import { literalStringLoopFix } from "./_literal-string-loop-fix.js";

const NAME = "no-string-concat-in-loop";

type LoopStatement =
  | ESTree.ForStatement
  | ESTree.ForOfStatement
  | ESTree.ForInStatement
  | ESTree.WhileStatement
  | ESTree.DoWhileStatement;

const LOOP_NODE_TYPES: ReadonlySet<string> = new Set([
  "ForStatement",
  "ForOfStatement",
  "ForInStatement",
  "WhileStatement",
  "DoWhileStatement",
]);

/** Requires exactly one variable declaration with a string-literal initializer. */
function isStringInitializedVariable(variable: TsVariable): boolean {
  if (variable.defs.length !== 1) return false;
  const def = variable.defs[0];
  if (def === undefined || def.type !== "Variable") return false;
  const declarator = def.node;
  if (declarator.type !== "VariableDeclarator") return false;
  if (isStringLiteralInit(declarator.init)) return true;
  if (declarator.id.type === "Identifier" && declarator.id.typeAnnotation?.typeAnnotation.type === "TSStringKeyword") {
    return true;
  }
  return isTemplateStringsArrayElement(declarator.init, variable.scope);
}

/** A tagged-template parameter is statically a string at every numeric index. */
function isTemplateStringsArrayElement(node: Node | null, scope: Scope): boolean {
  if (node?.type !== "MemberExpression" || !node.computed || node.object.type !== "Identifier") return false;
  const source = findVariable(scope, node.object.name);
  if (source?.defs.length !== 1) return false;
  const name = source.defs[0]?.name as Node | undefined;
  if (name?.type !== "Identifier") return false;
  const annotation = name.typeAnnotation?.typeAnnotation;
  return (
    annotation?.type === "TSTypeReference" &&
    annotation.typeName.type === "Identifier" &&
    annotation.typeName.name === "TemplateStringsArray"
  );
}

/** Checks whether an initializer is a string or template literal. */
function isStringLiteralInit(node: Node | null): boolean {
  if (node === null) return false;
  node = unwrapExpression(node);
  if (node.type === "TemplateLiteral") return true;
  if (node.type === "Literal") return typeof node.value === "string";
  return false;
}

/** Recognizes longhand accumulation such as `s = s + x`. */
function isConcatOntoTarget(rhs: Node, target: string): boolean {
  if (rhs.type === "TemplateLiteral") {
    return rhs.expressions.some((expression) => expression.type === "Identifier" && expression.name === target);
  }
  if (rhs.type !== "BinaryExpression" || rhs.operator !== "+") return false;
  return isConcatOperand(rhs.left, target) || isConcatOperand(rhs.right, target);
}

/** Finds a target identifier in a chained `+` expression. */
function isConcatOperand(node: Node, target: string): boolean {
  if (node.type === "Identifier") return node.name === target;
  if (node.type === "BinaryExpression" && node.operator === "+") {
    return isConcatOperand(node.left, target) || isConcatOperand(node.right, target);
  }
  return false;
}

/** Checks whether the loop creates a fresh accumulator on every iteration. */
function isDeclaredInsideLoop(variable: TsVariable, repetition: Node): boolean {
  const def = variable.defs[0];
  if (def === undefined) return false;
  const body = repetition.type === "CallExpression" ? repetition.arguments[0] : (repetition as LoopStatement).body;
  if (body === undefined || body.type === "SpreadElement") return false;
  const [declStart, declEnd] = def.node.range;
  const [bodyStart, bodyEnd] = body.range;
  return declStart >= bodyStart && declEnd <= bodyEnd;
}

/** Finds the nearest loop whose body contains the assignment. */
function enclosingLoop(node: Node): Node | null {
  let child: Node = node;
  let parent = parentOf(node);
  while (parent !== null) {
    const grandparent = parentOf(parent);
    if (isForEachCallback(parent, grandparent)) return grandparent;
    if (isFunctionNode(parent)) return null;
    if (LOOP_NODE_TYPES.has(parent.type) && (parent as LoopStatement).body === child) return parent;
    child = parent;
    parent = grandparent;
  }
  return null;
}

/** True for the callback passed as the first argument of `items.forEach(...)`. */
function isForEachCallback(node: Node, call: Node | null): boolean {
  return (
    (node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression") &&
    call?.type === "CallExpression" &&
    call.arguments[0] === node &&
    call.callee.type === "MemberExpression" &&
    !call.callee.computed &&
    call.callee.property.type === "Identifier" &&
    call.callee.property.name === "forEach"
  );
}

function isFunctionNode(node: Node): boolean {
  return node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression" || node.type === "FunctionDeclaration";
}

function immediatelyExitsLoop(node: ESTree.AssignmentExpression, loop: Node): boolean {
  const statement = parentOf(node);
  if (!LOOP_NODE_TYPES.has(loop.type) || statement?.type !== "ExpressionStatement") return false;
  const block = parentOf(statement);
  if (block?.type !== "BlockStatement") return false;
  const next = block.body[block.body.indexOf(statement) + 1];
  return isLoopExit(next) && !exitIsIntercepted(block, loop, next?.type === "BreakStatement");
}

/** An unlabeled `break`, a `return` or a `throw` leaves the loop for good. */
function isLoopExit(node: Node | undefined): boolean {
  return (node?.type === "BreakStatement" && node.label === null) || node?.type === "ReturnStatement" || node?.type === "ThrowStatement";
}

/** A `try` can resume the loop after the exit, and a `switch` captures a `break`. */
function exitIsIntercepted(block: Node, loop: Node, isBreak: boolean): boolean {
  for (let current: Node | null = block; current !== null && current !== loop; current = parentOf(current)) {
    if (current.type === "TryStatement" || (isBreak && current.type === "SwitchStatement")) return true;
  }
  return false;
}

/** A small literal loop cannot exhibit unbounded quadratic growth. */
function isSmallStaticForLoop(node: Node): boolean {
  if (node.type !== "ForStatement") return false;
  const iterations = staticForLoopIterations(node);
  return iterations !== null && iterations >= 0 && iterations <= 8;
}

/** Iteration count of `for (let i = A; i < B; i++)` with integer literals, else null. */
function staticForLoopIterations(node: ESTree.ForStatement): number | null {
  const { test } = node;
  const counter = literalCounter(node.init);
  if (
    counter === null ||
    test?.type !== "BinaryExpression" ||
    (test.operator !== "<" && test.operator !== "<=") ||
    !isIdentifierNamed(test.left, counter.name) ||
    !incrementsCounter(node.update, counter.name)
  ) {
    return null;
  }
  const end = integerLiteral(test.right);
  return end === null ? null : end - counter.start + (test.operator === "<=" ? 1 : 0);
}

/** The counter declared by `let i = <integer>`, else null. */
function literalCounter(init: ESTree.ForStatement["init"]): { readonly name: string; readonly start: number } | null {
  if (init?.type !== "VariableDeclaration" || init.declarations.length !== 1) return null;
  const declaration = init.declarations[0];
  const start = integerLiteral(declaration?.init);
  return declaration?.id.type === "Identifier" && start !== null ? { name: declaration.id.name, start } : null;
}

function incrementsCounter(update: ESTree.ForStatement["update"], name: string): boolean {
  return update?.type === "UpdateExpression" && update.operator === "++" && isIdentifierNamed(update.argument, name);
}

function isIdentifierNamed(node: Node, name: string): boolean {
  return node.type === "Identifier" && node.name === name;
}

function integerLiteral(node: Node | null | undefined): number | null {
  return node?.type === "Literal" && typeof node.value === "number" && Number.isInteger(node.value) ? node.value : null;
}

/** Recognizes an exact Array.reduce-style string accumulator. */
function isStringSeededReduce(node: ESTree.CallExpression): boolean {
  if (!isReduceCall(node)) return false;
  const [callback, initial] = node.arguments;
  if (
    (callback?.type !== "ArrowFunctionExpression" && callback?.type !== "FunctionExpression") ||
    callback.params[0]?.type !== "Identifier" ||
    initial === undefined ||
    initial.type === "SpreadElement" ||
    !isStringLiteralInit(initial)
  ) {
    return false;
  }
  return returnsConcatOnto(callback.body, callback.params[0].name);
}

function isReduceCall(node: ESTree.CallExpression): boolean {
  const callee = node.callee;
  return (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    callee.property.name === "reduce" &&
    node.arguments.length === 2 &&
    !(callee.object.type === "ArrayExpression" && callee.object.elements.length <= 8)
  );
}

/** True when a reducer body returns `accumulator + ...` directly or from its only statement. */
function returnsConcatOnto(body: Node | null, accumulator: string): boolean {
  if (body === null) return false;
  if (body.type !== "BlockStatement") return isConcatOntoTarget(body, accumulator);
  const statement = body.body.length === 1 ? body.body[0] : undefined;
  return statement?.type === "ReturnStatement" && statement.argument !== null && isConcatOntoTarget(statement.argument, accumulator);
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Prefer collecting string fragments over repeatedly accumulating a growing string inside a loop.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noStringConcatInLoop:
        "This loop repeatedly accumulates a growing string. Consider collecting fragments and joining once; preserve coercion timing and intermediate reads, and measure performance-sensitive paths.",
      noStringReduce:
        "This reduce repeatedly accumulates a growing string. Consider mapping fragments and joining once if coercion timing and intermediate observations are unchanged.",
    },
  },
  createOnce(context) {
    // Report each accumulator once per loop.
    let reported = new WeakMap<Node, Set<string>>();
    return {
      before() {
        reported = new WeakMap();
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (isStringSeededReduce(node)) context.report({ node, messageId: "noStringReduce" });
      },
      AssignmentExpression(node: ESTree.AssignmentExpression): void {
        // The LHS must be a plain variable reference.
        if (node.left.type !== "Identifier") return;
        // Accept both the compound `s += x` and the longhand `s = s + x`.
        const isAccumulation =
          node.operator === "+=" || (node.operator === "=" && isConcatOntoTarget(node.right, node.left.name));
        if (!isAccumulation) return;
        // Must occur inside a loop body, else it's a one-shot append.
        const loop = enclosingLoop(node);
        if (loop === null) return;
        if (immediatelyExitsLoop(node, loop)) return;
        if (isSmallStaticForLoop(loop)) return;

        const sourceCode = context.sourceCode;
        const variable = findVariable(sourceCode.getScope(node), node.left.name);
        // Conservative: can't resolve the declaration -> don't flag.
        if (variable === null) return;
        if (!isStringInitializedVariable(variable)) return;
        if (isDeclaredInsideLoop(variable, loop)) return;

        let seen = reported.get(loop);
        if (seen === undefined) {
          seen = new Set<string>();
          reported.set(loop, seen);
        }
        if (seen.has(node.left.name)) return;
        seen.add(node.left.name);

        const fix = literalStringLoopFix(sourceCode, node);
        context.report({ node, messageId: "noStringConcatInLoop", ...(fix !== null && { fix }) });
      },
    };
  },
});
