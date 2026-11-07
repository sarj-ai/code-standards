/** @fileoverview _literal-selector-fix — reuse authored operations for literal calls. */

import type { Fix, Fixer } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody, soleConstDeclarator } from "./_closed-module.js";

type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

/** Reuse already authored operations instead of an exclusively literal-called adapter. */
export function literalSelectorFix(
  sourceCode: SourceCode,
  parameter: Identifier,
): ((fixer: Fixer) => Fix[]) | null {
  if (
    sourceCode.ast.body.length !== 4 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const [first, second, declaration, statement] = sourceCode.ast.body;
  if (
    first?.type !== "FunctionDeclaration" || !isLiteralOperation(first) ||
    second?.type !== "FunctionDeclaration" || !isLiteralOperation(second) ||
    declaration?.type !== "VariableDeclaration" ||
    statement?.type !== "ExportNamedDeclaration" ||
    statement.declaration?.type !== "FunctionDeclaration"
  )
    return null;
  const binding = soleConstDeclarator(declaration);
  if (
    binding?.id.type !== "Identifier" ||
    isPresent(binding.id.typeAnnotation) ||
    binding.init?.type !== "ArrowFunctionExpression" ||
    binding.init.body.type !== "ConditionalExpression" ||
    !isSelector(binding.init, parameter)
  )
    return null;
  const branch = binding.init.body;
  const whenTrue = operation(sourceCode, branch.consequent, first, second);
  const whenFalse = operation(sourceCode, branch.alternate, first, second);
  if (whenTrue === null || whenFalse === null || whenTrue === whenFalse)
    return null;
  const calls = literalCallers(sourceCode, statement.declaration, binding);
  if (calls === null) return null;
  const gap = sourceCode.text.slice(declaration.range[1], statement.range[0]);
  if (!/^\s*$/u.test(gap)) return null;
  return (fixer) => [
    fixer.removeRange([declaration.range[0], statement.range[0]]),
    ...calls.map((call) =>
      fixer.replaceText(
        call,
        `${call.arguments[0]?.type === "Literal" && call.arguments[0].value === true ? whenTrue : whenFalse}()`,
      ),
    ),
  ];
}

function isLiteralOperation(node: ESTree.Function): boolean {
  const body = plainFunctionBody(node);
  if (node.id === null || node.params.length !== 0 || isPresent(node.returnType) || body?.length !== 1) return false;
  const returned = body[0];
  return (
    returned?.type === "ReturnStatement" &&
    returned.argument?.type === "Literal" &&
    typeof returned.argument.value === "string"
  );
}

function isSelector(
  node: ESTree.ArrowFunctionExpression,
  parameter: Identifier,
): boolean {
  const actual = node.params[0];
  return (
    actual?.type === "Identifier" &&
    actual.name === parameter.name &&
    !node.async &&
    !isPresent(node.typeParameters) &&
    !isPresent(node.returnType) &&
    node.params.length === 1 &&
    !actual.optional &&
    actual.typeAnnotation?.typeAnnotation.type ===
      "TSBooleanKeyword" &&
    node.body.type === "ConditionalExpression" &&
    node.body.test === parameter
  );
}

function operation(
  sourceCode: SourceCode,
  node: Node,
  first: ESTree.Function,
  second: ESTree.Function,
): string | null {
  if (
    node.type !== "CallExpression" ||
    node.optional ||
    node.callee.type !== "Identifier" ||
    node.arguments.length !== 0 ||
    isPresent(node.typeArguments)
  )
    return null;
  const variable = findVariable(
    sourceCode.getScope(node),
    node.callee.name,
  );
  const target = variable?.defs[0]?.node;
  return variable?.defs.length === 1 && (target === first || target === second)
    ? sourceCode.getText(node.callee)
    : null;
}

function literalCallers(
  sourceCode: SourceCode,
  owner: ESTree.Function,
  binding: ESTree.VariableDeclarator,
): ESTree.CallExpression[] | null {
  const body = plainFunctionBody(owner);
  const returned = body?.length === 1 ? body[0] : undefined;
  if (
    owner.params.length !== 0 ||
    owner.returnType?.typeAnnotation.type !== "TSArrayType" ||
    owner.returnType.typeAnnotation.elementType.type !== "TSStringKeyword" ||
    returned?.type !== "ReturnStatement" ||
    returned.argument?.type !== "ArrayExpression"
  )
    return null;
  const calls: ESTree.CallExpression[] = [];
  const choices = new Set<boolean>();
  for (const item of returned.argument.elements) {
    if (item?.type !== "CallExpression") return null;
    const choice = selectorChoice(sourceCode, item, binding);
    if (choice === null) return null;
    calls.push(item);
    choices.add(choice);
  }
  return choices.size === 2 ? calls : null;
}

/** The boolean a direct `selector(true)` call passes, when `selector` is `binding`. */
function selectorChoice(sourceCode: SourceCode, call: ESTree.CallExpression, binding: ESTree.VariableDeclarator): boolean | null {
  const [argument] = call.arguments;
  if (
    call.optional ||
    call.callee.type !== "Identifier" ||
    isPresent(call.typeArguments) ||
    call.arguments.length !== 1 ||
    argument?.type !== "Literal" ||
    typeof argument.value !== "boolean"
  )
    return null;
  const variable = findVariable(sourceCode.getScope(call), call.callee.name);
  return variable?.defs.length === 1 && variable.defs[0]?.node === binding ? argument.value : null;
}
