/**
 * @fileoverview no-json-stringify-error — `JSON.stringify` on an Error yields `{}` — `message` and `stack` are non-enumerable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-json-stringify-error.test.ts
 */

import { ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import type { Scope, SourceCode } from "@typescript-eslint/utils/ts-eslint";

type MessageIds = "noJsonStringifyError";
type Options = readonly [];

export const NO_JSON_STRINGIFY_ERROR_DOCUMENTATION = {
  summary: "Avoid generic JSON serialization that can omit native Error details.",
  rationale: "Native Error details are non-enumerable, so generic JSON serialization discards diagnostic information.",
  remediation: "Serialize explicit error fields or use an error-aware serializer.",
  category: "correctness",
  limitations: ["The rule uses stable local catch bindings and unshadowed built-in constructors, not runtime type information. Custom replacers are left to their serializer contract; a catch value is not guaranteed to be an Error."],
  examples: [
    { id: "explicit-error-message", title: "Narrow an unknown catch value before selecting fields", outcome: "no-match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err instanceof Error ? err.message : String(err) }); }" }], focusPath: "src/report.ts", expectedCount: 0, public: true },
    { id: "stringified-error", title: "Do not stringify an Error object", outcome: "match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err }); }" }], focusPath: "src/report.ts", expectedCount: 1, public: true },
    { id: "shadowed-error-binding", scenarioId: "binding-provenance", title: "Keep native binding provenance", outcome: "match", files: [{ path: "src/error.ts", source: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;{const err=new Error(\"lost\");return JSON.stringify(err);}}}\nconsole.log(probe());" }], focusPath: "src/error.ts", expectedCount: 1, public: true },
    { id: "escaped-fallback-binding", scenarioId: "binding-provenance", title: "Keep native binding provenance", outcome: "no-match", files: [{ path: "src/error.ts", source: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;return JSON.stringify(\\u0065rr);}}\nconsole.log(probe());" }], focusPath: "src/error.ts", expectedCount: 0, public: true },
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
  sourceCode: Readonly<SourceCode>,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length !== 1 || variable.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const definition = variable.defs[0];
  if (definition?.type === "CatchClause") return true;
  if (definition?.type !== "Variable") return false;
  const initializer = definition.node.init;
  return (
    initializer?.type === "NewExpression" &&
    initializer.callee.type === "Identifier" &&
    BUILTIN_ERROR_CONSTRUCTORS.has(initializer.callee.name) &&
    isGlobalIdentifier(initializer.callee.name, sourceCode.getScope(initializer.callee))
  );
}

function isGlobalIdentifier(name: string, scope: Scope.Scope): boolean {
  const binding = ASTUtils.findVariable(scope, name);
  return binding === null || binding.defs.length === 0;
}

function positiveErrorSubject(
  test: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
  return instanceofErrorSubject(test, sourceCode) ?? typeGuardSubject(test);
}

/** Names of a user-defined type-guard predicate: `isErrorLike`, `isError`, `hasErrorShape`. */
const TYPE_GUARD_PATTERN = /^(is|has)[A-Z]/;

function instanceofErrorSubject(
  test: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
  if (
    test.type === "BinaryExpression" &&
    test.operator === "instanceof" &&
    test.right.type === "Identifier" &&
    test.right.name === "Error" &&
    isGlobalIdentifier("Error", sourceCode.getScope(test.right))
  ) {
    return test.left;
  }
  return null;
}

/** The narrowed subject `x` of a user-defined type-guard call `isFoo(x)`, or null. */
function typeGuardSubject(
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  const unwrappedTestCallee = test.type === "CallExpression" || test.type === "NewExpression" ? unwrapExpression(test.callee) : null;
  const arg = test.type === "CallExpression" ? test.arguments[0] : undefined;
  if (
    test.type === "CallExpression" &&
    unwrappedTestCallee?.type === "Identifier" &&
    TYPE_GUARD_PATTERN.test(unwrappedTestCallee.name) &&
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
  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "BlockStatement" || current.type === "Program") {
      if (hasEarlierErrorGuard(current.body, node, argExpr, sourceCode)) return true;
    }
    current = current.parent;
  }
  return false;
}

function isGuardedByInstanceofError(
  node: TSESTree.Node,
  argExpr: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const sameSubject = (subject: TSESTree.Expression): boolean =>
    sameSubjectBinding(subject, argExpr, sourceCode);

  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "ConditionalExpression") {
      const subject = positiveErrorSubject(current.test, sourceCode);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test, sourceCode);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    } else if (current.type === "IfStatement") {
      const subject = positiveErrorSubject(current.test, sourceCode);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test, sourceCode);
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
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    return positiveErrorSubject(test.argument, sourceCode);
  }
  return null;
}

