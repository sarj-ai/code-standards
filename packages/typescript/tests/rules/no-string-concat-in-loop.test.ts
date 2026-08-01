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
    // Generated stream parsers may use template-owned string accumulation.
    {
      code: `
        let text = "";
        for (const chunk of chunks) {
          text += chunk;
        }
      `,
      filename: "/repo/src/openapi-gen/requests/core/serverSentEvents.gen.ts",
    },
    // The prescribed pattern: push parts to an array, join after the loop.
    {
      code: `
        const parts = [];
        for (let i = 0; i < n; i++) {
          parts.push(items[i]);
        }
        const result = parts.join("");
      `,
    },
    // Numeric accumulator — `+=` on a number-initialized variable is fine.
    {
      code: `
        let total = 0;
        for (let i = 0; i < n; i++) {
          total += i;
        }
      `,
    },
    // Numeric accumulator inside a while loop.
    {
      code: `
        let total = 0;
        while (total < 100) {
          total += 1;
        }
      `,
    },
    // String `+=` OUTSIDE any loop — not the antipattern.
    {
      code: `
        let s = "";
        s += "hello";
        s += "world";
      `,
    },
    // String concatenation in a loop but via a fresh local each iteration that
    // is not string-initialized at declaration (no initializer) -> conservative
    // non-flag.
    {
      code: `
        for (let i = 0; i < n; i++) {
          let chunk;
          chunk += compute(i);
        }
      `,
    },
    // LHS is a parameter (type unknown) -> conservative non-flag.
    {
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
    // Variable initialized to a non-literal expression (function call) -> type
    // cannot be confirmed as string -> conservative non-flag.
    {
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
    // Longhand `=` whose RHS is a `+` but the target is NOT an operand
    // (`s = x + y`) — this overwrites, it does not accumulate.
    {
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s = a + b;
        }
      `,
    },
    // From a first-party review regression — one editor-serializer site
    // — the accumulator is DECLARED INSIDE the body, so it is a fresh string
    // every pass, appended to at most once, and the parts are already collected
    // into `textParts` for a `join` after the loop. Nothing quadratic to remove.
    {
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
    // Same shape, minimal: declaration inside the body is bounded growth.
    {
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
    // Longhand `s = s + x` on a body-declared accumulator is equally bounded.
    {
      code: `
        for (const item of items) {
          let s = "";
          s = s + item;
          out.push(s);
        }
      `,
    },
  ],
  invalid: [
    // Corpus: react-router/packages/react-router/lib/server-runtime/cookies.ts:221
    // — one accumulator appended from several branches of ONE loop is ONE defect
    // with ONE fix, so exactly one report is emitted.
    {
      code: "function f(str) { let result = ''; for (const chr of str) { if (ok(chr)) { result += chr; } else { result += '%'; result += hex(chr); } } return result; }",
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Two distinct accumulators in one loop are two distinct defects.
    {
      code: "function f(xs) { let a = ''; let b = ''; for (const x of xs) { a += x; b += x; } return a + b; }",
      errors: [
        { messageId: "noStringConcatInLoop" },
        { messageId: "noStringConcatInLoop" },
      ],
    },
    // Sibling loops over the same accumulator each keep their own report.
    {
      code: "function f(xs, ys) { let s = ''; for (const x of xs) { s += x; } for (const y of ys) { s += y; } return s; }",
      errors: [
        { messageId: "noStringConcatInLoop" },
        { messageId: "noStringConcatInLoop" },
      ],
    },
    // Empty-string init, `for` loop — the canonical antipattern.
    {
      code: `
        let s = "";
        for (let i = 0; i < n; i++) {
          s += items[i];
        }
      `,
      errors: [{ messageId: "noStringConcatInLoop" }],
    },
    // Double-quoted non-empty string init.
    {
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
    // Longhand reassignment `s = s + x` — identical O(n^2) cost to `s += x`.
    {
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
    // TRUE POSITIVE the body-declaration exemption must not swallow: declared
    // OUTSIDE the loop, so it survives every iteration — the real O(n^2) shape.
    // Nearly identical to the exempt serializes-state-to-text case above except
    // for where the `let` sits.
    {
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
