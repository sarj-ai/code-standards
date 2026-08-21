/**
 * @fileoverview _class-private — conservative shared analysis for converting a class member to ECMAScript `#private`.
 */

import {
  AST_NODE_TYPES,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import type * as ts from "typescript";

export type PrivateConvertibleMember =
  | TSESTree.MethodDefinition
  | TSESTree.PropertyDefinition
  | TSESTree.AccessorProperty;

function symbolAt(
  services: ParserServicesWithTypeInformation,
  checker: ts.TypeChecker,
  node: TSESTree.Node,
): ts.Symbol | undefined {
  return checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(node));
}

function sameSymbol(left: ts.Symbol | undefined, right: ts.Symbol | undefined): boolean {
  return left !== undefined && right !== undefined && left === right;
}

function enclosingClass(node: TSESTree.Node): TSESTree.ClassDeclaration | TSESTree.ClassExpression | null {
  let current: TSESTree.Node | undefined = node.parent;
  while (current !== undefined) {
    if (current.type === AST_NODE_TYPES.ClassDeclaration || current.type === AST_NODE_TYPES.ClassExpression) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

function memberName(member: PrivateConvertibleMember): string | null {
  return !member.computed && member.key.type === AST_NODE_TYPES.Identifier ? member.key.name : null;
}

/**
 * Return one atomic fix only when every reference resolves to the exact member
 * symbol and is an in-class `this.name` access. Reflection and string access
 * intentionally make the conversion report-only.
 */
export function privateMemberFixes(
  context: Readonly<TSESLint.RuleContext<string, readonly unknown[]>>,
  services: ParserServicesWithTypeInformation,
  owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
  members: readonly PrivateConvertibleMember[],
  removePrivateKeyword: boolean,
): ((fixer: TSESLint.RuleFixer) => readonly TSESLint.RuleFix[]) | undefined {
  const first = members[0];
  const name = first === undefined ? null : memberName(first);
  if (first === undefined || name === null || members.some((member) => member.static || member.decorators.length > 0)) {
    return undefined;
  }
  if (owner.body.body.some((member) => {
    if (
      member.type !== AST_NODE_TYPES.MethodDefinition &&
      member.type !== AST_NODE_TYPES.PropertyDefinition &&
      member.type !== AST_NODE_TYPES.AccessorProperty
    ) return false;
    return member.key.type === AST_NODE_TYPES.PrivateIdentifier && member.key.name === name;
  })) return undefined;
  const selectedMembers = new Set<PrivateConvertibleMember>(members);
  if (owner.body.body.some((member) => {
    if (
      member.type !== AST_NODE_TYPES.MethodDefinition &&
      member.type !== AST_NODE_TYPES.PropertyDefinition &&
      member.type !== AST_NODE_TYPES.AccessorProperty
    ) return false;
    return memberName(member) === name && !selectedMembers.has(member);
  })) return undefined;

  const checker = services.program.getTypeChecker();
  const symbols = members.map((member) => symbolAt(services, checker, member.key)).filter(
    (symbol): symbol is ts.Symbol => symbol !== undefined,
  );
  if (symbols.length === 0) return undefined;
  const references: TSESTree.MemberExpression[] = [];
  let unsafe = false;
  walk(context.sourceCode.ast, context.sourceCode.visitorKeys, (node) => {
    if (node.type === AST_NODE_TYPES.Literal && node.value === name) {
      // A string-key access through Reflect, Object helpers, or serialization
      // cannot be renamed without whole-program provenance.
      unsafe = true;
      return;
    }
    if (node.type !== AST_NODE_TYPES.MemberExpression) return;
    const propertyName = node.property.type === AST_NODE_TYPES.Identifier || node.property.type === AST_NODE_TYPES.PrivateIdentifier
      ? node.property.name
      : node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
        ? node.property.value
        : null;
    if (propertyName !== name) return;
    const propertySymbol = symbolAt(services, checker, node.property);
    if (
      node.computed ||
      node.property.type !== AST_NODE_TYPES.Identifier ||
      node.object.type !== AST_NODE_TYPES.ThisExpression ||
      enclosingClass(node) !== owner ||
      !symbols.some((symbol) => sameSymbol(symbol, propertySymbol))
    ) {
      // Same-spelled access outside the class is conservatively considered a
      // possible external use even when the compiler withholds a symbol after
      // diagnosing illegal access to a TypeScript-private member.
      unsafe = true;
      return;
    }
    references.push(node);
  });
  if (unsafe) return undefined;

  const privateKeywordRanges = new Map<PrivateConvertibleMember, readonly [number, number]>();
  if (removePrivateKeyword) {
    const comments = context.sourceCode.getAllComments();
    for (const member of members) {
      const keyword = context.sourceCode.getTokens(member).find((token) => token.value === "private");
      const next = keyword === undefined ? undefined : context.sourceCode.getTokenAfter(keyword);
      if (keyword === undefined || next === null || next === undefined) return undefined;
      if (comments.some((comment) => comment.range[0] >= keyword.range[1] && comment.range[1] <= next.range[0])) {
        return undefined;
      }
      privateKeywordRanges.set(member, [keyword.range[0], next.range[0]]);
    }
  }

  return (fixer) => {
    const fixes: TSESLint.RuleFix[] = [];
    for (const member of members) {
      fixes.push(fixer.replaceText(member.key, `#${name}`));
      if (removePrivateKeyword) {
        const range = privateKeywordRanges.get(member);
        if (range === undefined) return [];
        fixes.push(fixer.removeRange(range));
      }
    }
    for (const reference of references) fixes.push(fixer.replaceText(reference.property, `#${name}`));
    return fixes;
  };
}

function walk(
  node: TSESTree.Node,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
  visit: (current: TSESTree.Node) => void,
): void {
  visit(node);
  for (const key of visitorKeys[node.type] ?? []) {
    const child = (node as unknown as Record<string, unknown>)[key];
    if (Array.isArray(child)) {
      for (const item of child) {
        if (typeof item === "object" && item !== null && "type" in item) {
          walk(item as TSESTree.Node, visitorKeys, visit);
        }
      }
    } else if (typeof child === "object" && child !== null && "type" in child) {
      walk(child as TSESTree.Node, visitorKeys, visit);
    }
  }
}

export function convertibleMemberName(member: TSESTree.ClassElement): string | null {
  if (
    member.type !== AST_NODE_TYPES.MethodDefinition &&
    member.type !== AST_NODE_TYPES.PropertyDefinition &&
    member.type !== AST_NODE_TYPES.AccessorProperty
  ) return null;
  return memberName(member);
}
