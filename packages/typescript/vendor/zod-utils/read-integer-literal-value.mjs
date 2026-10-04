import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/read-integer-literal-value.ts
/**
* Reads a non-negative integer literal, or `null` for anything else — rules
* comparing check arguments must skip non-literal counts rather than guess.
* Internal to `@eslint-zod/utils`.
*/
function readIntegerLiteralValue(node) {
	if (node?.type !== AST_NODE_TYPES.Literal) return null;
	const { value } = node;
	if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return null;
	return value;
}
//#endregion
export { readIntegerLiteralValue };
