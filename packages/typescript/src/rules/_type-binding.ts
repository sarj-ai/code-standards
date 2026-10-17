/** @fileoverview _type-binding — resolve type names without value-only shadowing. */
import { type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export function typeBinding(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
): TSESLint.Scope.Variable | null {
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    if (variable !== undefined &&
      (variable.isTypeVariable || variable.defs.some(definition => definition.isTypeDefinition))) {
      return variable;
    }
    scope = scope.upper;
  }
  return null;
}
