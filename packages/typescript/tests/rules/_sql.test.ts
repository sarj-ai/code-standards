/**
 * `_sql.ts` is consumed by every SQL-aware store rule and had no tests of its own.
 *
 * `createSqlListener`'s contract is "each WHOLE statement, exactly once". The
 * "exactly once" half is invisible to the consuming rules' tests, because every
 * fixture in them concatenates exactly two fragments — and with two fragments a
 * `markConsumed` that only marks the node and its direct children still marks
 * everything. Three fragments is the smallest case that separates a recursive
 * mark from a shallow one, and with a shallow mark the inner concatenation's
 * string literals are visited again and the same statement is reported twice.
 *
 * The listener is exercised through a synthetic rule rather than a real one so
 * the assertion is on the helper's dispatch, not on any rule's predicate.
 */

import * as tsParser from "@typescript-eslint/parser";
import { type TSESTree } from "@typescript-eslint/utils";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createSqlListener, sqlTextOf, stripSqlNoise } from "../../src/rules/_sql.js";

const RULE_ID = "probe/sql";

/** Every SQL text `createSqlListener` hands a rule, in dispatch order. */
function dispatched(code: string): string[] {
  const linter = new Linter();
  const messages = linter.verify(code, {
    plugins: {
      probe: {
        rules: {
          sql: {
            meta: { schema: [], type: "problem", messages: { sql: "{{sql}}" } },
            create: (context: {
              report: (d: { node: TSESTree.Node; messageId: string; data: { sql: string } }) => void;
            }) =>
              createSqlListener((sql, node) => {
                context.report({ node, messageId: "sql", data: { sql } });
              }),
          } as never,
        },
      },
    },
    languageOptions: { parser: tsParser as never },
    rules: { [RULE_ID]: "error" },
  } as never);
  const noise = messages.filter((message) => message.ruleId !== RULE_ID);
  expect(noise, `harness produced non-rule messages: ${JSON.stringify(noise)}`).toEqual([]);
  return messages.map((message) => message.message);
}

describe("createSqlListener hands each whole statement over exactly once", () => {
  it("reports a two-operand concatenation once", () => {
    expect(dispatched(`db.prepare("SELECT a " + "FROM t");`)).toEqual(["SELECT a FROM t"]);
  });

  // The mutation this kills: `markConsumed` marking only the node and its
  // direct children. With two operands that is indistinguishable from a full
  // recursive mark; with three, the inner `BinaryExpression`'s own literals
  // escape and the statement is reported again, once per surviving fragment.
  it("reports a three-operand concatenation once, not once per fragment", () => {
    expect(dispatched(`db.prepare("SELECT a " + "FROM t " + "WHERE id = ?");`)).toEqual([
      "SELECT a FROM t WHERE id = ?",
    ]);
  });

  // The trailing `" "` is the separator argument of `.join`, reached by the
  // `Literal` visitor in its own right. Rules see it as a one-space "statement"
  // and no keyword scan matches it, so it is harmless — but it is part of the
  // helper's observable dispatch and is asserted rather than filtered away.
  it("reports a joined fragment array once, not once per element", () => {
    expect(dispatched(`db.prepare(["INSERT INTO t", "VALUES (?)", "ON CONFLICT DO NOTHING"].join(" "));`)).toEqual([
      "INSERT INTO t VALUES (?) ON CONFLICT DO NOTHING",
      " ",
    ]);
  });

  // An array of strings that is NOT glued together is not one statement, so its
  // elements are separate texts rather than a single joined one.
  it("does not treat an unjoined array as one statement", () => {
    expect(dispatched(`const names = ["a", "b"];`)).toEqual(["a", "b"]);
  });
});

describe("sqlTextOf reconstructs the shapes TypeScript SQL actually takes", () => {
  it.each([
    ['db.prepare("SELECT 1");', ["SELECT 1"]],
    ["db.prepare(`SELECT ${col} FROM t`);", ["SELECT ? FROM t"]],
    ["sql`SELECT 1`;", ["SELECT 1"]],
  ])("reads %s", (code, expected) => {
    expect(dispatched(code)).toEqual(expected);
  });

  // A substitution becomes the parameter marker rather than vanishing, so
  // `LIMIT ? OFFSET ${n}` still reads as a pagination clause.
  it("substitutes the parameter marker rather than dropping the expression", () => {
    expect(dispatched("db.prepare(`LIMIT ? OFFSET ${n}`);")).toEqual(["LIMIT ? OFFSET ?"]);
  });

  it("refuses a concatenation with a non-string operand", () => {
    expect(sqlTextOf({ type: "Identifier" } as unknown as TSESTree.Node)).toBeNull();
  });
});

describe("stripSqlNoise masks values and comments, in one left-to-right pass", () => {
  // The precedence is the point: a `--` inside a string literal is string data,
  // and a quote inside a comment is not the start of a literal.
  it.each([
    ["WHERE p = 'on conflict'", "WHERE p =              "],
    ["SELECT '*' FROM t", "SELECT     FROM t"],
    ["SELECT 1 -- FROM t", "SELECT 1          "],
    ["SELECT 'a--b' FROM t", "SELECT        FROM t"],
    ["SELECT /* FROM x */ 1", "SELECT              1"],
  ])("masks %s", (input, expected) => {
    expect(stripSqlNoise(input)).toBe(expected);
  });

  // A doubled quote is SQL's in-string escape, so the scanner must stay inside
  // the literal rather than closing and reopening it.
  it("stays inside a literal across a doubled quote", () => {
    expect(stripSqlNoise("WHERE p = 'it''s' AND q = 1")).toBe("WHERE p =         AND q = 1");
  });

  // Newlines survive so the masked text keeps its line numbering.
  it("preserves newlines inside a masked region", () => {
    expect(stripSqlNoise("SELECT 'a\nb'")).toBe("SELECT   \n  ");
  });
});
