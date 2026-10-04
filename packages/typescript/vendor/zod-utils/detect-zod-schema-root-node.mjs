import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/detect-zod-schema-root-node.ts
/**
* Helper: extract static property names (Identifier | Literal | simple template literal)
*/
function getPropertyName(prop) {
	if (prop.type === AST_NODE_TYPES.Identifier) return prop.name;
	if (prop.type === AST_NODE_TYPES.Literal) return prop.value == null ? null : String(prop.value);
	if (prop.type === AST_NODE_TYPES.TemplateLiteral) {
		if (prop.expressions.length === 0 && prop.quasis.length === 1) return prop.quasis[0].value.cooked;
		return null;
	}
	return null;
}
/** Quick check: only process outermost call in a chain */
function isOutermostCallExpression(node) {
	const { parent } = node;
	if (parent.type === AST_NODE_TYPES.CallExpression && parent.callee === node) return false;
	if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === node) return false;
	return true;
}
/**
* Parse a CallExpression to detect whether it's a zod schema expression (namespace or named).
* This helper DOES NOT require the call to be outermost.
*
* Returns:
*  { schemaDecl, schemaType, methods, node } if successful
*  null otherwise
*/
function parseZodCallExpression(call, imports) {
	let cur = call.callee;
	const methodsRightToLeft = [];
	let leftmostIdentifier;
	while (true) {
		if (cur.type === AST_NODE_TYPES.CallExpression) {
			cur = cur.callee;
			continue;
		}
		if (cur.type === AST_NODE_TYPES.MemberExpression) {
			const name = getPropertyName(cur.property);
			if (!name) return null;
			methodsRightToLeft.push(name);
			cur = cur.object;
			continue;
		}
		if (cur.type === AST_NODE_TYPES.Identifier) {
			leftmostIdentifier = cur.name;
			break;
		}
		return null;
	}
	const methods = methodsRightToLeft.slice().reverse();
	if (imports.namespaces.has(leftmostIdentifier)) {
		const factory = methods[0] ?? null;
		if (!factory) return null;
		return {
			schemaDecl: "namespace",
			schemaType: factory,
			methods
		};
	}
	const factory = imports.named.get(leftmostIdentifier);
	if (factory !== void 0) return {
		schemaDecl: "named",
		schemaType: factory,
		methods
	};
	return null;
}
/**
* True when `node` is a zod call chain built from `schemaType` (e.g.
* `z.number().min(1)` or `number().min(1)` for `'number'`). Unlike
* {@link detectZodSchemaRootNode} the call need not be outermost, which is
* what member access like `z.number().isInt` requires.
*/
function isZodSchemaOfType(node, schemaType, imports) {
	if (node.type !== AST_NODE_TYPES.CallExpression) return false;
	const parsed = parseZodCallExpression(node, imports);
	return parsed !== null && parsed.schemaType === schemaType;
}
/**
* Finds the outermost Zod call expression in a chain and returns metadata about it
* (declaration style, factory name, methods, AST node). Includes calls in argument
* position (e.g. inside `.check(...)`), so a standalone check call is treated as the
* root of its own expression.
*
* Returns `null` if the node is not a Zod schema call or not the outermost call in its chain.
*
* @param node - The AST node to analyze (typically a `CallExpression` from an ESLint visitor)
* @param imports - The file's zod imports, from a tracker
*/
function detectZodSchemaRootNode(node, imports) {
	if (node.type !== AST_NODE_TYPES.CallExpression) return null;
	const call = node;
	if (!isOutermostCallExpression(call)) return null;
	const outer = parseZodCallExpression(call, imports);
	if (!outer) return null;
	return outer;
}
//#endregion
export { detectZodSchemaRootNode, isZodSchemaOfType };
