//#region src/zod-mutating-check-names.ts
/**
* Zod check names that mutate the validated value instead of just asserting on it.
* Used in `zod` as chained methods on a schema; used in `zod-mini` as standalone
* `$ZodCheck` calls passed to `.check(...)`.
*/
const ZOD_MUTATING_CHECK_NAMES = Object.freeze([
	"normalize",
	"overwrite",
	"toLowerCase",
	"toUpperCase",
	"trim"
]);
//#endregion
export { ZOD_MUTATING_CHECK_NAMES };
