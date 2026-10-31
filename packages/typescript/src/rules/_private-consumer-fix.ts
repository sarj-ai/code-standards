/** @fileoverview _private-consumer-fix — preserve caller validity while editing erased contracts only. */
import { AST_NODE_TYPES, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import type { ScalarConsumerNode } from "./_private-scalar-consumer.js";
import { retainsNamedTypeUses } from "./_type-binding.js";

const UNSAFE = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter |
  ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess | ts.TypeFlags.Substitution;

/** Check each identifier caller against the original parameter contract. */
export function validConsumerFixCalls(node: ScalarConsumerNode, parameter: ts.ParameterDeclaration,
  sourceCode: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): boolean {
  // A newly valid call can make a previously required @ts-expect-error an error itself.
  if (sourceCode.getAllComments().some((comment) => /@ts-(?:expect-error|ignore|nocheck)\b/u.test(comment.value))) return false;
  const owner = node.type === AST_NODE_TYPES.FunctionDeclaration ? node : node.parent;
  if (owner.type !== AST_NODE_TYPES.FunctionDeclaration && owner.type !== AST_NODE_TYPES.VariableDeclarator) return false;
  const binding = sourceCode.getDeclaredVariables(owner).find((variable) => variable.defs.some((definition) =>
    definition.node === owner && (definition.type === "FunctionName" || definition.type === "Variable")));
  if (!binding) return false;
  const declaration = services.esTreeNodeToTSNodeMap.get(node);
  if ((!ts.isFunctionDeclaration(declaration) && !ts.isArrowFunction(declaration)) || parameter.parent !== declaration ||
    declaration.parameters.some((entry) => ts.isIdentifier(entry.name) && entry.name.text === "this")) return false;
  const selected = declaration.parameters.indexOf(parameter);
  if (selected < 0) return false;
  const checker = services.program.getTypeChecker();
  const originals = declaration.parameters.map((entry) => checker.getTypeAtLocation(entry));
  const original = originals[selected];
  if (!original) return false;
  const fields = new Set<string>();
  const collect = (type: ts.Type): void => {
    if (type.isUnionOrIntersection()) type.types.forEach(collect);
    else type.getProperties().forEach((property) => fields.add(property.name));
  };
  collect(original);
  const validArguments = (call: TSESTree.CallExpression): boolean => {
    if (declaration.parameters.length > 1) {
      const nativeCall = services.esTreeNodeToTSNodeMap.get(call);
      if (!ts.isCallExpression(nativeCall) || checker.getResolvedSignature(nativeCall)?.declaration !== declaration) return false;
    }
    return call.arguments.every((argument, index) => {
      const target = originals[index];
      const nativeArgument = services.esTreeNodeToTSNodeMap.get(argument);
      const type = checker.getTypeAtLocation(nativeArgument);
      return target !== undefined && (index === selected ? knownArgument(type, nativeArgument, fields, checker) : known(type)) &&
        checker.isTypeAssignableTo(type, target);
    });
  };
  let calls = 0;
  for (const reference of binding.references) {
    if (reference.isWrite()) {
      if (reference.init !== true) return false;
      continue;
    }
    const call = reference.identifier.parent;
    if (reference.isTypeReference || !reference.isReadOnly() || call.type !== AST_NODE_TYPES.CallExpression ||
      call.callee !== reference.identifier || call.optional || call.typeArguments || call.arguments.length !== declaration.parameters.length ||
      !call.arguments.every((argument) => argument.type === AST_NODE_TYPES.Identifier) || !validArguments(call)) return false;
    calls += 1;
  }
  return calls > 0;
}

function known(type: ts.Type): boolean {
  return (type.flags & UNSAFE) === 0 && (!type.isUnionOrIntersection() || type.types.every(known));
}

function knownArgument(type: ts.Type, argument: ts.Node, fields: ReadonlySet<string>, checker: ts.TypeChecker): boolean {
  if (!known(type)) return false;
  if (type.isUnionOrIntersection() && !type.types.every((part) => knownArgument(part, argument, fields, checker))) return false;
  return [...fields].every((name) => {
    const property = checker.getPropertyOfType(type, name);
    return !property || known(checker.getTypeOfSymbolAtLocation(property, argument));
  });
}

/** Removing a covered type must not make its local/import binding unused, even with simultaneous fixes. */
export function retainedConsumerTypeUses(sourceCode: Readonly<TSESLint.SourceCode>, removed: TSESTree.Node,
  covering: TSESTree.Node, candidateAnnotations: readonly TSESTree.Node[]): boolean {
  const enclosed = candidateAnnotations.some((annotation) =>
    annotation.range[0] <= Math.min(removed.range[0], covering.range[0]) &&
    Math.max(removed.range[1], covering.range[1]) <= annotation.range[1]);
  return enclosed && retainsNamedTypeUses(sourceCode, removed);
}

/** Retain every authored line terminator and every byte outside the edited annotation. */
function lineBreaks(text: string): string {
  return text.replace(/[^\r\n\u2028\u2029]/gu, "");
}

/** A deletion must not join two original terminators into a newly formed CRLF token. */
function sameLineTerminators(sourceCode: Readonly<TSESLint.SourceCode>, annotation: TSESTree.Node, text: string): boolean {
  // Include neighboring source characters so joins across either edit boundary are checked too.
  const start = Math.max(0, annotation.range[0] - 1);
  const before = sourceCode.text.slice(start, annotation.range[1] + 1);
  const after = sourceCode.text.slice(start, annotation.range[0]) + text + sourceCode.text.slice(annotation.range[1], annotation.range[1] + 1);
  const original = before.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  const rendered = after.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  return original.length === rendered.length && original.every((ending, index) => ending === rendered[index]);
}

export function coveringConsumerFix(sourceCode: Readonly<TSESLint.SourceCode>, annotation: TSESTree.Node,
  covering: TSESTree.Node): TSESLint.ReportFixFunction | null {
  if (sourceCode.getCommentsInside(annotation).length || covering.range[0] < annotation.range[0] || covering.range[1] > annotation.range[1]) return null;
  const text = lineBreaks(sourceCode.text.slice(annotation.range[0], covering.range[0])) + sourceCode.getText(covering) +
    lineBreaks(sourceCode.text.slice(covering.range[1], annotation.range[1]));
  return sameLineTerminators(sourceCode, annotation, text) ? (fixer) => fixer.replaceText(annotation, text) : null;
}

export function minimalConsumerFix(sourceCode: Readonly<TSESLint.SourceCode>, annotation: TSESTree.Node,
  removed: readonly { readonly start: number; readonly end: number }[]): TSESLint.ReportFixFunction | null {
  if (sourceCode.getCommentsInside(annotation).length || !removed.length) return null;
  let text = sourceCode.getText(annotation);
  let last = annotation.range[1];
  for (const member of [...removed].sort((left, right) => right.start - left.start)) {
    if (member.start < annotation.range[0] || member.end > last || member.start >= member.end) return null;
    let start = member.start - annotation.range[0];
    // A first inline member owns its horizontal leading trivia, never a terminator.
    if (/^\{[ \t]+$/u.test(text.slice(0, start))) start = 1;
    const end = member.end - annotation.range[0];
    text = text.slice(0, start) + lineBreaks(text.slice(start, end)) + text.slice(end);
    last = member.start;
  }
  return sameLineTerminators(sourceCode, annotation, text) ? (fixer) => fixer.replaceText(annotation, text) : null;
}
