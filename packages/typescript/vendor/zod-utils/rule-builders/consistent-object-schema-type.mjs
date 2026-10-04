import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/consistent-object-schema-type.ts
const ZOD_OBJECT_METHODS = [
	"object",
	"looseObject",
	"strictObject"
];
function buildConsistentObjectSchemaTypeCreate(scope) {
	return function create(context, [{ allow: allowedList }]) {
		const { createSchemaVisitor } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: ZOD_OBJECT_METHODS,
			onSchema(node, { schemaType }) {
				if (allowedList.includes(schemaType)) return;
				const { callee } = node;
				if (callee.type === AST_NODE_TYPES.Identifier) {
					context.report({
						node,
						messageId: "consistentMethod",
						data: {
							actual: schemaType,
							allowedList: allowedList.join(",")
						}
					});
					return;
				}
				if (callee.type === AST_NODE_TYPES.MemberExpression) context.report({
					node,
					messageId: "consistentMethod",
					data: {
						actual: schemaType,
						allowedList: allowedList.join(",")
					},
					suggest: allowedList.map((it) => ({
						messageId: "useMethod",
						data: { expected: it },
						fix(fixer) {
							return fixer.replaceText(callee.property, it);
						}
					}))
				});
			}
		});
	};
}
//#endregion
export { buildConsistentObjectSchemaTypeCreate };
