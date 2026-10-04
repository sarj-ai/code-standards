//#region src/rule-builders/require-brand-type-parameter.ts
function buildRequireBrandTypeParameterCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const brandMethod = collectZodChainMethods(node).find((it) => it.name === "brand");
			if (!brandMethod) return;
			const brandNode = brandMethod.node;
			const { typeArguments } = brandNode;
			if (typeArguments && typeArguments.params.length > 0) return;
			const brandCalleeNode = brandNode.callee;
			context.report({
				messageId: "missingTypeParameter",
				node: brandCalleeNode.property,
				suggest: [{
					messageId: "removeBrandFunction",
					fix(fixer) {
						return fixer.removeRange([brandCalleeNode.object.range[1], brandNode.range[1]]);
					}
				}]
			});
		} });
	};
}
//#endregion
export { buildRequireBrandTypeParameterCreate };
