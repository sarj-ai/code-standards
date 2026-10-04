import { ZOD_NON_SCHEMA_PRODUCING_METHODS } from "../zod-non-schema-producing-methods.mjs";
import { isZodSchemaFactoryCall } from "../zod-schema-factory-names.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/consistent-schema-var-name.ts
function buildConsistentSchemaVarNameCreate(scope) {
	return function create(context, [{ before = "", after = "" }]) {
		const { importDeclarationListener, detectZodSchemaRootNode, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return {
			ImportDeclaration: importDeclarationListener,
			VariableDeclarator(node) {
				const initNode = node.init;
				if (initNode?.type !== AST_NODE_TYPES.CallExpression) return;
				const meta = detectZodSchemaRootNode(initNode);
				if (!meta || !isZodSchemaFactoryCall(meta)) return;
				const chainMethods = collectZodChainMethods(initNode).map((it) => it.name);
				if (ZOD_NON_SCHEMA_PRODUCING_METHODS.some((it) => chainMethods.includes(it))) return;
				if (node.id.type !== AST_NODE_TYPES.Identifier) return;
				const { name } = node.id;
				const nameLower = name.toLowerCase();
				const matchesBarePrefix = Boolean(before) && nameLower === before.toLowerCase();
				const matchesBareSuffix = Boolean(after) && nameLower === after.toLowerCase();
				if (!before && matchesBareSuffix || !after && matchesBarePrefix) return;
				const validPrefix = !before || name.startsWith(before);
				const validSuffix = !after || name.endsWith(after);
				if (validPrefix && validSuffix) return;
				const expected = matchesBarePrefix || matchesBareSuffix ? before + after : (validPrefix ? "" : before) + name + (validSuffix ? "" : after);
				context.report({
					node,
					messageId: "invalidName",
					data: { expected }
				});
			}
		};
	};
}
//#endregion
export { buildConsistentSchemaVarNameCreate };
