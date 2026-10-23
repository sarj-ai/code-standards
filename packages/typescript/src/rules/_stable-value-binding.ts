/**
 * @fileoverview _stable-value-binding — prove one value initializer site and no later assignments.
 */
import { type TSESLint, type TSESTree } from "@typescript-eslint/utils";

type BindingReference = TSESLint.Scope.Variable["references"][number];

export function stableValueBinding(
  variable: TSESLint.Scope.Variable,
  acceptRead?: (reference: BindingReference) => boolean,
): boolean {
  let initializer: TSESTree.Node | undefined;
  return variable.references.every((reference) => {
    if (!reference.isWrite()) return acceptRead?.(reference) ?? true;
    if (reference.init !== true || (initializer !== undefined && initializer !== reference.identifier)) return false;
    initializer = reference.identifier;
    return true;
  });
}
