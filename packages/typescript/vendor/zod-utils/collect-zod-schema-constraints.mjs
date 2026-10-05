import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/collect-zod-schema-constraints.ts
/**
* Flattens a zod call chain into the list of constraints applied to the schema,
* regardless of API style:
*
* - every chained method after the factory becomes a `chained` constraint
* (`.check(...)` itself excluded);
* - every recognized zod call among `.check(...)` arguments becomes a
* `check-argument` constraint.
* Non-call or unrecognized arguments are skipped,
* but still counted in `argumentCount` so fixers can tell whether removing a whole `.check(...)` would orphan an unrelated argument.
*
* Internal:
* rules use the bound `collectZodSchemaConstraints(node)` from `scope.createTracker({ kind: 'value' })`,
* which supplies the chain and the detector.
*/
function collectZodSchemaConstraints(opts) {
	const { methods, detectZodSchemaRootNode } = opts;
	const constraints = [];
	for (const [chainIndex, method] of methods.entries()) {
		if (chainIndex === 0) continue;
		if (method.name !== "check") {
			constraints.push({
				name: method.name,
				node: method.node,
				origin: "chained",
				chainIndex
			});
			continue;
		}
		const checkArguments = method.node.arguments;
		for (const [argumentIndex, argument] of checkArguments.entries()) {
			if (argument.type !== AST_NODE_TYPES.CallExpression) continue;
			const checkMeta = detectZodSchemaRootNode(argument);
			if (!checkMeta) continue;
			constraints.push({
				name: checkMeta.schemaType,
				node: argument,
				origin: "check-argument",
				chainIndex,
				checkNode: method.node,
				argumentIndex,
				argumentCount: checkArguments.length
			});
		}
	}
	return constraints;
}
//#endregion
export { collectZodSchemaConstraints };
