//#region src/rule-builders/no-empty-custom-schema.ts
function buildNoEmptyCustomSchemaCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "custom",
			onSchema(node) {
				const customCallNode = collectZodChainMethods(node).find((method) => method.name === "custom")?.node;
				if (customCallNode?.arguments.length === 0) context.report({
					node: customCallNode,
					messageId: "noEmptyCustomSchema"
				});
			}
		});
	};
}
//#endregion
export { buildNoEmptyCustomSchemaCreate };