function sameSubjectBinding(
  subject: TSESTree.Expression,
  value: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const left = unwrapExpression(subject);
  const right = unwrapExpression(value);
  if (left.type === "Identifier" && right.type === "Identifier") {
    const binding = ASTUtils.findVariable(sourceCode.getScope(left), left.name);
    return binding !== null && binding === ASTUtils.findVariable(sourceCode.getScope(right), right.name);
  }
  return sourceCode.getText(subject) === sourceCode.getText(value);
}

function nodeWithin(node: TSESTree.Node, container: TSESTree.Node | null): boolean {
  return (
    container !== null &&
    node.range[0] >= container.range[0] &&
    node.range[1] <= container.range[1]
  );
}

function isJsonStringify(callee: TSESTree.Expression): boolean {
  if (callee.type !== "MemberExpression") return false;
  const receiver = unwrapExpression(callee.object);
  return (
    callee.type === "MemberExpression" &&
    receiver.type === "Identifier" &&
    receiver.name === "JSON" &&
    ASTUtils.getPropertyName(callee) === "stringify"
  );
}

/** Direct values serialized by a one-level object or array literal. */
function directLiteralValues(
  argument: TSESTree.CallExpressionArgument,
): readonly TSESTree.Expression[] {
  argument = unwrapExpression(argument);
  if (argument.type === "ObjectExpression") {
    return argument.properties.flatMap((property) => {
      if (property.type !== "Property" || ASTUtils.getPropertyName(property) === null) return [];
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
  sourceCode: Readonly<SourceCode>,
): boolean {
  expression = unwrapExpression(expression);
  const unwrappedExpressionCallee = expression.type === "CallExpression" || expression.type === "NewExpression" ? unwrapExpression(expression.callee) : null;
  if (expression.type === "Identifier") {
    return identifierIsProvenError(expression, sourceCode);
  }
  if (
    expression.type === "NewExpression" &&
    unwrappedExpressionCallee?.type === "Identifier"
  ) {
    return BUILTIN_ERROR_CONSTRUCTORS.has(unwrappedExpressionCallee.name) && isGlobalIdentifier(unwrappedExpressionCallee.name, sourceCode.getScope(unwrappedExpressionCallee));
  }
  return (
    expression.type === "MemberExpression" &&
    memberSuggestsError(expression, sourceCode)
  );
}

/**
 * True if a member-expression argument denotes a property of a value proven
 * locally to be an Error, excluding the ordinary string/payload escape hatches.
 */
function memberSuggestsError(
  member: TSESTree.MemberExpression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const propName = ASTUtils.getPropertyName(member);

  const base = member.object;
  const baseSuggestsError =
    base.type === "Identifier" &&
    identifierIsProvenError(base, sourceCode);
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
        "Avoid generic JSON serialization that can omit native Error details.",
    },
    schema: [],
    messages: {
      noJsonStringifyError:
        "Generic `JSON.stringify` can omit non-enumerable Error details such as message and stack. Serialize explicit fields or use an error-aware serializer.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (!isJsonStringify(unwrappedNodeCallee)) {
          return;
        }

        const firstArg = node.arguments[0];
        if (!firstArg) {
          return;
        }

        const scope = context.sourceCode.getScope(firstArg);
        if (!isGlobalIdentifier("JSON", scope)) return;
        const replacer = node.arguments[1] === undefined ? undefined : unwrapExpression(node.arguments[1]);
        if (replacer !== undefined && !(replacer.type === "Literal" && replacer.value === null) && !(replacer.type === "Identifier" && replacer.name === "undefined" && isGlobalIdentifier("undefined", scope))) return;
        const unsafeValue = directLiteralValues(firstArg).find(
          (value) =>
            expressionSuggestsError(value, context.sourceCode) &&
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

function hasEarlierErrorGuard(statements: readonly TSESTree.Statement[], node: TSESTree.Node, argExpr: TSESTree.Expression, sourceCode: Readonly<SourceCode>): boolean {
  for (const stmt of statements) {
    if (stmt.range[0] >= node.range[0]) {
      break;
    }
    if (
      stmt.type === "IfStatement" &&
      stmt.alternate === null &&
      branchTerminates(stmt.consequent)
    ) {
      const subject = positiveErrorSubject(stmt.test, sourceCode);
      if (subject && sameSubjectBinding(subject, argExpr, sourceCode)) {
        return true;
      }
    }
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
