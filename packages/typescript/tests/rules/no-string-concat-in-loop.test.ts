import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-string-concat-in-loop.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-string-concat-in-loop", rule, {
  valid: [
    {
      name: "ignores generated files",
      code: `
        let text = "";
        for (const chunk of chunks) {
          text += chunk;
        }
      `,
      filename: "/repo/src/openapi-gen/requests/core/serverSentEvents.gen.ts",
    },
    {
      name: "allows collecting parts and joining after the loop",
      code: `
        const parts = [];
        for (let i = 0; i < n; i++) {
          parts.push(items[i]);
        }
        const result = parts.join("");
      `,
    },
    {
      name: "ignores numeric accumulators",
      code: `
        let total = 0;
        for (let i = 0; i < n; i++) {
          total += i;
        }
      `,
    },
    {
      name: "ignores numeric accumulators in while loops",
      code: `
        let total = 0;
        while (total < 100) {
          total += 1;
        }
      `,
    },
    {
      name: "ignores string appends outside loops",
      code: `
        let s = "";
        s += "hello";
        s += "world";
      `,
    },
    {
      name: "ignores declarations without an initializer",
      code: `
        for (let i = 0; i < n; i++) {
          let chunk;
          chunk += compute(i);
        }
      `,
    },
    {
      name: "ignores parameters because their runtime type is unknown",
      code: `
        function build(acc) {
          for (let i = 0; i < n; i++) {
            acc += items[i];
          }
          return acc;
        }
      `,
    },
    // `+=` appears in the loop's TEST/UPDATE clause, not its body. Even though
    // `i` is numeric this is doubly safe.
    {
      code: `
        let s = "";
        for (let i = 0; i < n; i += 1) {
          void i;
        }
      `,
    },
    {
      name: "ignores non-literal initializers because their type is unknown",
      code: `
        let s = makeString();
        for (let i = 0; i < n; i++) {
          s += items[i];
        }
      `,
    },
    // Plain `=` assignment (not `+=`) in a loop is not accumulation.
    {
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s = items[i];
        }
      `,
    },
    {
      name: "ignores longhand assignment when the target is absent from the sum",
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s = a + b;
        }
      `,
    },
    {
      name: "allows a fresh per-iteration accumulator collected for a final join",
      code: `
        const textParts = [];
        for (const node of children) {
          if (isSection(node)) {
            let sectionText = \`## \${node.title}\`;
            if (node.body) {
              sectionText += \`\\n\${node.body}\\n\`;
            }
            textParts.push(sectionText);
          }
        }
        return textParts.join("\\n\\n");
      `,
    },
    {
      name: "allows an accumulator declared in the current loop body",
      code: `
        for (const item of items) {
          let line = "";
          line += item.a;
          line += item.b;
          out.push(line);
        }
      `,
    },
    // Declared inside the body of a while loop.
    {
      code: `
        while (queue.length) {
          let s = "";
          s += queue.pop();
          out.push(s);
        }
      `,
    },
    // Declared in the body of the INNER loop — bounded by the inner pass.
    {
      code: `
        for (const row of rows) {
          for (const cell of row) {
            let s = "";
            s += cell;
            out.push(s);
          }
        }
      `,
    },
    {
      name: "allows longhand accumulation on a fresh per-iteration variable",
      code: `
        for (const item of items) {
          let s = "";
          s = s + item;
          out.push(s);
        }
      `,
    },
    {
      name: "ignores unresolved variables because their type is unknown",
      code: `
        for (const item of items) {
          output += item;
        }
      `,
    },
    {
      name: "ignores variables with conflicting redeclarations",
      code: `
        var output = "";
        var output = makeOutput();
        for (const item of items) {
          output += item;
        }
      `,
    },
    {
      name: "ignores member assignments because they are not local variables",
      code: `
        const state = { output: "" };
        for (const item of items) {
          state.output += item;
        }
      `,
    },
    {
      name: "ignores assignments in a loop condition",
      code: `
        let output = "";
        while ((output += next()) !== "done") {
          consume(output);
        }
      `,
    },
  ],
  invalid: [
    {
      name: "reports an outer accumulator once when one loop appends in several branches",
      code: "function f(str) { let result = ''; for (const chr of str) { if (ok(chr)) { result += chr; } else { result += '%'; result += hex(chr); } } return result; }",
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    {
      name: "reports two accumulators separately within one loop",
      code: "function f(xs) { let a = ''; let b = ''; for (const x of xs) { a += x; b += x; } return a + b; }",
      errors: [
        { messageId: "noStringConcatInLoop" },
        { messageId: "noStringConcatInLoop" },
      ],
    },
    {
      name: "reports the same accumulator once in each sibling loop",
      code: "function f(xs, ys) { let s = ''; for (const x of xs) { s += x; } for (const y of ys) { s += y; } return s; }",
      errors: [
        { messageId: "noStringConcatInLoop" },
        { messageId: "noStringConcatInLoop" },
      ],
    },
    {
      name: "reports compound accumulation from an empty string",
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s += items[i];
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    {
      name: "reports compound accumulation from a non-empty string",
      code: `
        let out = "prefix:";
        for (const item of items) {
          out += item;
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Template-literal init.
    {
      code: `
        let s = \`\`;
        for (const key in obj) {
          s += key;
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // String init accumulated in a `while` loop.
    {
      code: `
        let s = "";
        while (hasNext()) {
          s += next();
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // String init accumulated in a `do-while` loop.
    {
      code: `
        let s = "";
        do {
          s += next();
        } while (hasNext());
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // String variable declared in an outer scope, mutated inside a nested loop.
    {
      code: `
        let s = "";
        function build() {
          for (let i = 0; i < n; i++) {
            s += items[i];
          }
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Single-quoted string init.
    {
      code: `
        let csv = '';
        for (let i = 0; i < rows.length; i++) {
          csv += rows[i];
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    {
      name: "reports longhand accumulation",
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s = s + items[i];
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Longhand with the target on the RIGHT of the `+` (`s = prefix + s`).
    {
      code: `
        let s = "";
        for (const item of items) {
          s = item + s;
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Longhand across a chained `+` (`s = s + a + b`).
    {
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s = s + items[i] + ",";
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    {
      name: "reports accumulation into a variable declared outside the loop",
      code: `
        let sectionText = "";
        for (const node of children) {
          if (node.body) {
            sectionText += \`\\n\${node.body}\\n\`;
          }
        }
        return sectionText;
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Declared in the OUTER loop body but accumulated in the INNER loop: it
    // still survives every inner iteration, so the growth is unbounded there.
    {
      code: `
        for (const row of rows) {
          let s = "";
          for (const cell of row) {
            s += cell;
          }
          out.push(s);
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Declared in the loop's INITIALIZER, not its body — one binding for the
    // whole loop, so it accumulates across iterations.
    {
      code: `
        for (let i = 0, s = ""; i < n; i++) {
          s += items[i];
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
  ],
});
