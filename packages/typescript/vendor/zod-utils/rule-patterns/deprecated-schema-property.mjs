import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-patterns/deprecated-schema-property.ts
/**
* Flags a deprecated property access on a schema of `schemaType` (`z.number().isInt`).
* Report-only: the replacement depends on surrounding code, so no fix is safe.
*/
function buildDeprecatedSchemaPropertyCreate(options) {
	const { scope, schemaType, propertyName, messageId } = options;
	return function create(context) {
		const { importDeclarationListener, isZodSchemaOfType } = scope.createTracker({ kind: "value" });
		return {
			ImportDeclaration: importDeclarationListener,
			MemberExpression(node) {
				if (node.computed) return;
				if (node.property.type !== AST_NODE_TYPES.Identifier) return;
				if (node.property.name !== propertyName) return;
				if (node.object.type !== AST_NODE_TYPES.CallExpression) return;
				if (!isZodSchemaOfType(node.object, schemaType)) return;
				context.report({
					node,
					messageId
				});
			}
		};
	};
}
//#endregion
export { buildDeprecatedSchemaPropertyCreate };
