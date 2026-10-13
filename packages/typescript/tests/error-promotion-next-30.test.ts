import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import plugin from "../src/index.js";

const PROMOTIONS = [
  {
    rule: "prefer-nominal-id-types",
    filename: "src/boundary.ts",
    source: "function load(accountId: string, invoiceId: string) {}",
  },
  {
    rule: "require-explicit-service-contract",
    filename: "src/service.ts",
    source: "interface Worker { run(): void }\nclass Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
  },
  {
    rule: "require-interface-for-exported-class",
    filename: "src/boundary.ts",
    source: "export class Reader { read() { return 'value'; } }",
  },
  {
    rule: "no-json-stringify-object-equality",
    filename: "src/boundary.ts",
    source: "const same = JSON.stringify({a: 1, b: 2}) === JSON.stringify({b: 2, a: 1});",
  },
  {
    rule: "no-duplicate-test-case",
    filename: "src/boundary.test.ts",
    source: "import { it } from 'vitest';\nit.each([[1, 2], [1, 2]])('%s', (input, expected) => {});",
  },
] as const;

for (const preset of ["recommended", "strict"] as const) {
  it.each(PROMOTIONS)(`${preset} blocks $rule and supports its exact local exception`, ({ rule, filename, source }) => {
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
    const lines = source.split("\n");
    lines.splice(findings[0].line - 1, 0, `// eslint-disable-next-line ${ruleId} -- required compatibility boundary`);
    expect(linter.verify(lines.join("\n"), config, { filename })).toEqual([]);
  });
}
