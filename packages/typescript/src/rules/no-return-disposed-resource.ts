/**
 * @fileoverview no-return-disposed-resource — Do not return a resource whose using declaration disposes it before the caller receives it.
 *
 * Port of the 18.x `no-return-disposed-resource` rule. Same algorithm;
 * the generated-file gate runs in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "no-return-disposed-resource";

function resourceOwner(source: SourceCode, value: Node, seen: ReadonlySet<TsVariable> = new Set()): ESTree.VariableDeclarator | null {
  const node = unwrapExpression(value);
  if (node.type !== "Identifier") return null;
  const variable = findVariable(source.getScope(node), node.name);
  const declaration = variable?.defs.length === 1 ? variable.defs[0]!.node : null;
  if (variable === null || declaration?.type !== "VariableDeclarator" || seen.has(variable) ||
      variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
  const kind = (parentOf(declaration) as ESTree.VariableDeclaration).kind;
  if (kind === "using" || kind === "await using") return declaration;
  if (kind !== "const" || declaration.init === null || declaration.range[1] >= node.range[0]) return null;
  return resourceOwner(source, declaration.init, new Set([...seen, variable]));
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: "Do not return a resource whose using declaration disposes it before the caller receives it.", url: docsUrl(NAME) },
    schema: [],
    messages: { disposedReturn: "This using resource is disposed when its function returns; keep the consumer inside its lifetime or transfer ownership explicitly." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
      },
      ReturnStatement(node: ESTree.ReturnStatement): void {
        if (node.argument === null) return;
        const declaration = resourceOwner(sourceCode, node.argument);
        if (declaration !== null && enclosingFunction(declaration) === enclosingFunction(node)) context.report({ node: node.argument, messageId: "disposedReturn" });
      },
    };
  },
});
