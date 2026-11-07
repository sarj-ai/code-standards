/**
 * @fileoverview private-consumer-fix — preserve caller validity while editing erased contracts only.
 */

import type { FixFn } from "@oxlint/plugins";
import type { Node as TsAstNode, ParameterDeclaration } from "tsrs/ast";
import type { Type } from "tsrs/sync";

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { parentOf } from "./ast.js";
import type { NativeTypes } from "./checked-native-source.js";
import type { ScalarConsumerNode } from "./private-scalar-consumer.js";
import { retainsNamedTypeUses } from "./type-binding.js";

function partsOf(type: Type): readonly Type[] | undefined {
  return type.isUnionType() || type.isIntersectionType() ? type.getTypes() : undefined;
}

/** Check each identifier caller against the original parameter contract. */
export function validConsumerFixCalls(native: NativeTypes, node: ScalarConsumerNode, parameter: ParameterDeclaration, sourceCode: SourceCode): boolean {
  // A newly valid call can make a previously required @ts-expect-error an error itself.
  if (sourceCode.getAllComments().some((comment) => /@ts-(?:expect-error|ignore|nocheck)\b/u.test(comment.value))) return false;
  const owner = node.type === "FunctionDeclaration" ? node : parentOf(node);
  if (owner?.type !== "FunctionDeclaration" && owner?.type !== "VariableDeclarator") return false;
  const binding = sourceCode.getDeclaredVariables(owner).find((variable) => variable.defs.some((definition) =>
    definition.node === owner && (definition.type === "FunctionName" || definition.type === "Variable"))) as TsVariable | undefined;
  if (!binding) return false;
  const { ast, checker } = native;
  const declaration = native.node(node);
  if (!declaration || (!ast.isFunctionDeclaration(declaration) && !ast.isArrowFunction(declaration)) || parameter.parent !== declaration ||
    declaration.parameters.some((entry) => ast.isIdentifier(entry.name) && entry.name.text === "this")) return false;
  const selected = declaration.parameters.indexOf(parameter);
  if (selected < 0) return false;
  const originals = declaration.parameters.map((entry) => checker.getTypeAtLocation(entry));
  const original = originals[selected];
  if (!original) return false;
  const fields = new Set<string>();
  const collect = (type: Type): void => {
    const parts = partsOf(type);
    if (parts) parts.forEach(collect);
    else type.getProperties().forEach((property) => fields.add(property.name));
  };
  collect(original);
  const validArguments = (call: ESTree.CallExpression): boolean => {
    if (declaration.parameters.length > 1) {
      const nativeCall = native.node(call);
      if (!nativeCall || !ast.isCallExpression(nativeCall)) return false;
      const resolved = checker.getResolvedSignature(nativeCall).declaration;
      if (resolved === undefined || resolved.resolve(native.program.getProject()) !== declaration) return false;
    }
    return call.arguments.every((argument, index) => {
      const target = originals[index];
      const nativeArgument = native.node(argument);
      if (nativeArgument === undefined) return false;
      const type = checker.getTypeAtLocation(nativeArgument);
      return target !== undefined && (index === selected ? knownArgument(native, type, nativeArgument, fields) : known(native, type)) &&
        checker.isTypeAssignableTo(type, target);
    });
  };
  let calls = 0;
  for (const reference of binding.references) {
    if (reference.isWrite()) {
      if (reference.init !== true) return false;
      continue;
    }
    const call = parentOf(reference.identifier);
    if (reference.isTypeReference || !reference.isReadOnly() || call?.type !== "CallExpression" ||
      call.callee !== reference.identifier || call.optional || call.typeArguments || call.arguments.length !== declaration.parameters.length ||
      !call.arguments.every((argument) => argument.type === "Identifier") || !validArguments(call)) return false;
    calls += 1;
  }
  return calls > 0;
}

function known(native: NativeTypes, type: Type): boolean {
  const parts = partsOf(type);
  return (type.flags & unsafeFlags(native)) === 0 && (!parts || parts.every((part) => known(native, part)));
}

function unsafeFlags(native: NativeTypes): number {
  const f = native.sync.TypeFlags;
  return f.Any | f.Unknown | f.Never | f.TypeParameter | f.Conditional | f.IndexedAccess | f.Substitution;
}

function knownArgument(native: NativeTypes, type: Type, argument: TsAstNode, fields: ReadonlySet<string>): boolean {
  if (!known(native, type)) return false;
  const parts = partsOf(type);
  if (parts && !parts.every((part) => knownArgument(native, part, argument, fields))) return false;
  return [...fields].every((name) => {
    const property = native.checker.getPropertyOfType(type, name);
    return !property || known(native, native.checker.getTypeOfSymbolAtLocation(property, argument));
  });
}

/** Removing a covered type must not make its local/import binding unused, even with simultaneous fixes. */
export function retainedConsumerTypeUses(sourceCode: SourceCode, removed: Node, covering: Node, candidateAnnotations: readonly Node[]): boolean {
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
function sameLineTerminators(sourceCode: SourceCode, annotation: Node, text: string): boolean {
  // Include neighboring source characters so joins across either edit boundary are checked too.
  const start = Math.max(0, annotation.range[0] - 1);
  const before = sourceCode.text.slice(start, annotation.range[1] + 1);
  const after = sourceCode.text.slice(start, annotation.range[0]) + text + sourceCode.text.slice(annotation.range[1], annotation.range[1] + 1);
  const original = before.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  const rendered = after.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  return original.length === rendered.length && original.every((ending, index) => ending === rendered[index]);
}

export function coveringConsumerFix(sourceCode: SourceCode, annotation: Node, covering: Node): FixFn | null {
  if (sourceCode.getCommentsInside(annotation).length || covering.range[0] < annotation.range[0] || covering.range[1] > annotation.range[1]) return null;
  const text = lineBreaks(sourceCode.text.slice(annotation.range[0], covering.range[0])) + sourceCode.getText(covering) +
    lineBreaks(sourceCode.text.slice(covering.range[1], annotation.range[1]));
  return sameLineTerminators(sourceCode, annotation, text) ? (fixer) => fixer.replaceText(annotation, text) : null;
}

export function minimalConsumerFix(sourceCode: SourceCode, annotation: Node, removed: readonly { readonly start: number; readonly end: number }[]): FixFn | null {
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
