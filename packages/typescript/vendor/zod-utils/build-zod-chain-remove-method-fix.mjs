//#region src/build-zod-chain-remove-method-fix.ts
/**
* Remove one call from a zod method chain, e.g. `z.number().min(0).finite()` →
* `z.number().min(0)`.
*/
function buildZodChainRemoveMethodFix(opts) {
	const { fixer, methods, removeIndex } = opts;
	if (removeIndex < 1) return null;
	const prev = methods[removeIndex - 1]?.node;
	const toRemove = methods[removeIndex]?.node;
	if (!prev?.range || !toRemove?.range) return null;
	return fixer.removeRange([prev.range[1], toRemove.range[1]]);
}
//#endregion
export { buildZodChainRemoveMethodFix };
