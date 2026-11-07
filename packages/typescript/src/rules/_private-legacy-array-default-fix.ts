/** @fileoverview _private-legacy-array-default-fix — prove an unobserved legacy array wrapper in a closed module. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";
import { soleConstDeclarator } from "./_closed-module.js";

type Specifier = ESTree.ImportDeclaration["specifiers"][number];
type Identifier = ESTree.IdentifierReference;

/** Zod 3 has no supported constructor hook; keep its otherwise observable schemas private. */
export function privateLegacyArrayDefaultFix(
  sourceCode: SourceCode,
  node: ESTree.CallExpression,
  filename: string,
): FixFn | null {
  const schema = legacyZodSchema(sourceCode);
  if (
    schema === null ||
    schema.declaration.init !== node ||
    schema.declaration.id.type !== "Identifier" ||
    isPresent(schema.declaration.id.typeAnnotation) ||
    !isUnusedPrivateBinding(sourceCode, schema.declaration, schema.declaration.id, filename)
  )
    return null;
  const fallback = node.arguments[0];
  const optional = methodReceiver(node, "default", 1);
  const array = methodReceiver(optional, "optional", 0);
  const namespace = methodReceiver(array, "array", 1);
  const stringNamespace = methodReceiver(array?.type === "CallExpression" ? array.arguments[0] : undefined, "string", 0);
  if (
    fallback?.type !== "ArrayExpression" ||
    fallback.elements.length !== 0 ||
    optional === null ||
    array === null ||
    namespace?.type !== "Identifier" ||
    stringNamespace?.type !== "Identifier" ||
    !readsOnlyAt(sourceCode, schema.specifier, namespace, stringNamespace)
  )
    return null;
  return (fixer) => fixer.replaceText(optional, sourceCode.getText(array));
}

/** `import { z } from "zod/v3"` (or a namespace import) and one `const` declaration, in a comment-free module. */
function legacyZodSchema(
  sourceCode: SourceCode,
): { readonly specifier: Specifier; readonly declaration: ESTree.VariableDeclarator } | null {
  const [imported, statement] = sourceCode.ast.body;
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length !== 0 ||
    imported?.type !== "ImportDeclaration" ||
    imported.source.value !== "zod/v3" ||
    imported.importKind === "type" ||
    imported.specifiers.length !== 1 ||
    statement?.type !== "VariableDeclaration"
  )
    return null;
  const [specifier] = imported.specifiers;
  const declaration = soleConstDeclarator(statement);
  return specifier !== undefined && declaration !== null && importsZodNamespace(specifier)
    ? { specifier, declaration }
    : null;
}

function importsZodNamespace(specifier: Specifier): boolean {
  if (specifier.type !== "ImportSpecifier") return specifier.type === "ImportNamespaceSpecifier";
  return specifier.importKind !== "type" && specifier.imported.type === "Identifier" && specifier.imported.name === "z";
}

/** The imported namespace is read exactly at the two schema calls. */
function readsOnlyAt(sourceCode: SourceCode, specifier: Specifier, first: Identifier, second: Identifier): boolean {
  const binding = findVariable(sourceCode.getScope(first), first.name);
  return (
    binding !== null &&
    binding.defs.length === 1 &&
    binding.defs[0]?.name === specifier.local &&
    binding.references.length === 2 &&
    binding.references.every((reference) => reference.identifier === first || reference.identifier === second) &&
    findVariable(sourceCode.getScope(second), second.name) === binding
  );
}

function methodReceiver(
  node: Node | null | undefined,
  method: string,
  argumentCount: number,
): ESTree.Expression | null {
  if (
    node?.type !== "CallExpression" ||
    node.optional ||
    isPresent(node.typeArguments) ||
    node.arguments.length !== argumentCount ||
    node.callee.type !== "MemberExpression" ||
    node.callee.computed ||
    node.callee.optional ||
    node.callee.property.type !== "Identifier" ||
    node.callee.property.name !== method ||
    node.callee.object.type === "Super"
  )
    return null;
  return node.callee.object;
}
