/**
 * @fileoverview _closed-module — the declaration shapes the closed-module fixes accept.
 *
 * Those fixes only rewrite code whose behavior they can see whole: a function that is
 * synchronous, not a generator, not `declare`d, not generic and has a body, and a
 * `const` statement that declares one binding.
 */

import type { ESTree, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";

type Body = ESTree.FunctionBody["body"];

/** The body statements of a plain function, or null for any other function. */
export function plainFunctionBody(node: ESTree.Function): Body | null {
  if (node.async || node.generator || node.declare === true || isPresent(node.typeParameters)) return null;
  return node.body === null ? null : node.body.body;
}

interface SoleExportedFunction {
  readonly statement: ESTree.ExportNamedDeclaration;
  readonly owner: ESTree.Function;
  readonly body: Body;
}

/** The module's only statement when it is a plain `export function …` and the module has no comments. */
export function soleExportedFunction(sourceCode: SourceCode): SoleExportedFunction | null {
  const [statement] = sourceCode.ast.body;
  if (
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0 ||
    statement?.type !== "ExportNamedDeclaration" ||
    statement.declaration?.type !== "FunctionDeclaration"
  )
    return null;
  const owner = statement.declaration;
  const body = plainFunctionBody(owner);
  return body === null ? null : { statement, owner, body };
}

/** The one declarator of a `const` statement that is not `declare`d. */
export function soleConstDeclarator(declaration: ESTree.VariableDeclaration): ESTree.VariableDeclarator | null {
  if (declaration.kind !== "const" || declaration.declare === true || declaration.declarations.length !== 1) return null;
  return declaration.declarations[0] ?? null;
}
