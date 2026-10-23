// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import plugin from "../src/index.js";

const PROMOTIONS = [
  {
    rule: "prefer-multi-value-zod-literal",
    filename: "src/schema.ts",
    source: "import { z } from 'zod/v4'; const Version = z.union([z.literal(1), z.literal(2)]);",
  },
  {
    rule: "require-camelcase-properties",
    filename: "src/wire.ts",
    source: "declare const response: { 'event_id': string }; response.event_id;",
  },
] as const;

for (const preset of ["recommended", "strict"] as const) {
  it.each(PROMOTIONS)(`${preset} blocks $rule with an exact compatibility exception`, ({ rule, filename, source }) => {
    const ruleId = `@sarj/${rule}` as const;
    const config: Linter.Config = {
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { "@sarj": plugin },
      rules: { [ruleId]: plugin.configs[preset].rules[ruleId] },
    };
    const linter = new Linter();
    const findings = linter.verify(source, config, { filename });
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ ruleId, severity: 2 });
    expect(linter.verify(source, config, { filename })).toEqual(findings);
    expect(linter.verify(`// eslint-disable-next-line ${ruleId} -- preserve required wire or union contract\n${source}`, config, { filename })).toEqual([]);
  });

  it(`${preset} preserves explicit quoted wire keys and bracket access`, () => {
    const linter = new Linter();
    const config: Linter.Config = {
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { "@sarj": plugin },
      rules: { "@sarj/require-camelcase-properties": plugin.configs[preset].rules["@sarj/require-camelcase-properties"] },
    };
    expect(linter.verify("const response = { 'event_id': 'known' }; response['event_id'];", config, { filename: "src/wire.ts" })).toEqual([]);
  });
}
