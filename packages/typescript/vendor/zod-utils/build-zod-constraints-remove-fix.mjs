import { buildZodChainRemoveMethodFix } from "./build-zod-chain-remove-method-fix.mjs";
//#region src/build-zod-constraints-remove-fix.ts
/**
* Build the fixes that remove the given constraints from a zod chain,
* whatever their API style:
*
* - `chained` constraints are removed as chain methods
*   (`z.array(x).min(2)` → `z.array(x)`);
* - `check-argument` constraints are removed by deleting the containing
*   `.check(...)` call — but only when every argument of that call is
*   targeted, so removal never orphans an unrelated check argument.
*
* Pass each constraint at most once. Returns `null` when the constraints
* cannot be removed safely (partial `.check(...)` coverage, unfixable chain
* position); callers should then report without fixing.
*/
function buildZodConstraintsRemoveFix(opts) {
	const { fixer, methods, constraints } = opts;
	const fixes = [];
	const checkRemovals = /* @__PURE__ */ new Map();
	for (const constraint of constraints) {
		if (constraint.origin === "chained") {
			const fix = buildZodChainRemoveMethodFix({
				fixer,
				methods,
				removeIndex: constraint.chainIndex
			});
			if (fix === null) return null;
			fixes.push(fix);
			continue;
		}
		const entry = checkRemovals.get(constraint.chainIndex);
		if (entry) entry.targeted += 1;
		else checkRemovals.set(constraint.chainIndex, {
			targeted: 1,
			argumentCount: constraint.argumentCount
		});
	}
	for (const [chainIndex, { targeted, argumentCount }] of checkRemovals) {
		if (targeted !== argumentCount) return null;
		const fix = buildZodChainRemoveMethodFix({
			fixer,
			methods,
			removeIndex: chainIndex
		});
		if (fix === null) return null;
		fixes.push(fix);
	}
	return fixes;
}
//#endregion
export { buildZodConstraintsRemoveFix };
