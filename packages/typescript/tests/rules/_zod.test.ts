import { describe, expect, it } from "vitest";

import {
  ZOD_PREFIX_RE,
  ZOD_SCHEMA_NAME_RE,
  ZOD_SUFFIX_RE,
  isZodModule,
} from "../../src/rules/_zod.js";

describe("Zod schema names", () => {
  it.each(["ZUser", "ZSubmitForm"])("accepts the Z<Capital> prefix: %s", (name) => {
    expect(ZOD_PREFIX_RE.test(name)).toBe(true);
    expect(ZOD_SCHEMA_NAME_RE.test(name)).toBe(true);
  });

  it.each(["userSchema", "SubmitFormDataSchema"])(
    "accepts the Schema suffix: %s",
    (name) => {
      expect(ZOD_SUFFIX_RE.test(name)).toBe(true);
      expect(ZOD_SCHEMA_NAME_RE.test(name)).toBe(true);
    },
  );

  it.each(["User", "zUser", "Zuser", "userSchemaValue"])(
    "rejects names outside both conventions: %s",
    (name) => {
      expect(ZOD_SCHEMA_NAME_RE.test(name)).toBe(false);
    },
  );

  it.each(["ZUser", "userSchema", "User", "zUser", "userSchemaValue"])(
    "keeps the combined matcher equivalent to its two conventions: %s",
    (name) => {
      expect(ZOD_SCHEMA_NAME_RE.test(name)).toBe(
        ZOD_PREFIX_RE.test(name) || ZOD_SUFFIX_RE.test(name),
      );
    },
  );
});

describe("Zod module names", () => {
  it.each(["zod", "zod/v4", "zod/mini", "@hono/zod-validator"])(
    "recognises supported Zod imports: %s",
    (source) => {
      expect(isZodModule(source)).toBe(true);
    },
  );

  it.each(["./zod.ts", "@scope/zodiac", "zodish", "validation"])(
    "ignores unrelated imports: %s",
    (source) => {
      expect(isZodModule(source)).toBe(false);
    },
  );
});
