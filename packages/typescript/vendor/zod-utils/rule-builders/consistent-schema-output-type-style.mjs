import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/consistent-schema-output-type-style.ts
function buildConsistentSchemaOutputTypeStyleCreate(scope) {
	return function create(context, [{ style }]) {
		const { importDeclarationListener, isZodNamespace, getNamedImportOriginal, getNamedImportLocal } = scope.createTracker({ kind: "all" });
		return {
			ImportDeclaration: importDeclarationListener,
			TSTypeReference(node) {
				const { typeName } = node;
				if (typeName.type === AST_NODE_TYPES.TSQualifiedName) {
					const { left, right } = typeName;
					if (left.type !== AST_NODE_TYPES.Identifier || !isZodNamespace(left.name)) return;
					const usedStyle = right.name;
					if (usedStyle !== "infer" && usedStyle !== "output" || usedStyle === style) return;
					context.report({
						node: right,
						messageId: style === "infer" ? "useInfer" : "useOutput",
						fix(fixer) {
							return fixer.replaceText(right, style);
						}
					});
					return;
				}
				if (typeName.type === AST_NODE_TYPES.Identifier) {
					const originalName = getNamedImportOriginal(typeName.name);
					if (originalName !== "infer" && originalName !== "output" || originalName === style) return;
					const targetLocalName = getNamedImportLocal(style);
					context.report({
						node: typeName,
						messageId: style === "infer" ? "useInfer" : "useOutput",
						fix(fixer) {
							if (!targetLocalName || targetLocalName === "infer") return null;
							return fixer.replaceText(typeName, targetLocalName);
						}
					});
				}
			}
		};
	};
}
//#endregion
export { buildConsistentSchemaOutputTypeStyleCreate };
