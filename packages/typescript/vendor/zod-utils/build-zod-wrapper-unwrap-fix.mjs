import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/build-zod-wrapper-unwrap-fix.ts
/**
* Replace a single-argument wrapper call with its argument, e.g.
* `z.readonly(z.string())` → `z.string()`. Any chain on the wrapper is
* preserved (`z.readonly(z.string()).check(…)` → `z.string().check(…)`).
*
* Returns `null` when the call does not have exactly one non-spread
* argument, so callers report without fixing.
*/
function buildZodWrapperUnwrapFix(opts) {
	const { fixer, sourceCode, wrapperCall } = opts;
	if (wrapperCall.arguments.length !== 1) return null;
	const [inner] = wrapperCall.arguments;
	if (inner.type === AST_NODE_TYPES.SpreadElement) return null;
	return fixer.replaceText(wrapperCall, sourceCode.getText(inner));
}
//#endregion
export { buildZodWrapperUnwrapFix };
