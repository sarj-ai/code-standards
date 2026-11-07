/**
 * @fileoverview no-mutating-input-with-result — return replacement values instead of writing input fields.
 *
 * Port of the 18.x `no-mutating-input-with-result` rule. The rule is untyped, so the port
 * covers all of it.
 *
 * The original compares `typeArguments` and `typeParameters` to `undefined`; Oxlint passes `null`
 * for absent fields, so under Oxlint the original never resolves a named interface, type alias or
 * class contract (only inline type literals). The port accepts both, which matches ESLint.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { forEachOwnAstChild, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "no-mutating-input-with-result";

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

function command(annotation: ESTree.TSType): boolean {
  if (annotation.type === "TSVoidKeyword" || annotation.type === "TSUndefinedKeyword" || annotation.type === "TSNeverKeyword") return true;
  if (annotation.type === "TSTypeReference" && annotation.typeName.type === "Identifier" && annotation.typeName.name === "Promise" && annotation.typeArguments?.params.length === 1) {
    const result = annotation.typeArguments.params[0];
    return result !== undefined && command(result);
  }
  return false;
}

function fields(annotation: ESTree.TSType, sourceCode: SourceCode): ReadonlySet<string> {
  const names = new Set<string>();
  for (const member of membersOf(annotation, sourceCode)) {
    const name = mutableField(member);
    if (name !== null) names.add(name);
  }
  return names;
}

function membersOf(annotation: ESTree.TSType, sourceCode: SourceCode): readonly Node[] {
  if (annotation.type === "TSTypeLiteral") return annotation.members;
  if (annotation.type !== "TSTypeReference" || annotation.typeName.type !== "Identifier" || isPresent(annotation.typeArguments)) return [];
  const variable = findVariable(sourceCode.getScope(annotation.typeName), annotation.typeName.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0]?.node : undefined;
  return definition === undefined ? [] : declaredMembers(definition);
}

/** The members of a non-generic, non-inheriting interface, type literal alias or class. */
function declaredMembers(definition: Node): readonly Node[] {
  switch (definition.type) {
    case "TSInterfaceDeclaration":
      return definition.extends.length === 0 && !isPresent(definition.typeParameters) ? definition.body.body : [];
    case "TSTypeAliasDeclaration":
      return !isPresent(definition.typeParameters) && definition.typeAnnotation.type === "TSTypeLiteral" ? definition.typeAnnotation.members : [];
    case "ClassDeclaration":
      return !isPresent(definition.superClass) && !isPresent(definition.typeParameters) && definition.decorators.length === 0 ? definition.body.body : [];
    default: return [];
  }
}

function mutableField(member: Node): string | null {
  if ((member.type !== "TSPropertySignature" && member.type !== "PropertyDefinition") || member.readonly || member.computed) return null;
  if (member.type === "PropertyDefinition" && (member.static || member.accessibility === "private" || member.accessibility === "protected")) return null;
  if (member.key.type === "Identifier") return member.key.name;
  return member.key.type === "Literal" && (typeof member.key.value === "string" || typeof member.key.value === "number") ? String(member.key.value) : null;
}

function walkBody(node: Node, visit: (node: Node) => void): void {
  if (node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression" ||
    node.type === "ClassDeclaration" || node.type === "ClassExpression") return;
  visit(node);
  if (node.type === "BlockStatement") {
    for (const statement of node.body) {
      walkBody(statement, visit);
      if (statement.type === "ReturnStatement" || statement.type === "ThrowStatement") break;
    }
    return;
  }
  const selected = selectedChildren(node);
  if (selected !== null) {
    for (const child of selected) walkBody(child, visit);
    return;
  }
  forEachOwnAstChild(node, child => walkBody(child, visit), key => key !== "typeAnnotation" && key !== "returnType");
}

function selectedChildren(node: Node): readonly Node[] | null {
  if (node.type === "IfStatement" && node.test.type === "Literal") {
    const branch = node.test.value ? node.consequent : node.alternate;
    return branch === null ? [node.test] : [node.test, branch];
  }
  if (node.type === "LogicalExpression" && node.left.type === "Literal") {
    return shortCircuits(node.operator, node.left.value) ? [node.left] : [node.left, node.right];
  }
  if (node.type === "ConditionalExpression" && node.test.type === "Literal") return [node.test, node.test.value ? node.consequent : node.alternate];
  return null;
}

/** Whether a literal left operand makes `operator` skip its right operand. */
function shortCircuits(operator: ESTree.LogicalExpression["operator"], value: unknown): boolean {
  return operator === "&&" && !value || operator === "||" && !!value || operator === "??" && value !== null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Return replacement object values instead of writing input fields in result-returning functions.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { inputWrite: "This result-returning function writes input `{{name}}`; return a replacement value or declare an in-place command returning void." },
  },
  createOnce(context) {
    function inspect(node: FunctionNode): void {
      const sourceCode = context.sourceCode;
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined || command(annotation) || !isPresent(node.body)) return;
      const inputs = new Map<TsVariable, ReadonlySet<string>>();
      for (const parameter of node.params as readonly Node[]) {
        if (parameter.type !== "Identifier" || !isPresent(parameter.typeAnnotation)) continue;
        const variable = findVariable(sourceCode.getScope(parameter), parameter.name);
        if (variable === null || variable.references.some(reference => reference.isWrite())) continue;
        const names = fields(parameter.typeAnnotation.typeAnnotation, sourceCode);
        if (names.size > 0) inputs.set(variable, names);
      }
      if (inputs.size === 0) return;
      let returned = node.body.type !== "BlockStatement";
      const writes: { readonly node: ESTree.MemberExpression; readonly name: string }[] = [];
      walkBody(node.body, current => {
        if (current.type === "ReturnStatement" && current.argument !== null) returned = true;
        const candidate = current.type === "AssignmentExpression" ? current.left :
          current.type === "UpdateExpression" || current.type === "UnaryExpression" && current.operator === "delete" ? current.argument : null;
        if (candidate === null) return;
        const target = unwrapExpression(candidate);
        if (target.type !== "MemberExpression" || target.object.type !== "Identifier") return;
        const variable = findVariable(sourceCode.getScope(target.object), target.object.name);
        const property = getPropertyName(target);
        if (variable !== null && property !== null && inputs.get(variable)?.has(property)) writes.push({ node: target, name: target.object.name });
      });
      const first = writes[0];
      if (returned && first !== undefined) context.report({ node: first.node, messageId: "inputWrite", data: { name: first.name } });
    }
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      FunctionDeclaration: inspect,
      FunctionExpression: inspect,
      ArrowFunctionExpression: inspect,
    };
  },
});
