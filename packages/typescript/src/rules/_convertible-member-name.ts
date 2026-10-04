/** @fileoverview _convertible-member-name — identify native TypeScript private class members. */

import type { ESTree } from "@oxlint/plugins";
/** Shared class-member shapes for report-only privacy rules. */
export type PrivateConvertibleMember =
  | ESTree.MethodDefinition
  | ESTree.PropertyDefinition
  | ESTree.AccessorProperty;

export function convertibleMemberName(
  member: ESTree.ClassElement,
): string | null {
  if (
    member.type !== "MethodDefinition" &&
    member.type !== "PropertyDefinition" &&
    member.type !== "AccessorProperty"
  )
    return null;
  return !member.computed && member.key.type === "Identifier"
    ? member.key.name
    : null;
}
