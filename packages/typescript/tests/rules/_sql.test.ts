// vitest: shared-module-graph
/** Executable contract for TypeScript SQL extraction and masking. */

import type { ESTree } from "@oxlint/plugins";
import { ruleReports } from "../_native-rule.js";
import { describe, expect, it } from "vitest";

import { createSqlListener, sqlSingleQuotedRanges, sqlTextOf, stripSqlNoise } from "../../src/rules/_sql.js";

/** Every SQL text the native listener dispatches, including fragment ordering. */
function dispatched(code: string): string[] {
  const found: string[] = [];
  ruleReports({
    meta: { schema: [], messages: {} },
    create: () => createSqlListener((sql) => { found.push(sql); }),
  }, code);
  return found;
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
    expect(sqlTextOf({ type: "Identifier" } as unknown as ESTree.Node)).toBeNull();
  });
});

describe("stripSqlNoise masks values and comments, in one left-to-right pass", () => {
  it("masks nested block comments without swallowing subsequent SQL", () => {
    const sql = "SELECT /* outer /* inner */ hidden */ id FROM users";
    expect(stripSqlNoise(sql)).toBe("SELECT " + " ".repeat("/* outer /* inner */ hidden */".length) + " id FROM users");
  });
  it("preserves UTF-16 offsets and newlines across dollar-quoted Unicode", () => {
    const sql = "SELECT $body$😀\n* FROM$body$, id FROM users";
    const masked = stripSqlNoise(sql);
    expect(masked.length).toBe(sql.length);
    expect(masked.indexOf("\n")).toBe(sql.indexOf("\n"));
    expect(masked.indexOf(", id")).toBe(sql.indexOf(", id"));
    expect(masked).not.toContain("*");
  });

  it("does not mask numbered parameters or dollar-containing identifiers", () => {
    const sql = "SELECT price$tag$ FROM users WHERE id = $1";
    expect(stripSqlNoise(sql)).toBe(sql);
  });

  it("identifies only single-quoted values outside other SQL noise", () => {
    const sql = `SELECT "'identifier'", $$'dollar'$$, 'value' -- 'comment'`;
    expect(sqlSingleQuotedRanges(sql).map(([start, end]) => sql.slice(start, end))).toEqual(["'value'"]);
  });
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
