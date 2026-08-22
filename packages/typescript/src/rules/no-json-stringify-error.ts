/**
 * @fileoverview no-json-stringify-error — `JSON.stringify` on an Error yields `{}` — `message` and `stack` are non-enumerable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-json-stringify-error.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import type { Scope, SourceCode } from "@typescript-eslint/utils/ts-eslint";

type MessageIds = "noJsonStringifyError";
type Options = readonly [];

export const NO_JSON_STRINGIFY_ERROR_DOCUMENTATION = {
  summary: "Disallow `JSON.stringify` on an Error value; it yields `{}` because `message`/`stack` are non-enumerable.",
  rationale: "Native Error details are non-enumerable, so generic JSON serialization discards diagnostic information.",
  remediation: "Serialize explicit error fields or use an error-aware serializer.",
  category: "correctness",
  limitations: ["The rule uses local catch-binding and constructor provenance rather than type information."],
  examples: [
    { id: "explicit-error-message", title: "Serialize an enumerable error field", outcome: "no-match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err.message }); }" }], focusPath: "src/report.ts", expectedCount: 0, public: true },
    { id: "stringified-error", title: "Do not stringify an Error object", outcome: "match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err }); }" }], focusPath: "src/report.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Property names whose value is a plain string — the recommended escape hatch. */
const SAFE_STRING_PROPS: ReadonlySet<string> = new Set(["message", "stack", "name"]);

const PAYLOAD_PROPS: ReadonlySet<string> = new Set([
  "data",
  "status",
  "statuscode",
  "statustext",
  "code",
  "issues",
  "details",
  "body",
  "payload",
  "response",
  "info",
  "meta",
  "metadata",
  "context",
]);

const BUILTIN_ERROR_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "AggregateError",
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
]);

/** Whether a stable local binding is constructively proven to hold an Error. */
function identifierIsProvenError(
  identifier: TSESTree.Identifier,
  scope: Scope.Scope,
): boolean {
  if (isCatchBinding(scope, identifier.name)) return true;
  let current: Scope.Scope | null = scope;
  while (current !== null && !current.set.has(identifier.name)) {
    current = current.upper;
  }
  const variable = current?.set.get(identifier.name);
  if (variable === undefined || variable.defs.length !== 1) return false;
  const definition = variable.defs[0];
  if (definition?.type !== "Variable") return false;
  const initializer = definition.node.init;
  return (
    initializer?.type === "NewExpression" &&
    initializer.callee.type === "Identifier" &&
    BUILTIN_ERROR_CONSTRUCTORS.has(initializer.callee.name) &&
    variable.references.every(
      (reference) => !reference.isWrite() || reference.init === true,
    )
  );
}

function isCatchBinding(scope: Scope.Scope, name: string): boolean {
  let current: Scope.Scope | null = scope;
  while (current) {
    const variable = current.set.get(name);
    if (variable) {
      for (const def of variable.defs) {
        if (def.type === "CatchClause") {
          return true;
        }
      }
    }
    current = current.upper;
  }
  return false;
}

function positiveErrorSubject(
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  return instanceofErrorSubject(test) ?? typeGuardSubject(test);
}

/** Names of a user-defined type-guard predicate: `isErrorLike`, `isError`, `hasErrorShape`. */
const TYPE_GUARD_PATTERN = /^(is|has)[A-Z]/;

function instanceofErrorSubject(
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  if (
    test.type === "BinaryExpression" &&
    test.operator === "instanceof" &&
    test.right.type === "Identifier" &&
    test.right.name === "Error"
  ) {
    return test.left;
  }
  return null;
}

/** The narrowed subject `x` of a user-defined type-guard call `isFoo(x)`, or null. */
function typeGuardSubject(
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  const arg = test.type === "CallExpression" ? test.arguments[0] : undefined;
  if (
    test.type === "CallExpression" &&
    test.callee.type === "Identifier" &&
    TYPE_GUARD_PATTERN.test(test.callee.name) &&
    test.arguments.length === 1 &&
    arg !== undefined &&
    arg.type !== "SpreadElement"
  ) {
    return arg;
  }
  return null;
}

/**
 * True if an earlier guard `if (isErrorLike(arg)) return …` (or `instanceof Error`)
 * in an enclosing block narrows `argExpr` away from the error case before `node`,
 * so by the time `JSON.stringify(arg)` runs the value is the non-Error fallback.
 */
function isNarrowedByEarlyReturn(
  node: TSESTree.Node,
  argExpr: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const argText = sourceCode.getText(argExpr);
  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "BlockStatement" || current.type === "Program") {
      for (const stmt of current.body) {
        if (stmt.range[0] >= node.range[0]) {
          break;
        }
        if (
          stmt.type === "IfStatement" &&
          stmt.alternate === null &&
          branchTerminates(stmt.consequent)
        ) {
          const subject = positiveErrorSubject(stmt.test);
          if (subject && sourceCode.getText(subject) === argText) {
            return true;
          }
        }
      }
    }
    current = current.parent;
  }
  return false;
}

