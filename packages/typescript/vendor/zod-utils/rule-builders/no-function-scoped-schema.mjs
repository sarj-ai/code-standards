import { isZodSchemaFactoryCall } from "../zod-schema-factory-names.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-function-scoped-schema.ts
const FUNCTION_NODE_TYPES = /* @__PURE__ */ new Set([
	AST_NODE_TYPES.FunctionDeclaration,
	AST_NODE_TYPES.FunctionExpression,
	AST_NODE_TYPES.ArrowFunctionExpression
]);
/**
* The two recursive-schema idioms where a function is the schema's only legal home:
* an object getter, and the thunk passed to `z.lazy()`.
* Walking past one leaves the enclosing scope — not the thunk — deciding whether to report.
*/
function isRecursiveSchemaThunk(node, isLazyCall) {
	const { parent } = node;
	return parent?.type === AST_NODE_TYPES.Property ? parent.kind === "get" && parent.value === node : parent?.type === AST_NODE_TYPES.CallExpression && parent.callee !== node && isLazyCall(parent);
}
/**
* Flags a zod schema constructed inside a function body — `() => z.string()`,
* or a schema declared in a function's block — instead of once at module scope.
* Under `import 'zod/compile'` a schema instance is compiled lazily on first parse,
* so a per-call schema is rebuilt (and recompiled) on every call.
*/
function buildNoFunctionScopedSchemaCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, isZodSchemaOfType } = scope.createTracker({ kind: "value" });
		const reportedSchemaCalls = /* @__PURE__ */ new WeakSet();
		const isLazyCall = (node) => isZodSchemaOfType(node, "lazy");
		return createSchemaVisitor({ onSchema(node, meta) {
			if (!isZodSchemaFactoryCall(meta)) return;
			let current = node;
			while (current.parent) {
				const parent = current.parent;
				if (parent.type === AST_NODE_TYPES.Program) return;
				if (parent.type === AST_NODE_TYPES.CallExpression && reportedSchemaCalls.has(parent)) return;
				if (FUNCTION_NODE_TYPES.has(parent.type) && !isRecursiveSchemaThunk(parent, isLazyCall)) {
					reportedSchemaCalls.add(node);
					context.report({
						node,
						messageId: "functionScopedSchema"
					});
					return;
				}
				current = parent;
			}
		} });
	};
}
//#endregion
export { buildNoFunctionScopedSchemaCreate };
