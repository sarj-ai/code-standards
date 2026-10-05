import { ZOD_BIGINT_SUBTYPE_NAMES, ZOD_NUMBER_SUBTYPE_NAMES } from "./zod-numeric-subtype-names.mjs";
import { ZOD_STRING_FORMAT_NAMES } from "./zod-string-format-names.mjs";
//#region src/zod-immutable-schema-types.ts
/**
* Zod schema factories whose parsed output is already immutable, so wrapping
* them in `readonly` has no effect on the inferred type (and no runtime
* effect: freezing a primitive is a no-op).
*
* Covers primitives/scalars, number sub-types, and the top-level string
* formats (they all parse to `string`). Container factories (`object`,
* `array`, `record`, `map`, `set`, `tuple`, …) are intentionally absent —
* `readonly` is meaningful there.
*/
const ZOD_IMMUTABLE_SCHEMA_TYPES = Object.freeze([
	"bigint",
	"boolean",
	"date",
	"enum",
	"literal",
	"nan",
	"nativeEnum",
	"null",
	"number",
	"string",
	"stringbool",
	"symbol",
	"templateLiteral",
	"undefined",
	"void",
	...ZOD_NUMBER_SUBTYPE_NAMES,
	...ZOD_BIGINT_SUBTYPE_NAMES,
	...ZOD_STRING_FORMAT_NAMES,
	"iso"
]);
//#endregion
export { ZOD_IMMUTABLE_SCHEMA_TYPES };
