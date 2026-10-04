import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
  mkdirSync,
} from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { RuleTester } from "oxlint/plugins-dev";
import plugin from "../src/upstream/test.js";
import { createStrictOxlintConfig } from "../dist/config.js";
import { createSelectedOxlintConfig } from "../dist/select-rules.js";

RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});

it("preserves the stock warning authority and ordinary explicit consumer severity", async () => {
  const directory = realpathSync(
    mkdtempSync(path.join(tmpdir(), "sarj-conditional-authority-")),
  );
  try {
    symlinkSync(
      new URL("../../../node_modules", import.meta.url),
      path.join(directory, "node_modules"),
      "dir",
    );
    mkdirSync(path.join(directory, "test"));
    writeFileSync(
      path.join(directory, "test/owner.ts"),
      inTest("if(ready){expect(actual).toBe(1);}"),
    );
    const engine = path.join(
      path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
      "bin/oxlint",
    );
    const config = await createStrictOxlintConfig({
      root: directory,
      typeAware: false,
    });
    expect(config.rules).toMatchObject({
      "sarj-test/no-conditional-expect": "warn",
      "vitest/no-conditional-expect": "off",
      "jest/no-conditional-expect": "off",
    });
    for (const severity of ["warning", "error"] as const) {
      if (severity === "error")
        config.overrides?.push({
          files: ["**/test/**/*.ts"],
          rules: { "sarj-test/no-conditional-expect": "error" },
        });
      const policy = path.join(directory, "policy.json");
      writeFileSync(policy, JSON.stringify(config));
      const selected = await createSelectedOxlintConfig(policy, [
        "sarj-test/no-conditional-expect",
      ]);
      writeFileSync(
        path.join(directory, "selected.json"),
        JSON.stringify(selected),
      );
      const result = spawnSync(
        process.execPath,
        [engine, "--config", "selected.json", "--format=json", "test/owner.ts"],
        { cwd: directory, encoding: "utf8", timeout: 30_000 },
      );
      expect(result).toMatchObject({
        status: severity === "error" ? 1 : 0,
        stderr: "",
      });
      const report = JSON.parse(result.stdout) as {
        diagnostics: Array<{ code: string; severity: string }>;
      };
      expect(report.diagnostics).toMatchObject([
        { code: "sarj-test(no-conditional-expect)", severity },
      ]);
      expect(report.diagnostics).toHaveLength(1);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
const error = { messageId: "conditionalExpect" };
const imports = "import { expect, it } from 'vitest';";
const inTest = (body: string) => `${imports}it('case',()=>{${body}});`;

tester.run(
  "sarj-test/no-conditional-expect",
  plugin.rules["no-conditional-expect"],
  {
    valid: [
      'import { expect, it } from "vitest"; it("accepts either projection", () => { const short = Math.random() > 0.5; const actual = { id: "a", detail: "b" }; const expected = short ? expect.objectContaining({ id: "a" }) : expect.objectContaining(actual); expect(actual).toEqual(expected); });',
      inTest(
        "expect(actual).toEqual(ready ? expect.any(String) : expect.anything());",
      ),
      inTest(
        "expect(actual).toEqual(ready ? expect.arrayContaining([1]) : expect.stringContaining('x'));",
      ),
      inTest(
        "expect(actual).toEqual(ready ? expect.stringMatching(/x/) : expect.closeTo(1,2));",
      ),
      inTest(
        "const expected=ready?expect.schemaMatching(schema):null;expect(actual).toEqual(expected);",
      ),
      inTest(
        "const expected=ready?expect.not.objectContaining({id:1}):null;expect(actual).toEqual(expected);",
      ),
      inTest(
        "const expected=ready?expect['objectContaining']({id:1}):null;expect(actual).toEqual(expected);",
      ),
      inTest(
        "if(ready){expect.extend({custom(){}});}expect(actual).toEqual(expected);",
      ),
      inTest("const result=ready?1:2;expect(result).toBe(1);"),
      inTest("(()=>expect(actual).toBe(1))();"),
      inTest("values.forEach(value=>expect(value).toBe(1));"),
      `${imports}if(ready){it('case',()=>expect(actual).toBe(1));}`,
      `${imports}if(ready){const body=()=>expect(actual).toBe(1);it('case',body);}`,
      `${imports}if(ready){const body=()=>expect(actual).toBe(1);it.each([1])('case',body);}`,
      "import {expect,it as caseOf} from 'vitest';if(ready){const body=()=>expect(actual).toBe(1);caseOf('case',body);}",
      "import * as suite from 'vitest';if(ready){const body=()=>suite.expect(actual).toBe(1);suite.it('case',body);}",
      {
        code: "if(ready){const body=()=>expect(actual).toBe(1);it('case',body);}",
        filename: "/repo/src/owner.test.ts",
      },
      inTest("if(ready){(()=>expect.objectContaining({id:1}))();}"),
      inTest("try{run();}catch{}finally{expect(actual).toBe(1);}"),
      inTest("expect(actual).resolves.not.toBe(null);"),
      inTest(
        "const expect=(value:unknown)=>({toBe(){}});if(ready){expect(actual).toBe(1);}",
      ),
      inTest(
        "function helper(expect:(value:unknown)=>{toBe:()=>void}){if(ready){expect(actual).toBe();}}helper(custom);",
      ),
      "import { expect, it } from './custom';it('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "import type { expect, it } from 'vitest';it('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "import { expect, test } from 'bun:test';test('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "import { expect, test } from '@playwright/test';test('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "import {expect,test} from 'vitest';const spec=test.extend({value:1});spec('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "const {expect,it}=require('vitest');it('case',()=>{if(ready){expect(actual).toBe(1);}});",
      "import {expect,test} from 'vitest';test.beforeEach(()=>{if(ready){expect(actual).toBe(1);}});",
      "import {expect,test} from 'vitest';test.step('case',()=>{if(ready){expect(actual).toBe(1);}});",
      `${imports}function helper(){if(ready){expect(actual).toBe(1);}}`,
      {
        code: "it('case',()=>{if(ready){expect(actual).toBe(1);}});",
        filename: "/repo/src/owner.ts",
      },
      {
        code: "it('case',()=>{if(ready){expect(actual).toBe(1);}});",
        filename: "/repo/tests/owner.ts",
      },
      {
        code: "it('case',()=>{if(ready){expect(actual).toBe(1);}});",
        filename: "/repo/src/owner.e2e.ts",
      },
      {
        code: "const expect=(value:unknown)=>({toBe(){}});it('case',()=>{if(ready){expect(actual).toBe(1);}});",
        filename: "/repo/src/owner.test.ts",
      },
    ],
    invalid: [
      ...[
        "if(ready){expect(actual).toBe(1);}",
        "ready?expect(actual).toBe(1):null;",
        "ready&&expect(actual).toBe(1);",
        "ready||expect(actual).toBe(1);",
        "if(ready){(()=>expect(actual).toBe(1))();}",
        "if(ready){values.forEach(value=>expect(value).toBe(1));}",
        "ready&&(()=>expect(actual).toBe(1))();",
        "ready?(()=>expect(actual).toBe(1))():null;",
        "switch(value){case 1:expect(actual).toBe(1);break;}",
        "switch(value){default:expect(actual).toBe(1);}",
        "try{run();}catch(error){expect(error).toBeInstanceOf(Error);}",
        "run().catch(error=>expect(error).toBeInstanceOf(Error));",
        "run().catch(function(error){expect(error).toBeInstanceOf(Error);});",
        "if(ready){expect.soft(actual).toBe(1);}",
        "if(ready){expect.poll(()=>actual).toBe(1);}",
        "if(ready){expect(actual).resolves.not.toBe(null);}",
        "if(ready){expect(actual)['toBe'](1);}",
        "if(ready){expect(actual)!.toBe(1);}",
        "if(ready){(expect(actual) as any).toBe(1);}",
        "expect.assertions(1);if(ready){expect(actual).toBe(1);}",
      ].map((body) => ({ code: inTest(body), errors: [error] })),
      {
        code: "import {expect as check,it as caseOf} from 'vitest';caseOf('case',()=>{if(ready){check(actual).toBe(1);}});",
        errors: [error],
      },
      {
        code: "import * as suite from 'vitest';suite.it('case',()=>{if(ready){suite.expect(actual).toBe(1);}});",
        errors: [error],
      },
      {
        code: "import {expect,test} from '@jest/globals';test('case',()=>{if(ready){expect(actual).toBe(1);}});",
        errors: [error],
      },
      ...["vite-plus/test", "@effect/vitest"].map((module) => ({
        code: `import {expect,it} from '${module}';it('case',()=>{if(ready){expect(actual).toBe(1);}});`,
        errors: [error],
      })),
      {
        code: `${imports}function helper(){if(ready){expect(actual).toBe(1);}}it('case',()=>helper());`,
        errors: [error],
      },
      {
        code: `${imports}function helper(){if(ready){expect(actual).toBe(1);}}it('case',helper);`,
        errors: [error],
      },
      {
        code: `${imports}const helper=()=>{if(ready){expect(actual).toBe(1);}};it('case',()=>helper());`,
        errors: [error],
      },
      {
        code: `${imports}if(registered){const body=()=>{if(ready){expect(actual).toBe(1);}};it('case',body);}`,
        errors: [error],
      },
      {
        code: `${imports}if(ready){const helper=()=>expect(actual).toBe(1);it('case',()=>helper());}`,
        errors: [error],
      },
      {
        code: `${imports}if(ready){const body=()=>expect(actual).toBe(1);function register(it:(name:string,body:()=>void)=>void){it('custom',body);}register(custom);it('case',()=>body());}`,
        errors: [error],
      },
      {
        code: `${imports}if(ready){const body=()=>expect(actual).toBe(1);{const body=()=>{};it('other',body);}it('case',()=>body());}`,
        errors: [error],
      },
      {
        code: `${imports}if(ready){const body=()=>expect(actual).toBe(1);it(body,()=>body());}`,
        errors: [error],
      },
      {
        code: `${imports}if(ready){let body=()=>expect(actual).toBe(1);const helper=body;body=()=>{};it('case',body);it('helper',()=>helper());}`,
        errors: [error],
      },
      {
        code: `${imports}function helper(){if(ready){expect(actual).toBe(1);}}function nested(){helper();}it('case',()=>nested());`,
        errors: [error],
      },
      ...[
        "/repo/src/owner.test.ts",
        "/repo/src/owner.spec.mts",
        "/repo/__tests__/owner.ts",
        "/repo/test.ts",
      ].map((filename) => ({
        code: "it('case',()=>{if(ready){expect(actual).toBe(1);}});",
        filename,
        errors: [error],
      })),
      {
        code: inTest(
          "if(ready){expect(actual).toBe(1);}ready&&expect(other).toBe(2);",
        ),
        errors: [error, error],
      },
    ],
  },
);
