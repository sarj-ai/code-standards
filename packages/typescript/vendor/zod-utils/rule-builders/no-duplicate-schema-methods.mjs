import { ZOD_TYPE_CHANGING_METHODS } from "../zod-type-changing-methods.mjs";
//#region src/rule-builders/no-duplicate-schema-methods.ts
function buildNoDuplicateSchemaMethodsCreate(scope, excludedMethods) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const chainMethods = collectZodChainMethods(node);
			const seen = /* @__PURE__ */ new Set();
			for (const method of chainMethods) {
				if (ZOD_TYPE_CHANGING_METHODS.includes(method.name)) {
					seen.clear();
					continue;
				}
				if (excludedMethods.includes(method.name)) continue;
				if (seen.has(method.name)) context.report({
					node,
					messageId: "noDuplicateSchemaMethod",
					data: { method: method.name }
				});
				else seen.add(method.name);
			}
		} });
	};
}
//#endregion
export { buildNoDuplicateSchemaMethodsCreate };
