import { isZodNonSchemaHelperCall } from "../zod-non-schema-helper-names.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
import { findVariable } from "../../eslint-utils/index.mjs";
//#region src/rule-builders/no-dynamic-schema-value.ts
/**
* True when every leaf of `node` is a literal or an import binding —
* `zod-compiler`'s hoist criterion.
* A nested zod schema call (e.g. the `z.string()` inside `z.object({ a: z.string() })`) counts as static here:
* it is checked independently through its own `onSchema` visit.
*/
function isStaticExpression(node, state) {
	switch (node.type) {
		case AST_NODE_TYPES.Literal:
		case AST_NODE_TYPES.ArrowFunctionExpression:
		case AST_NODE_TYPES.FunctionExpression: return true;
		case AST_NODE_TYPES.TemplateLiteral: return node.expressions.every((expression) => isStaticExpression(expression, state));
		case AST_NODE_TYPES.ArrayExpression: return node.elements.every((element) => element === null || isStaticExpression(element.type === AST_NODE_TYPES.SpreadElement ? element.argument : element, state));
		case AST_NODE_TYPES.ObjectExpression: return node.properties.every((property) => isStaticExpression(property.type === AST_NODE_TYPES.SpreadElement ? property.argument : property.value, state));
		case AST_NODE_TYPES.UnaryExpression: return isStaticExpression(node.argument, state);
		case AST_NODE_TYPES.ChainExpression:
		case AST_NODE_TYPES.TSAsExpression:
		case AST_NODE_TYPES.TSSatisfiesExpression:
		case AST_NODE_TYPES.TSNonNullExpression: return isStaticExpression(node.expression, state);
		case AST_NODE_TYPES.ConditionalExpression: return isStaticExpression(node.test, state) && isStaticExpression(node.consequent, state) && isStaticExpression(node.alternate, state);
		case AST_NODE_TYPES.LogicalExpression:
		case AST_NODE_TYPES.BinaryExpression: return node.left.type !== AST_NODE_TYPES.PrivateIdentifier && isStaticExpression(node.left, state) && isStaticExpression(node.right, state);
		case AST_NODE_TYPES.Identifier: {
			const def = findVariable(state.context.sourceCode.getScope(node), node)?.defs[0];
			if (!def) return false;
			if (def.type === "ImportBinding" || def.type === "FunctionName") return true;
			if (def.type !== "Variable" || def.parent.kind !== "const" || def.node.init === null || state.resolving.has(def.node)) return false;
			state.resolving.add(def.node);
			const isStatic = isStaticExpression(def.node.init, state);
			state.resolving.delete(def.node);
			return isStatic;
		}
		case AST_NODE_TYPES.CallExpression: return state.isZodCall(node);
		default: return false;
	}
}
/**
* Flags a non-static value passed as an argument anywhere in a zod schema expression —
* `z.string(getErrorMessage())`, `new Date()`, `this` —
* the same values `zod-compiler` cannot hoist at build time.
*/
function buildNoDynamicSchemaValueCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, detectZodSchemaRootNode, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		const state = {
			context,
			isZodCall: (node) => detectZodSchemaRootNode(node) !== null,
			resolving: /* @__PURE__ */ new Set()
		};
		return createSchemaVisitor({ onSchema(node, meta) {
			if (isZodNonSchemaHelperCall(meta)) return;
			const chain = collectZodChainMethods(node);
			const calls = chain.length > 0 ? chain.map((item) => item.node) : [node];
			for (const call of calls) for (const argument of call.arguments) {
				const expression = argument.type === AST_NODE_TYPES.SpreadElement ? argument.argument : argument;
				if (!isStaticExpression(expression, state)) context.report({
					node: expression,
					messageId: "dynamicValue"
				});
			}
		} });
	};
}
//#endregion
export { buildNoDynamicSchemaValueCreate };
