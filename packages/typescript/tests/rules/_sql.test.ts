/** Executable contract for TypeScript SQL extraction and masking. */

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

  it("reports a three-operand concatenation once, not once per fragment", () => {
    expect(dispatched(`db.prepare("SELECT a " + "FROM t " + "WHERE id = ?");`)).toEqual([
      "SELECT a FROM t WHERE id = ?",
    ]);
  });

  it("reports a joined fragment array once, not once per element", () => {
    expect(dispatched(`db.prepare(["INSERT INTO t", "VALUES (?)", "ON CONFLICT DO NOTHING"].join(" "));`)).toEqual([
      "INSERT INTO t VALUES (?) ON CONFLICT DO NOTHING",
      " ",
    ]);
  });

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

  it("substitutes the parameter marker rather than dropping the expression", () => {
    expect(dispatched("db.prepare(`LIMIT ? OFFSET ${n}`);")).toEqual(["LIMIT ? OFFSET ?"]);
  });

  it("preserves an interpolated VALUES payload as a parameter marker", () => {
    expect(dispatched("db.prepare(`INSERT INTO t VALUES ${rows}`);")).toEqual(["INSERT INTO t VALUES ?"]);
  });

  it("refuses a concatenation with a non-string operand", () => {
    expect(sqlTextOf({ type: "Identifier" } as unknown as TSESTree.Node)).toBeNull();
  });
});

describe("stripSqlNoise masks values and comments, in one left-to-right pass", () => {
  it.each([
    ["WHERE p = 'on conflict'", "WHERE p =              "],
    ["SELECT '*' FROM t", "SELECT     FROM t"],
    ["SELECT 1 -- FROM t", "SELECT 1          "],
    ["SELECT 'a--b' FROM t", "SELECT        FROM t"],
    ["SELECT /* FROM x */ 1", "SELECT              1"],
  ])("masks %s", (input, expected) => {
    expect(stripSqlNoise(input)).toBe(expected);
  });

  it("does not let a quote inside a comment swallow following SQL", () => {
    expect(stripSqlNoise("-- don't scan this\nSELECT COUNT(*) FROM t")).toBe(
      "                  \nSELECT COUNT(*) FROM t",
    );
  });

  it("stays inside a literal across a doubled quote", () => {
    expect(stripSqlNoise("WHERE p = 'it''s' AND q = 1")).toBe("WHERE p =         AND q = 1");
  });

  it("stays inside a double-quoted literal across a doubled double quote", () => {
    expect(stripSqlNoise('WHERE p = "a "" JOIN b" AND q = 1')).toBe("WHERE p =               AND q = 1");
  });

  it("preserves newlines inside a masked region", () => {
    expect(stripSqlNoise("SELECT 'a\nb'")).toBe("SELECT   \n  ");
  });
});
