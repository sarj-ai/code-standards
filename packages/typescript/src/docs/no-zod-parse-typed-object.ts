/** @fileoverview no-zod-parse-typed-object — the documentation and executable examples of `@sarj/no-zod-parse-typed-object`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Reuse known object contracts instead of parsing them again with Zod.",
  rationale: "Parsing a typed service result duplicates its object contract and adds runtime validation and copying throughout trusted application code. Validate unknown data once at its boundary.",
  remediation: "Use the typed value directly. If defaults or normalization are needed, express that mapping explicitly. Keep untrusted boundary data unknown until it is validated.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires type information, strict null checks, and a native installed Zod parse, parseAsync, safeParse or safeParseAsync signature. Recognizes imported schemas, aliases, member access and awaited service results without guessing from names.",
    "Reports fully known object or array inputs assignable to the schema input, when schema input and output have the same value shape. Optional-to-required defaults are included; type-changing transforms, coercions, brands, incompatible contracts, primitive roots and nested any/unknown/generic contracts are excluded.",
    "Static types do not establish runtime trust or prove refinements and normalization redundant. This is an architectural warning with no automatic removal. Keep intentional validation at an unknown-data boundary or document an exact local suppression. Tests, stories and generated code are excluded.",
    "Shape comparison ignores undefined introduced by optional properties and checks tuple element types and rest positions. It is bounded to 128 object pairs, visited input objects, properties, tuple elements or primitive union alternatives; object unions have at most 16 alternatives. Opaque or larger graphs are conservatively excluded.",
  ],
  references: ["https://zod.dev/basics"],
  examples: [
    { id: "imported-schema-alias", title: "Imported schema names do not establish a new boundary", outcome: "match", files: [{ path: "src/schema.ts", source: 'import { z } from "zod"; export const RowSchema = z.object({ id: z.string() });' }, { path: "src/value.ts", source: 'import { RowSchema as schema } from "./schema.js"; export function read(row: { id: string }) { return schema.safeParse(row); }' }], focusPath: "src/value.ts", expectedCount: 1, public: false, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "unknown-boundary", title: "Validate unknown data once", outcome: "no-match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); export function read(raw: unknown) { return RowSchema.parse(raw); }' }], focusPath: "src/value.ts", expectedCount: 0, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "typed-service-result", title: "Reuse the typed service response", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); declare function load(): Promise<{ id: string }>; export async function read() { return RowSchema.parse(await load()); }' }], focusPath: "src/value.ts", expectedCount: 1, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "typed-result-with-default", title: "Make a typed response default explicit", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string(), enabled: z.boolean().default(false) }); declare function load(): Promise<{ id: string; enabled?: boolean }>; export async function read() { return RowSchema.parse(await load()); }' }], focusPath: "src/value.ts", expectedCount: 1, public: false, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
  ],
} as const satisfies RuleDocumentation;
