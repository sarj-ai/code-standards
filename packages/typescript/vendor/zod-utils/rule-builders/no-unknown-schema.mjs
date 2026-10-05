//#region src/rule-builders/no-unknown-schema.ts
function buildNoUnknownSchemaCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "unknown",
			onSchema(node) {
				context.report({
					node,
					messageId: "noZUnknown"
				});
			}
		});
	};
}
//#endregion
export { buildNoUnknownSchemaCreate };
