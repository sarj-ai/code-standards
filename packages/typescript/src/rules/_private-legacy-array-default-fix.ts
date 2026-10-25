/**
 * @fileoverview _private-legacy-array-default-fix — simplify an unobserved legacy array wrapper.
 */

/** @fileoverview Prove an unobserved legacy array wrapper in a closed module. */
import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { isUnusedPrivateBinding } from "./_unused-private-binding.js";

/** Zod 3 has no supported constructor hook; keep its otherwise observable schemas private. */
export function privateLegacyArrayDefaultFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.CallExpression,
  filename: string,
): TSESLint.ReportFixFunction | null {
  const [imported, statement] = sourceCode.ast.body;
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length !== 0 ||
    imported?.type !== AST_NODE_TYPES.ImportDeclaration ||
    imported.source.value !== "zod/v3" ||
    imported.importKind === "type" ||
    imported.specifiers.length !== 1 ||
    statement?.type !== AST_NODE_TYPES.VariableDeclaration ||
    statement.declare ||
    statement.kind !== "const" ||
    statement.declarations.length !== 1
  )
    return null;
  const specifier = imported.specifiers[0];
  const declaration = statement.declarations[0];
  if (
    specifier === undefined ||
    specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
    (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
      (specifier.importKind === "type" ||
        specifier.imported.type !== AST_NODE_TYPES.Identifier ||
        specifier.imported.name !== "z")) ||
    declaration === undefined ||
    declaration.init !== node ||
    declaration.id.type !== AST_NODE_TYPES.Identifier ||
    declaration.id.typeAnnotation !== undefined ||
    !isUnusedPrivateBinding(sourceCode, declaration, declaration.id, filename)
  )
    return null;
  const fallback = node.arguments[0];
  const optional = methodReceiver(node, "default", 1);
  const array =
    optional === null ? null : methodReceiver(optional, "optional", 0);
  const namespace = array === null ? null : methodReceiver(array, "array", 1);
  const element =
    array?.type === AST_NODE_TYPES.CallExpression
      ? array.arguments[0]
      : undefined;
  const stringNamespace = methodReceiver(element, "string", 0);
  if (
    fallback?.type !== AST_NODE_TYPES.ArrayExpression ||
    fallback.elements.length !== 0 ||
    namespace?.type !== AST_NODE_TYPES.Identifier ||
    stringNamespace?.type !== AST_NODE_TYPES.Identifier
  )
    return null;
  const binding = ASTUtils.findVariable(
    sourceCode.getScope(namespace),
    namespace.name,
  );
  if (
    binding === null ||
    binding.defs.length !== 1 ||
    binding.defs[0]?.name !== specifier.local ||
    binding.references.length !== 2 ||
    binding.references.some(
      (reference) =>
        reference.identifier !== namespace &&
        reference.identifier !== stringNamespace,
    ) ||
    ASTUtils.findVariable(
      sourceCode.getScope(stringNamespace),
      stringNamespace.name,
    ) !== binding ||
    optional === null ||
    array === null
  )
    return null;
  return (fixer) => fixer.replaceText(optional, sourceCode.getText(array));
}

function methodReceiver(
  node: TSESTree.Node | undefined,
  method: string,
  argumentCount: number,
): TSESTree.Expression | null {
  if (
    node?.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.typeArguments !== undefined ||
    node.arguments.length !== argumentCount ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.computed ||
    node.callee.optional ||
    node.callee.property.type !== AST_NODE_TYPES.Identifier ||
    node.callee.property.name !== method ||
    node.callee.object.type === AST_NODE_TYPES.Super
  )
    return null;
  return node.callee.object;
}
