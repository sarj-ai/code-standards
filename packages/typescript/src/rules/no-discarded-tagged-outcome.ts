/**
 * @fileoverview no-discarded-tagged-outcome — Consume a closed tagged success or failure outcome instead of discarding it.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableConstInitializer, stableFunctionDeclaration } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { typeBinding } from "../utils/type-binding.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

const NAME = "no-discarded-tagged-outcome";
type Callable = ESTree.Function | ESTree.ArrowFunctionExpression;
type RecordMembers = ESTree.TSTypeLiteral["members"];
interface OutcomeFacts { readonly tagged: boolean; readonly thenable: boolean; }
const OUTCOMES = new WeakMap<ESTree.Program, WeakMap<Node, OutcomeFacts>>();

function callable(input: Node, source: SourceCode, depth = 0): Callable | null {
  if (depth >= 12) return null;
  const node = unwrapExpression(input);
  if (node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression") return node;
  if (node.type !== "Identifier") return null;
  const declaration = stableFunctionDeclaration(source, node);
  if (declaration !== null) return declaration;
  const initializer = stableConstInitializer(source, node);
  return initializer === null ? null : callable(initializer.value, source, depth + 1);
}

function resolve(input: Node, source: SourceCode, depth = 0): Node | null {
  if (depth >= 16) return null;
  if (input.type !== "TSTypeReference") return input;
  if (input.typeName.type !== "Identifier") return null;
  const binding = typeBinding(source, input.typeName);
  const declaration = binding?.defs[0]?.node;
  if (binding?.defs.length !== 1) return input;
  if (declaration?.type === "TSTypeAliasDeclaration") return resolve(declaration.typeAnnotation, source, depth + 1);
  return declaration?.type === "TSInterfaceDeclaration" && declaration.extends.length === 0 ? declaration.body : input;
}

function record(input: Node, source: SourceCode): RecordMembers | null {
  const node = resolve(input, source);
  const members = node?.type === "TSTypeLiteral" ? node.members : node?.type === "TSInterfaceBody" ? node.body : null;
  return members !== null && members.every(member => member.type === "TSPropertySignature" || member.type === "TSMethodSignature") ? members : null;
}

function outcome(input: Node, source: SourceCode, awaited: boolean): boolean {
  let facts = OUTCOMES.get(source.ast);
  if (facts === undefined) {
    facts = new WeakMap();
    OUTCOMES.set(source.ast, facts);
  }
  let known = facts.get(input);
  if (known === undefined) {
    known = inspectOutcome(input, source);
    facts.set(input, known);
  }
  return known.tagged && (!awaited || !known.thenable);
}

function inspectOutcome(input: Node, source: SourceCode): OutcomeFacts {
  const type = resolve(input, source);
  if (type?.type !== "TSUnionType" || type.types.length !== 2) return { tagged: false, thenable: true };
  const members = type.types.map(member => record(member, source));
  if (members[0] === null || members[0] === undefined || members[1] === null || members[1] === undefined) return { tagged: false, thenable: true };
  const thenable = members.some(recordMembers => recordMembers?.some(member =>
    (member.type === "TSPropertySignature" || member.type === "TSMethodSignature") &&
    (member.computed || member.key.type === "Identifier" && member.key.name === "then" || member.key.type === "Literal" && member.key.value === "then")));
  const left = tags(members[0]), right = tags(members[1]);
  for (const [key, first] of left) {
    const second = right.get(key);
    if (["ok", "success"].includes(key) && typeof first === "boolean" && typeof second === "boolean" && first !== second) return { tagged: true, thenable };
    if (!["kind", "status", "type", "tag"].includes(key) || typeof first !== "string" || typeof second !== "string") continue;
    const pair = [first, second].sort().join(",");
    if (["error,ok", "error,success", "failure,success", "accepted,rejected"].includes(pair)) return { tagged: true, thenable };
  }
  return { tagged: false, thenable };
}

function tags(members: RecordMembers): Map<string, string | boolean> {
  const values = new Map<string, string | boolean>();
  for (const member of members) {
    if (member.type !== "TSPropertySignature" || member.optional || member.computed) continue;
    const name = member.key.type === "Identifier" ? member.key.name : member.key.type === "Literal" ? member.key.value : null;
    const type = member.typeAnnotation?.typeAnnotation;
    if (typeof name !== "string" || type?.type !== "TSLiteralType" || type.literal.type !== "Literal") continue;
    const value = type.literal.value;
    if (typeof value === "boolean" || typeof value === "string") values.set(name, value);
  }
  return values;
}

function returnType(fn: Callable, awaited: boolean, source: SourceCode): Node | null {
  let type: Node | null = fn.returnType?.typeAnnotation ?? null;
  if (type === null) return null;
  type = resolve(type, source) ?? type;
  if (type.type !== "TSTypeReference" || type.typeName.type !== "Identifier" || type.typeName.name !== "Promise") return fn.async ? null : type;
  if (!awaited || findVariable(source.getScope(type.typeName), "Promise")?.defs.length) return null;
  return type.typeArguments?.params.length === 1 ? type.typeArguments.params[0] ?? null : null;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: 'Consume a closed tagged success or failure outcome instead of discarding it.', url: docsUrl(NAME) },
    schema: [],
    messages: { noDiscardedTaggedOutcome: 'Consume a closed tagged success or failure outcome instead of discarding it.' },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text) ||
          hasIdentifierNamed(context.sourceCode, "eval") || hasIdentifierNamed(context.sourceCode, "Function")) return false;
        return undefined;
      },
      ExpressionStatement(statement: ESTree.ExpressionStatement) {
        let expression = unwrapExpression(statement.expression);
        if (expression.type === "UnaryExpression" && expression.operator === "void") expression = unwrapExpression(expression.argument);
        const awaited = expression.type === "AwaitExpression";
        if (expression.type === "AwaitExpression") expression = unwrapExpression(expression.argument);
        if (expression.type !== "CallExpression" || expression.optional) return;
        const fn = callable(expression.callee, context.sourceCode);
        const type = fn === null ? null : returnType(fn, awaited, context.sourceCode);
        if (type !== null && outcome(type, context.sourceCode, awaited))
          context.report({ node: expression, messageId: "noDiscardedTaggedOutcome" });
      },
    };
  },
});
