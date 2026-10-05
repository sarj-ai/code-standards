import { ZOD_NON_SCHEMA_PRODUCING_METHODS } from "../zod-non-schema-producing-methods.mjs";
//#region src/rule-patterns/deprecated-schema-method.ts
/**
* Flags a deprecated method anywhere in a schema chain (`.isOptional()`).
* Skipped when a non-schema-producing method comes first — the call then belongs to that result,
* not to zod.
* Report-only: the `safeParse(…)` replacement would duplicate the schema expression.
*/
function buildDeprecatedSchemaMethodCreate(options) {
	const { scope, methodName, messageId } = options;
	return function create(context) {
		const { createSchemaVisitor } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			const { methods } = zodSchemaMeta;
			const methodIndex = methods.indexOf(methodName);
			if (methodIndex === -1) return;
			if (methods.slice(0, methodIndex).some((it) => ZOD_NON_SCHEMA_PRODUCING_METHODS.includes(it))) return;
			context.report({
				node,
				messageId
			});
		} });
	};
}
//#endregion
export { buildDeprecatedSchemaMethodCreate };
