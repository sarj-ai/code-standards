//#region src/rule-builders/no-promise-schema.ts
/**
* Builds the `create` function for the `no-promise-schema` rule.
*
* `promise` is a plain namespace factory in both `zod` and `zod/mini`,
* so the same detection serves both plugins unchanged.
* There is no fix: the migration is to await the value before parsing it,
* which depends on the surrounding control flow.
*/
function buildNoPromiseSchemaCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "promise",
			onSchema(node) {
				context.report({
					node,
					messageId: "noPromiseSchema"
				});
			}
		});
	};
}
//#endregion
export { buildNoPromiseSchemaCreate };