/** Whether a branch statement unconditionally exits (its last statement returns/throws). */
function branchTerminates(branch: TSESTree.Statement): boolean {
  const body = branch.type === "BlockStatement" ? branch.body : [branch];
  const last = body[body.length - 1];
  return (
    last !== undefined &&
    (last.type === "ReturnStatement" || last.type === "ThrowStatement")
  );
}

function isGuardedByInstanceofError(
  node: TSESTree.Node,
  argExpr: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const argText = sourceCode.getText(argExpr);
  const sameSubject = (subject: TSESTree.Expression): boolean =>
    sourceCode.getText(subject) === argText;

  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "ConditionalExpression") {
      const subject = positiveErrorSubject(current.test);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    } else if (current.type === "IfStatement") {
      const subject = positiveErrorSubject(current.test);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    }
    current = current.parent;
  }
  return false;
}

/** The subject `x` of a negated error-narrowing test — `!(x instanceof Error)` / `!isErrorLike(x)`. */
function negatedInstanceofErrorSubject(
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    return positiveErrorSubject(test.argument);
  }
  return null;
}

function nodeWithin(node: TSESTree.Node, container: TSESTree.Node | null): boolean {
  return (
    container !== null &&
    node.range[0] >= container.range[0] &&
    node.range[1] <= container.range[1]
  );
}

function isJsonStringify(callee: TSESTree.Expression): boolean {
  return (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    callee.object.name === "JSON" &&
    callee.property.type === "Identifier" &&
    callee.property.name === "stringify"
  );
}

/** Direct values serialized by a one-level object or array literal. */
function directLiteralValues(
  argument: TSESTree.CallExpressionArgument,
): readonly TSESTree.Expression[] {
  if (argument.type === "ObjectExpression") {
    return argument.properties.flatMap((property) => {
      if (property.type !== "Property" || property.computed) return [];
      const value = property.value;
      if (
        value.type === "AssignmentPattern" ||
        value.type === "ArrayPattern" ||
        value.type === "ObjectPattern" ||
        value.type === "TSEmptyBodyFunctionExpression"
      ) {
        return [];
      }
      return [value];
    });
  }
  if (argument.type === "ArrayExpression") {
    return argument.elements.flatMap((element) =>
      element !== null && element.type !== "SpreadElement" ? [element] : [],
    );
  }
  return argument.type === "SpreadElement" ? [] : [argument];
}

function expressionSuggestsError(
  expression: TSESTree.Expression,
  scope: Scope.Scope,
): boolean {
  if (expression.type === "Identifier") {
    return identifierIsProvenError(expression, scope);
  }
  if (
    expression.type === "NewExpression" &&
    expression.callee.type === "Identifier"
  ) {
    return BUILTIN_ERROR_CONSTRUCTORS.has(expression.callee.name);
  }
  return (
    expression.type === "MemberExpression" &&
    memberSuggestsError(expression, scope)
  );
}

/**
 * True if a member-expression argument denotes a property of a value proven
 * locally to be an Error, excluding the ordinary string/payload escape hatches.
 */
function memberSuggestsError(
  member: TSESTree.MemberExpression,
  scope: Scope.Scope,
): boolean {
  const propName =
    !member.computed && member.property.type === "Identifier" ? member.property.name : null;

  const base = member.object;
  const baseSuggestsError =
    base.type === "Identifier" &&
    identifierIsProvenError(base, scope);
  if (baseSuggestsError) {
    if (propName === null) {
      return true;
    }
    const lowered = propName.toLowerCase();
    return !SAFE_STRING_PROPS.has(lowered) && !PAYLOAD_PROPS.has(lowered);
  }

  return false;
}

export default createRule<Options, MessageIds>({
  name: "no-json-stringify-error",
  documentation: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `JSON.stringify` on an Error value; it yields `{}` because `message`/`stack` are non-enumerable.",
    },
    schema: [],
    messages: {
      noJsonStringifyError:
        "`JSON.stringify` on an Error yields `{}` because `message`/`stack` are non-enumerable. Log `err.message` / `err.stack`, or use a proper error serializer.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isJsonStringify(node.callee)) {
          return;
        }

        const firstArg = node.arguments[0];
        if (!firstArg) {
          return;
        }

        const scope = context.sourceCode.getScope(firstArg);
        const unsafeValue = directLiteralValues(firstArg).find(
          (value) =>
            expressionSuggestsError(value, scope) &&
            !isGuardedByInstanceofError(node, value, context.sourceCode) &&
            !isNarrowedByEarlyReturn(node, value, context.sourceCode),
        );
        if (unsafeValue === undefined) {
          return;
        }

        context.report({
          node,
          messageId: "noJsonStringifyError",
        });
      },
    };
  },
});
