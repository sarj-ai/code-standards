import { ZOD_BIGINT_SUBTYPE_NAMES, ZOD_NUMBER_SUBTYPE_NAMES } from "./zod-numeric-subtype-names.mjs";
import { ZOD_STRING_FORMAT_NAMES } from "./zod-string-format-names.mjs";
//#region src/get-zod-schema-base-type.ts
const BASE_TYPES = new Map([
	["string", "string"],
	["iso", "string"],
	...ZOD_STRING_FORMAT_NAMES.map((name) => [name, "string"]),
	["number", "number"],
	...ZOD_NUMBER_SUBTYPE_NAMES.map((name) => [name, "number"]),
	["bigint", "bigint"],
	...ZOD_BIGINT_SUBTYPE_NAMES.map((name) => [name, "bigint"]),
	["boolean", "boolean"],
	["stringbool", "boolean"],
	["date", "date"],
	["array", "array"],
	["object", "object"],
	["strictObject", "object"],
	["looseObject", "object"],
	["set", "set"],
	["map", "map"],
	["literal", "literal"],
	["any", "any"],
	["unknown", "unknown"],
	["never", "never"]
]);
/** Every name {@link getZodSchemaBaseType} maps, including the `iso` namespace. */
const ZOD_BASE_TYPE_NAMES = Object.freeze([...BASE_TYPES.keys()]);
/**
* Maps a schema factory name (the `schemaType` of `detectZodSchemaRootNode`) to its base type category,
* or `null` for factories the caller should not reason about (`union`, `tuple`, `enum`, `custom`, wrappers, …).
*/
function getZodSchemaBaseType(schemaType) {
	return BASE_TYPES.get(schemaType) ?? null;
}
//#endregion
export { ZOD_BASE_TYPE_NAMES, getZodSchemaBaseType };
