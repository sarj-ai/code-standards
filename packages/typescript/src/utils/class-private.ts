/**
 * @fileoverview class-private — conservative shared analysis for converting a class member to ECMAScript `#private`.
 *
 * Port of the 18.x `_class-private.ts` helper on tsrs. The original resolves
 * symbols one node at a time while it walks; here `privateMemberFixPlan` does
 * every syntactic check and the walk, and `resolvePrivateMemberFixes` resolves
 * the symbols of many plans in one tsrs request (call it in `Program:exit`).
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { forEachAstChild, parentOf } from "./ast.js";
import type { TsrsFile, TsrsSymbol } from "./tsrs-services.js";
import { isUnusedPrivateBinding } from "./unused-private-binding.js";

export type PrivateConvertibleMember = ESTree.MethodDefinition | ESTree.PropertyDefinition | ESTree.AccessorProperty;
export type ClassNode = ESTree.Class;
export type PrivateMemberFix = (fixer: Fixer) => Fix[];

type ClassElement = ESTree.ClassElement;

function convertibleMember(member: ClassElement): PrivateConvertibleMember | null {
  return member.type === "MethodDefinition" || member.type === "PropertyDefinition" || member.type === "AccessorProperty" ? member : null;
}

function hasDecorators(node: { readonly decorators?: readonly unknown[] | null }): boolean {
  return (node.decorators?.length ?? 0) > 0;
}

function enclosingClass(node: Node): ClassNode | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "ClassDeclaration" || current.type === "ClassExpression") return current;
  }
  return null;
}

function memberName(member: PrivateConvertibleMember): string | null {
  return !member.computed && member.key.type === "Identifier" ? member.key.name : null;
}

/** The syntactic half of the original's `privateMemberFixes`; the symbol half waits for `resolvePrivateMemberFixes`. */
export interface PrivateMemberFixPlan {
  /** Member keys whose symbols the references must resolve to. */
  readonly keys: readonly Node[];
  /** In-class `this.name` accesses whose property must resolve to one of the keys' symbols. */
  readonly references: readonly ESTree.MemberExpression[];
  readonly fix: PrivateMemberFix;
}

/**
 * Return a plan only when the members can be renamed and every same-spelled
 * access is an in-class `this.name`. Reflection and string access make the
 * conversion report-only.
 */
export function privateMemberFixPlan(
  sourceCode: SourceCode,
  owner: ClassNode,
  members: readonly PrivateConvertibleMember[],
  removePrivateKeyword: boolean,
): PrivateMemberFixPlan | undefined {
  const first = members[0];
  const name = first === undefined ? null : memberName(first);
  if (first === undefined || name === null || members.some((member) => member.static || hasDecorators(member))) {
    return undefined;
  }
  if (owner.body.body.some((element) => {
    const member = convertibleMember(element);
    return member !== null && member.key.type === "PrivateIdentifier" && member.key.name === name;
  })) {
    return undefined;
  }
  const selectedMembers = new Set<PrivateConvertibleMember>(members);
  if (owner.body.body.some((element) => {
    const member = convertibleMember(element);
    return member !== null && memberName(member) === name && !selectedMembers.has(member);
  })) {
    return undefined;
  }

  const references: ESTree.MemberExpression[] = [];
  let unsafe = false;
  walk(sourceCode.ast, sourceCode.visitorKeys, (node) => {
    if (node.type === "Literal" && node.value === name) {
      // A string-key access through Reflect, Object helpers, or serialization
      // cannot be renamed without whole-program provenance.
      unsafe = true;
      return;
    }
    if (node.type !== "MemberExpression") return;
    const property = node.property as Node;
    const propertyName = property.type === "Identifier" || property.type === "PrivateIdentifier"
      ? property.name
      : property.type === "Literal" && typeof property.value === "string"
        ? property.value
        : null;
    if (propertyName !== name) return;
    if (node.computed || property.type !== "Identifier" || node.object.type !== "ThisExpression" || enclosingClass(node) !== owner) {
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
  const comments = sourceCode.getAllComments();
  for (const member of members) {
    const accessibility = removePrivateKeyword ? "private" : member.accessibility ?? undefined;
    if (accessibility === undefined) continue;
    const keyword = sourceCode.getTokens(member).find((token) => token.value === accessibility && token.range[0] < member.key.range[0]);
    const next = keyword === undefined ? undefined : sourceCode.getTokenAfter(keyword);
    if (keyword === undefined || next === null || next === undefined) return undefined;
    if (comments.some((comment) => comment.range[0] >= keyword.range[1] && comment.range[1] <= next.range[0])) return undefined;
    privateKeywordRanges.set(member, [keyword.range[0], next.range[0]]);
  }

  return {
    keys: members.map((member) => member.key),
    references,
    fix: (fixer) => {
      const fixes: Fix[] = [];
      for (const member of members) {
        fixes.push(fixer.replaceText(member.key, `#${name}`));
        const range = privateKeywordRanges.get(member);
        if (range !== undefined) fixes.push(fixer.removeRange([range[0], range[1]]));
      }
      for (const reference of references) fixes.push(fixer.replaceText(reference.property, `#${name}`));
      return fixes;
    },
  };
}

/**
 * The fix of each plan, or undefined when a member has no symbol or a
 * reference resolves elsewhere. One tsrs request for every plan.
 */
export function resolvePrivateMemberFixes(
  file: TsrsFile,
  plans: readonly (PrivateMemberFixPlan | undefined)[],
): (PrivateMemberFix | undefined)[] {
  const nodes = plans.flatMap((plan) => plan === undefined ? [] : [...plan.keys, ...plan.references.map((reference) => reference.property)]);
  const resolved = file.symbolsOf(nodes);
  let next = 0;
  return plans.map((plan) => {
    if (plan === undefined) return undefined;
    const take = (count: number): (TsrsSymbol | undefined)[] => resolved.slice(next, next += count);
    const symbols = take(plan.keys.length).filter((symbol) => symbol !== undefined);
    const propertySymbols = take(plan.references.length);
    if (symbols.length === 0) return undefined;
    return propertySymbols.every((symbol) => symbol !== undefined && symbols.includes(symbol)) ? plan.fix : undefined;
  });
}

function walk(node: Node, visitorKeys: SourceCode["visitorKeys"], visit: (current: Node) => void): void {
  visit(node);
  forEachAstChild(node, visitorKeys, (child) => walk(child, visitorKeys, visit));
}

export function convertibleMemberName(member: ClassElement): string | null {
  const convertible = convertibleMember(member);
  return convertible === null ? null : memberName(convertible);
}

/** Class definition itself must have no eager hooks that can observe its members. */
export function isUnobservedPrivateClass(sourceCode: SourceCode, owner: ClassNode, filename: string): boolean {
  return owner.type === "ClassDeclaration" && owner.id !== null &&
    (owner.superClass ?? null) === null && !hasDecorators(owner) &&
    !owner.body.body.some((member) => member.type === "StaticBlock" ||
      ("static" in member && member.static) || ("computed" in member && member.computed) ||
      ("decorators" in member && hasDecorators(member))) &&
    isUnusedPrivateBinding(sourceCode, owner, owner.id, filename);
}
