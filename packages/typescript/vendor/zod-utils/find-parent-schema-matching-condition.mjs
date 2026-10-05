import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/find-parent-schema-matching-condition.ts
/**
* Walks up the AST from a Zod call expression and returns `true` when an
* ancestor call expression invokes a method named `schemaName` and the supplied
* `condition` predicate returns `true` for it.
*
* Useful for asking questions like *"is this `.min(1)` chain used inside a
* `z.record(...)` call as its first argument?"* without having to write the
* ancestor traversal in every rule.
*
* Returns `false` if no matching ancestor is reached before the root.
*
* @param outermostNode - Starting call expression (typically the result of {@link detectZodSchemaRootNode})
* @param options.schemaName - Name of the ancestor method to look for (e.g. `'record'`)
* @param options.condition - Predicate evaluated on the matching ancestor call expression
*/
function findParentSchemaMatchingCondition(outermostNode, options) {
	const { schemaName, condition } = options;
	let current = outermostNode;
	while (current.parent) {
		const { parent } = current;
		if (parent.type === AST_NODE_TYPES.CallExpression) {
			const callParent = parent;
			if (callParent.callee.type === AST_NODE_TYPES.MemberExpression) {
				const memberExpr = callParent.callee;
				if ((memberExpr.property.type === AST_NODE_TYPES.Identifier ? memberExpr.property.name : null) === schemaName) return condition(callParent);
			}
		}
		if (parent.type === AST_NODE_TYPES.MemberExpression) {
			current = parent;
			continue;
		}
		current = parent;
	}
	return false;
}
//#endregion
export { findParentSchemaMatchingCondition };
