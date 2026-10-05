import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-transform-in-record-key.ts
/**
* Builds the `create` function for the `no-transform-in-record-key` rule.
*
* Takes the names that count as a transform for the plugin's API style and matches them against a `z.record()` key schema —
* both its factory (`z.record(z.transform(fn), …)`) and its constraints,
* which cover chained methods in `zod` and `.check(...)` arguments in `zod/mini`.
*/
function buildNoTransformInRecordKeyCreate(scope, transformNames) {
	return function create(context) {
		const { createSchemaVisitor, detectZodSchemaRootNode, collectZodSchemaConstraints } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "record",
			onSchema(node) {
				const keySchema = node.arguments.at(0);
				if (keySchema?.type !== AST_NODE_TYPES.CallExpression) return;
				const factory = detectZodSchemaRootNode(keySchema);
				const reportNode = factory && transformNames.includes(factory.schemaType) ? keySchema : collectZodSchemaConstraints(keySchema).find((constraint) => transformNames.includes(constraint.name))?.node;
				if (reportNode) context.report({
					node: reportNode,
					messageId: "noTransformInRecordKey"
				});
			}
		});
	};
}
//#endregion
export { buildNoTransformInRecordKeyCreate };
