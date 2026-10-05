import { trackZodSchemaImports } from "./track-zod-schema-imports.mjs";
//#region src/zod-import-scope.ts
/**
* Defines the set of import source strings (e.g. `'zod'`, `'zod/mini'`) that a plugin considers in-scope.
* Used by each plugin's rules to ignore files that import from a different Zod surface.
*
* @example
* ```ts
* const scope = new ZodImportScope(['zod', 'zod/v4'] as const);
* scope.isAllowed('zod');      // true
* scope.isAllowed('zod/mini'); // false
* ```
*/
var ZodImportScope = class {
	constructor(sources) {
		this.sources = Object.freeze([...sources]);
	}
	/** Returns `true` if `source` is one of the scope's recognised import sources. */
	isAllowed(source) {
		return this.sources.includes(source);
	}
	/**
	* Creates an import tracker bound to this scope.
	* Call it once per `create(...)` — a tracker accumulates one file's imports.
	*
	* `kind` is required — `'value'` for a rule resolving calls, `'all'` for a type position.
	* Both wrong answers fail silently.
	* Pass `sourceCode` to enable `resolveZodImport` / `resolveZodExport`.
	*
	* @example
	* ```ts
	* const { importDeclarationListener, detectZodSchemaRootNode } =
	* zodImportScope.createTracker({ kind: 'value' });
	* ```
	*/
	createTracker(options) {
		return trackZodSchemaImports(this, options);
	}
};
/** Pre-built scope for `eslint-plugin-zod`. Recognises `'zod'`, `'zod/v4'`, `'zod/v3'`. */
const zodImportScope = new ZodImportScope([
	"zod",
	"zod/v4",
	"zod/v3"
]);
/** Pre-built scope for `eslint-plugin-zod-mini`. Recognises `'zod/mini'`, `'zod/v4-mini'`. */
const zodMiniImportScope = new ZodImportScope(["zod/mini", "zod/v4-mini"]);
/** Pre-built scope for `eslint-plugin-zod-core`. Recognises `'zod/v4/core'`. */
const zodCoreImportScope = new ZodImportScope(["zod/v4/core"]);
//#endregion
export { ZodImportScope, zodCoreImportScope, zodImportScope, zodMiniImportScope };
