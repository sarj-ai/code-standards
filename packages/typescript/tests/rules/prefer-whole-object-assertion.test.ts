// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule, { PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION } from "../../src/rules/prefer-whole-object-assertion.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});


const FILENAME = "src/user.test.ts";

RULE_TESTER.run("prefer-whole-object-assertion", rule, {
  valid: [
    ...([
      ["leading exact length", "expect(rows).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["trailing exact length", "expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b'); expect(rows).toHaveLength(2);"],
      ["intentional prefix of a longer collection", "expect(rows).toHaveLength(3); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["length property equality", "expect(rows.length).toBe(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["strict length equality after indices", "expect(rows[0]).toStrictEqual('a'); expect(rows[1]).toStrictEqual('b'); expect(rows['length']).toStrictEqual(2);"],
      ["same nested receiver", "expect(result.rows).toHaveLength(2); expect(result.rows[0]).toEqual('a'); expect(result.rows[1]).toEqual('b');"],
      ["erased receiver and length", "expect((rows as string[])).toHaveLength((2 as const)); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["imported length assertion alias", "import {expect as verify} from 'vitest'; verify(rows).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["explanation between length and prefix", "expect(rows).toHaveLength(3);\n// The third row is deliberately opaque.\nexpect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["type-only expectation is not a runtime assertion", "import type {expect} from 'vitest'; expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
    ] as const).map(([name, code]) => ({name, code, filename: FILENAME})),
    { name: "assigned expectation global is not the runner API", filename: FILENAME, languageOptions: {globals: {expect: "writable"}}, code: "expect = custom; expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');" },
    { name: "keeps wrapped dynamic expected values separate", filename: FILENAME, code: 'expect(user.id).toBe((expectedId as number)); expect(user.name).toBe((expectedName as string));' },
    { name: "preserves intervening effects with wrapped expected values", filename: FILENAME, code: 'expect(user.id).toBe((1 as const)); update(); expect(user.name).toBe(("Ada" as const));' },

    {
      name: "preserves dotted absent-property assertions",
      filename: FILENAME,
      code: 'expect(user.name).toBe("Ada"); expect(user.deletedAt).toBeUndefined();',
    },
    {
      name: "preserves bracket absent-property assertions",
      filename: FILENAME,
      code: 'expect(user["first-name"]).toBeUndefined(); expect(user["last-name"]).toBeUndefined();',
    },
    {
      name: "does not introduce property presence into a mixed literal run",
      filename: FILENAME,
      code: 'expect(user.name).toBe("Ada"); expect(user["deleted-at"]).toBeUndefined(); expect(user.active).toBe(true);',
    },
    { name: "preserves a locally supplied custom expect", filename: FILENAME, code: "function check(expect: CustomAssertion) { expect(obj.a).toBe(1); expect(obj.b).toBe(2); }" },
    { name: "preserves a non-runner imported expect", filename: FILENAME, code: "import { expect } from './custom'; expect(obj.a).toBe(1); expect(obj.b).toBe(2);" },
    { name: "accepts the documented whole-object assertion", filename: FILENAME, code: PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION.examples[0].files[0].source },

    { filename: FILENAME, code: `expect(obj).toMatchObject({ a: 1, b: 2 });` },

    { filename: FILENAME, code: `expect(obj.a).toBe(1);` },

    {
      filename: FILENAME,
      code: `
        expect(obj1.a).toBe(1);
        expect(obj2.b).toBe(2);
      `,
    },


    {
      filename: "src/user.ts",
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
    },
    {
      filename: "src/generated/user.test.ts",
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(mockRedis.get).toHaveBeenCalledWith("test:1");
        expect(mockRedis.set).toHaveBeenCalledWith("test:1", 2);
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(obj.name).toContain("ab");
        expect(obj.items).toHaveLength(3);
        expect(obj.n).toBeGreaterThan(5);
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect(cal.embedRenderStartTime).toBeGreaterThan(0);
        expect(cal.embedConfig).toBeDefined();
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(utils.container).toHaveTextContent("a:success");
        expect(utils.container).toHaveTextContent("b:success");
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBeDefined();
        expect(obj.c).toBe(3);
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.a).toBe(2);
      `,
    },
    {
      name: "ignores overlapping leaf paths",
      filename: FILENAME,
      code: `
        expect(config.tts).toBeNull();
        expect(config.tts.model).toBe("voice");
      `,
    },
    {
      name: "ignores dynamic computed path segments",
      filename: FILENAME,
      code: `
        expect(config[provider].model).toBe("voice");
        expect(config[provider].region).toBe("me-central2");
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(client.auth).toBe(auth);
        expect(client.zoho).toBe(zoho);
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect(res.body).toEqual({ ok: true });
        expect(res.headers).toEqual({ "content-type": "application/json" });
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(results.length).toBe(1);
        expect(results.size).toBe(1);
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect(results.length).toBe(2);
        expect(results[0]).toEqual("a");
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(getUser().a).toBe(1);
        expect(getUser().b).toBe(2);
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(obj?.a).toBe(1);
        expect(obj?.b).toBe(2);
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(obj.a).not.toBe(1);
        expect(obj.b).not.toBe(2);
      `,
    },
    {
      name: "ignores awaited expect calls",
      filename: FILENAME,
      code: `
        await expect(obj.a).toBe(1);
        await expect(obj.b).toBe(2);
      `,
    },
    {
      name: "ignores resolves and rejects chains",
      filename: FILENAME,
      code: `
        expect(obj.a).resolves.toBe(1);
        expect(obj.b).resolves.toBe(2);
        expect(obj.c).rejects.toThrow("nope");
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect.soft(obj.a).toBe(1);
        expect.soft(obj.b).toBe(2);
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect(obj.a).to.equal(1);
        expect(obj.b).to.equal(2);
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(rows[1]).toEqual("a");
        expect(rows[2]).toEqual("b");
      `,
    },
    {
      name: "ignores indexed runs with gaps",
      filename: FILENAME,
      code: `
        expect(rows[0]).toEqual("a");
        expect(rows[2]).toEqual("c");
      `,
    },
    {
      name: "ignores indexed assertions separated by another statement",
      filename: FILENAME,
      code: `
        expect(rows[0]).toEqual("a");
        observe(rows);
        expect(rows[1]).toEqual("b");
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(rows[0]).toBe(a);
        expect(rows[1]).toBe(b);
      `,
    },

    {
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(1);
        doSomething();
        expect(obj.b).toBe(2);
      `,
    },






    {
      filename: FILENAME,
      code: `
        foo(obj.a).toBe(1);
        foo(obj.b).toBe(2);
      `,
    },
    {
      filename: FILENAME,
      code: `
        expect(obj.a, "a must be 1").toBe(1);
        expect(obj.b, "b must be 2").toBe(2);
      `,
    },





    {
      filename: FILENAME,
      code: `
        expect(a?.b.c).toBe(1);
        expect(a?.b.d).toBe(2);
      `,
    },



    {
      filename: FILENAME,
      code: `
        expect(m[k].c).toBe(1);
        expect(m[k].d).toBe(2);
      `,
    },



    {
      filename: FILENAME,
      code: "\n        expect(obj.a).toBe(`x${y}`);\n        expect(obj.b).toBe(`z${y}`);\n      ",
    },



    {
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(!flag);
        expect(obj.b).toBe(!other);
      `,
    },
    {
      name: "does not replace regular expression identity with structural comparison",
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(/a/);
        expect(obj.b).toBe(/b/);
      `,
    },









    {
      filename: FILENAME,
      code: `
        expect(rows[0.5]).toEqual("a");
        expect(rows[1]).toEqual("b");
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(rows[-1]).toEqual("a");
        expect(rows[1]).toEqual("b");
      `,
    },


    {
      filename: FILENAME,
      code: `
        expect(rows[0]).toEqual("a");
        expect(rows[1]).toStrictEqual("b");
      `,
    },
  ],
  invalid: [
    ...([
      ["different collection length", "expect(other).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["negated length is not exact cardinality", "expect(rows).not.toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["dynamic length remains manual", "expect(rows).toHaveLength(count); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["an intervening mutation separates length observation", "expect(rows).toHaveLength(2); rows.push('c'); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["a later mutation separates length observation", "expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b'); rows.pop(); expect(rows).toHaveLength(2);"],
      ["custom length helper is not runner proof", "const verify = custom; verify(rows).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["foreign length helper is not runner proof", "import {verify} from './helpers'; verify(rows).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
      ["conditional length check is not adjacent proof", "if (ready) expect(rows).toHaveLength(2); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');"],
    ] as const).map(([name, code]) => ({name, code, filename: FILENAME, output: null, errors: [{messageId: "assertArrayOnce" as const}]})),
    { name: "retains literal expected values through const assertions", filename: FILENAME, code: 'expect(user.id).toBe((1 as const)); expect(user.name).toBe(("Ada" as const));', errors: [{ messageId: "combineAssertions" }] },
    { name: "recognizes static computed matchers in a literal property run", filename: FILENAME, code: 'expect(user.id)["toBe"](1); expect(user.name)["toBe"]("Ada");', errors: [{ messageId: "combineAssertions" }] },

    {
      name: "renders a non-identifier common prefix as bracket access",
      filename: FILENAME,
      code: 'expect(obj["account-id"]["first-name"]).toBe("Ada"); expect(obj["account-id"]["last-name"]).toBe("Lovelace");',
      errors: [{ messageId: "combineAssertions", data: { count: "2", receiver: 'obj["account-id"]' } }],
    },
    {
      name: "renders an indexed common receiver without invalid dotted syntax",
      filename: FILENAME,
      code: 'expect(obj[0].a).toBe(1); expect(obj[0].b).toBe(2);',
      errors: [{ messageId: "combineAssertions", data: { count: "2", receiver: 'obj["0"]' } }],
    },
    {
      name: "combines distinct literal leaf paths under their pure common ancestor",
      filename: FILENAME,
      code: `expect(config.tts.model).toBe("eleven");
expect(config.tts.voice).toBe("sarah");
expect(config.stt.model).toBe("nova");`,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      name: "reports but does not autofix distinct leaf paths across a rationale comment",
      filename: FILENAME,
      code: `expect(config.tts.model).toBe("eleven");
// STT intentionally uses a separate provider.
expect(config.stt.model).toBe("nova");`,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },
    { name: "reports the documented member assertion run without rewriting it", filename: FILENAME, code: PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION.examples[1].files[0].source, output: null, errors: [{ messageId: "combineAssertions" }] },


    {
      filename: FILENAME,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },



    {
      filename: FILENAME,
      code: `
        expect(user.id).toBe(1);
        expect(user.name).toEqual("ada");
        expect(user.active).toStrictEqual(true);
        expect(user.deletedAt).toBeNull();
      `,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },

    {
      filename: FILENAME,
      code: `
        expect(res.body.user.id).toBe(1);
        expect(res.body.user.name).toBe("ada");
      `,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      name: "merges a property run on a literal computed receiver",
      filename: FILENAME,
      code: `
        expect(registry["user"].id).toBe(1);
        expect(registry["user"].active).toBe(true);
      `,
      output:
        null,
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      name: "treats inherited names other than __proto__ as ordinary keys",
      filename: FILENAME,
      code: `
        expect(obj.constructor).toBe(null);
        expect(obj.toString).toBe("custom");
      `,
      output:
        null,
      errors: [{ messageId: "combineAssertions" }],
    },


    {
      filename: FILENAME,
      code: `
        expect(bodies[0]).toEqual("a");
        expect(bodies[1]).toEqual({ slug: "b" });
      `,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },

    {
      filename: FILENAME,
      code: `
        expect(res[0][0]).toStrictEqual("slug");
        expect(res[0][1]).toStrictEqual({ slug: "b" });
      `,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },








    {
      filename: FILENAME,
      code: `it("returns the user", () => {
  expect(obj.a).toBe(1);
  expect(obj.b).toBe(2);
});`,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      filename: FILENAME,
      code: `describe("rows", () => {
  it("returns them in order", () => {
    expect(rows[0]).toEqual("a");
    expect(rows[1]).toEqual("b");
  });
});`,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },




    {
      filename: FILENAME,
      code: `
        expect(this.a).toBe(1);
        expect(this.b).toBe(2);
      `,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },


    {
      filename: FILENAME,
      code: "\n        expect(obj.a).toBe(`x`);\n        expect(obj.b).toBe(`y`);\n      ",
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },


    {
      filename: FILENAME,
      code: `
        expect(point.x).toBe(-1);
        expect(point.y).toBe(+2);
      `,
      output: null,
      errors: [{ messageId: "combineAssertions" }],
    },
  ],
});











describe("prefer-whole-object-assertion autofix soundness", () => {
  const linter = new Linter();
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { local: { rules: { "prefer-whole-object-assertion": rule } } },
      rules: { "local/prefer-whole-object-assertion": "error" },



      linterOptions: { reportUnusedDisableDirectives: "off" },
    },
  ] as unknown as Linter.Config[];

  const fix = (code: string): string => linter.verifyAndFix(code, config, FILENAME).output;

  it("preserves absent-property semantics instead of adding a presence assertion", () => {
    const user: { name: string; missing?: string } = { name: "Ada" };
    expect(user.missing).toBeUndefined();
    expect(() => expect(user).toMatchObject({ name: "Ada", missing: undefined })).toThrow();
    const code = `expect(user.name).toBe("Ada");\nexpect(user.missing).toBeUndefined();`;
    expect(fix(code)).toBe(code);
  });

  it("does not rewrite repeated reads of an observable getter", () => {
    const code = `let reads = 0;
      const user = { get child() { return { id: ++reads, name: String(reads) }; } };
      expect(user.child.id).toBe(1);
      expect(user.child.name).toBe("2");`;
    expect(fix(code)).toBe(code);
    expect(rule.meta.fixable).toBeUndefined();
  });

  it("leaves substring, length and ordering matchers alone", () => {
    const code = `expect(o.name).toContain("ab");\nexpect(o.items).toHaveLength(3);\nexpect(o.n).toBeGreaterThan(5);\n`;
    expect(fix(code)).toBe(code);
  });

  it("leaves spy assertions alone", () => {
    const code = `expect(m.get).toHaveBeenCalledWith("k");\nexpect(m.set).toHaveBeenCalledWith("k", 1);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never emits a duplicate object key", () => {
    const code = `expect(o.a).toBe(1);\nexpect(o.a).toBe(2);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never downgrades toBe on a non-literal to structural equality", () => {
    const code = `expect(c.auth).toBe(auth);\nexpect(c.zoho).toBe(zoho);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never rewrites an indexed run, which would add a length assertion", () => {
    const code = `expect(bodies[0]).toEqual("a");\nexpect(bodies[1]).toEqual("b");\n`;
    expect(fix(code)).toBe(code);
  });

  it("preserves a complete length contract with intentionally partial element observations", () => {
    const rows = ["a", "b", "opaque"];
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual("a");
    expect(rows[1]).toEqual("b");
    expect(() => expect(rows).toEqual(["a", "b"])).toThrow();
    const code = "expect(rows).toHaveLength(3); expect(rows[0]).toEqual('a'); expect(rows[1]).toEqual('b');";
    expect(linter.verify(code, config, FILENAME)).toEqual([]);
    expect(fix(code)).toBe(code);
  });








  describe("__proto__ is a prototype setter, not a key", () => {
    it("Object.keys drops it — the language fact the guard rests on", () => {
      expect(Object.keys({ __proto__: null, b: 2 })).toStrictEqual(["b"]);

      expect(Object.keys({ "__proto__": null, b: 2 })).toStrictEqual(["b"]);
    });

    it("the merged form would stop checking the prototype at all", () => {
      const received: Record<string, unknown> = Object.create({ marker: 1 }) as Record<string, unknown>;
      received["b"] = 2;

      expect(Object.getPrototypeOf(received)).not.toBeNull();


      expect(received["b"]).toBe(2);
    });

    it("is never merged or rewritten", () => {
      const code = `expect(o.__proto__).toBe(null);\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("preserves the entire run when it includes a prototype assertion", () => {
      expect(fix(`expect(o.__proto__).toBe(null);\nexpect(o.b).toBe(2);\nexpect(o.c).toBe(3);\n`)).toBe(
        `expect(o.__proto__).toBe(null);\nexpect(o.b).toBe(2);\nexpect(o.c).toBe(3);\n`,
      );
    });
  });






  describe("comments inside the run", () => {
    it("does not orphan a leading comment", () => {
      const code = `expect(o.a).toBe(1);\n// b matters because the API returns it second\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("does not strand an eslint-disable directive", () => {
      const code = `expect(o.a).toBe(1);\n// eslint-disable-next-line local/prefer-whole-object-assertion\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("does not swallow a comment inside a merged statement", () => {
      const code = `expect(o.a /* the a */).toBe(1);\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("preserves the source when comments sit outside the span", () => {
      expect(fix(`// setup\nexpect(o.a).toBe(1);\nexpect(o.b).toBe(2); // done\n`)).toBe(
        `// setup\nexpect(o.a).toBe(1);\nexpect(o.b).toBe(2); // done\n`,
      );
    });
  });

  it("leaves ordinary property runs available for manual review", () => {
    expect(fix(`expect(o.a).toBe(1);\nexpect(o.b).toBe(2);\n`)).toBe(
      `expect(o.a).toBe(1);\nexpect(o.b).toBe(2);\n`,
    );
  });
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "member-run-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/user.test.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/user.test.ts",
        "source": "expect(user[\"id\"])[\"toBe\"](1);\nexpect(user[\"name\"])[\"toBe\"]('Ada');"
      }
    ]
  },
  {
    "id": "member-run-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/user.test.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/user.test.ts",
        "source": "expect(user[auditDynamicMember])[auditDynamicMember](1);\nexpect(user[auditDynamicMember])[auditDynamicMember]('Ada');"
      }
    ]
  }
] } });
});
