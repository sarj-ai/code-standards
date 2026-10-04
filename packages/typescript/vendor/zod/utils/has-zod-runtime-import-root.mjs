import { zodImportScope } from "../../zod-utils/index.mjs";
import { ASTUtils, AST_NODE_TYPES, TSESLint } from "@typescript-eslint/utils";
//#region src/utils/has-zod-runtime-import-root.ts
/**
* Whether the identifier a chain starts from resolves to a runtime zod import.
* Bails on a root that is shadowed, re-assigned, type-only, or imported from another source —
* every case where a fix would rewrite code that is not zod, or reference a binding erased at runtime.
*/
function hasZodRuntimeImportRoot(node, sourceCode) {
	let root = node;
	while (root.type === AST_NODE_TYPES.CallExpression || root.type === AST_NODE_TYPES.MemberExpression) root = root.type === AST_NODE_TYPES.CallExpression ? root.callee : root.object;
	if (root.type !== AST_NODE_TYPES.Identifier) return false;
	const variable = ASTUtils.findVariable(sourceCode.getScope(root), root);
	if (variable?.defs.length !== 1) return false;
	const [definition] = variable.defs;
	if (definition.type !== TSESLint.Scope.DefinitionType.ImportBinding || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.parent.importKind === "type" || !zodImportScope.isAllowed(definition.parent.source.value)) return false;
	const specifier = definition.node;
	return specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier || specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier || specifier.type === AST_NODE_TYPES.ImportSpecifier && specifier.importKind !== "type";
}
//#endregion
export { hasZodRuntimeImportRoot };
