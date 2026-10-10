// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION } from "../../src/rules/named-child-schema-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const CHILD = 'const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]);';
const RECORD = 'export const RecordSchema: z.ZodRecord<z.ZodEnum<{ a: "a"; b: "b" }>, z.ZodString> = z.record(KeySchema, z.string());';
const SOURCE = `import { z } from "zod"; ${CHILD} ${RECORD}`;

new RuleTester({ languageOptions: { parser } }).run("named-child-schema-type", rule, {
  valid: [
    { name: "references the complete named child type", code: NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION.examples[0].files[0].source },
    { name: "keeps a distinct literal domain", code: SOURCE.replace('b: "b" }>,', 'c: "c" }>,') },
    { name: "does not equate schema input and output", code: 'import { z } from "zod"; const ValueSchema: z.ZodPipe<z.ZodString, z.ZodTransform<number, string>> = z.string().transform(Number); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodTransform<number, string>> = z.record(z.string(), ValueSchema);' },
    { name: "preserves a different default wrapper", code: 'import { z } from "zod"; const ValueSchema: z.ZodDefault<z.ZodString> = z.string().default("a"); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodOptional<z.ZodString>> = z.record(z.string(), ValueSchema);' },
    { name: "does not report a bare leaf type", code: 'import { z } from "zod"; const ValueSchema: z.ZodString = z.string(); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodString> = z.record(z.string(), ValueSchema);' },
    { name: "requires an explicit complete child annotation", code: SOURCE.replace(': z.ZodEnum<{ a: "a"; b: "b" }>', "") },
    { name: "does not replace independently imported child contracts", code: 'import { z } from "zod"; import { KeySchema } from "./keys.js"; ' + RECORD },
    { name: "skips mutable child bindings", code: SOURCE.replace("const KeySchema", "let KeySchema") },
    { name: "skips local declarations and shadowed namespaces", code: `import { z } from "zod"; function local(z: any) { ${CHILD} ${RECORD.replace("export ", "")} }` },
    { name: "requires the native Zod namespace", code: SOURCE.replace('from "zod"', 'from "./validation.js"') },
    { name: "skips type-only namespaces", code: SOURCE.replace("import { z }", "import type { z }") },
    { name: "skips repeated annotations on other constructors", code: SOURCE.replace("z.ZodRecord<", "z.ZodMap<").replace("z.record(", "z.map(") },
    { name: "skips chained parent schemas", code: SOURCE.replace("z.record(KeySchema, z.string())", "z.record(KeySchema, z.string()).readonly()") },
    { name: "preserves annotation comments and intentional pins", code: SOURCE.replace('z.ZodRecord<z.ZodEnum', 'z.ZodRecord</* independently pinned contract */ z.ZodEnum') },
    { name: "skips self-referential annotations", code: 'import { z } from "zod"; const ValueSchema: z.ZodArray<typeof RecordSchema> = z.array(RecordSchema); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodArray<typeof RecordSchema>> = z.record(z.string(), ValueSchema);' },
    { name: "skips indirect annotation cycles and unresolved aliases", code: 'import { z } from "zod"; type Value = typeof RecordSchema; const ValueSchema: z.ZodArray<Value> = z.array(RecordSchema); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodArray<Value>> = z.record(z.string(), ValueSchema);' },
    { name: "skips broad schema constraints", code: 'import { z } from "zod"; const ValueSchema: z.ZodType<string> = z.string(); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodType<string>> = z.record(z.string(), ValueSchema);' },
    { name: "skips generated headers", code: `// @generated\n${SOURCE}` },
    { name: "skips declaration files", code: SOURCE, filename: "src/contracts.d.ts" },
    { name: "skips generated paths", code: SOURCE, filename: "src/generated/contracts.ts" },
    { name: "honors exact ESLint suppression", code: `import { z } from "zod"; ${CHILD}\n// eslint-disable-next-line @rule-tester/named-child-schema-type -- This record deliberately pins its public contract.\n${RECORD}` },
  ],
  invalid: [
    { name: "reports the copied key annotation without a fix", code: NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION.examples[1].files[0].source, output: null, errors: [{ messageId: "namedChildType", data: { name: "KeySchema" } }] },
    { name: "resolves an aliased Zod namespace", code: SOURCE.replaceAll("z.", "validation.").replace("{ z }", "{ z as validation }"), output: null, errors: [{ messageId: "namedChildType", data: { name: "KeySchema" } }] },
    { name: "resolves a namespace import", code: SOURCE.replace("import { z }", "import * as z"), output: null, errors: [{ messageId: "namedChildType" }] },
    { name: "preserves the entire default value contract", code: 'import { z } from "zod/v4"; const ValueSchema: z.ZodDefault<z.ZodString> = z.string().default("a"); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodDefault<z.ZodString>> = z.record(z.string(), ValueSchema);', output: null, errors: [{ messageId: "namedChildType", data: { name: "ValueSchema" } }] },
    { name: "preserves readonly objects and literal property modifiers", code: 'import { z } from "zod"; const ValueSchema: z.ZodReadonly<z.ZodObject<{ readonly id: z.ZodString }>> = z.object({ id: z.string() }).readonly(); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodReadonly<z.ZodObject<{ readonly id: z.ZodString }>>> = z.record(z.string(), ValueSchema);', output: null, errors: [{ messageId: "namedChildType" }] },
    { name: "preserves a complete input/output transform type", code: 'import { z } from "zod"; const ValueSchema: z.ZodPipe<z.ZodString, z.ZodTransform<number, string>> = z.string().transform(Number); const RecordSchema: z.ZodRecord<z.ZodString, z.ZodPipe<z.ZodString, z.ZodTransform<number, string>>> = z.record(z.string(), ValueSchema);', output: null, errors: [{ messageId: "namedChildType" }] },
    { name: "reports each distinct duplicated operand once", code: 'import { z } from "zod"; const KeySchema: z.ZodEnum<{ a: "a" }> = z.enum(["a"]); const ValueSchema: z.ZodDefault<z.ZodString> = z.string().default("a"); const RecordSchema: z.ZodRecord<z.ZodEnum<{ a: "a" }>, z.ZodDefault<z.ZodString>> = z.record(KeySchema, ValueSchema);', output: null, errors: [{ messageId: "namedChildType", data: { name: "KeySchema" } }, { messageId: "namedChildType", data: { name: "ValueSchema" } }] },
  ],
});
