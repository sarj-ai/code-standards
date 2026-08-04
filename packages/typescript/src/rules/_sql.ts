/**
 * @fileoverview _sql — shared extraction of statically-resolvable SQL strings, with literal values and comments neutralised before any keyword scan.
 *
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

/** Mask SQL values and comments without changing text or line lengths. */
export function stripSqlNoise(text: string): string {
  const out = [...text];
  const n = text.length;
  let i = 0;
  while (i < n) {
    const ch = text[i];
    if (ch === "'" || ch === '"') {
      out[i] = " ";
      i += 1;
      while (i < n) {
        const c = text[i];
        if (c === ch) {
          if (i + 1 < n && text[i + 1] === ch) {
            out[i] = " ";
            out[i + 1] = " ";
            i += 2;
            continue;
          }
          out[i] = " ";
          i += 1;
          break;
        }
        if (c !== "\n") {
          out[i] = " ";
        }
        i += 1;
      }
      continue;
    }
    if (ch === "-" && text[i + 1] === "-") {
      while (i < n && text[i] !== "\n") {
        out[i] = " ";
        i += 1;
      }
      continue;
    }
    if (ch === "/" && text[i + 1] === "*") {
      out[i] = " ";
      out[i + 1] = " ";
      i += 2;
      while (i < n && !(text[i] === "*" && text[i + 1] === "/")) {
        if (text[i] !== "\n") {
          out[i] = " ";
        }
        i += 1;
      }
      if (i < n) {
        out[i] = " ";
        out[i + 1] = " ";
        i += 2;
      }
      continue;
    }
    i += 1;
  }
  return out.join("");
}

/** SQL words outside parentheses, after values and comments are masked. */
export function topLevelWords(sql: string): string[] {
  const masked = stripSqlNoise(sql);
  const words: string[] = [];
  let depth = 0;
  let i = 0;
  while (i < masked.length) {
    const char = masked[i];
    if (char === "(") {
      depth += 1;
      i += 1;
      continue;
    }
    if (char === ")") {
      depth = Math.max(0, depth - 1);
      i += 1;
      continue;
    }
    if (depth === 0 && char !== undefined && /[A-Za-z0-9_]/.test(char)) {
      const start = i;
      i += 1;
      while (i < masked.length && /[A-Za-z0-9_]/.test(masked[i] ?? "")) {
        i += 1;
      }
      words.push(masked.slice(start, i).toUpperCase());
      continue;
    }
    i += 1;
  }
  return words;
}

/** Whether consecutive top-level SQL words equal `phrase`. */
export function hasTopLevelPhrase(sql: string, ...phrase: string[]): boolean {
  const wanted = phrase.map((word) => word.toUpperCase());
  const words = topLevelWords(sql);
  return words.some((_, index) => wanted.every((word, offset) => words[index + offset] === word));
}

/** Whether LIMIT/FETCH caps the whole result, excluding ClickHouse LIMIT BY. */
export function hasTopLevelRowCap(sql: string): boolean {
  const words = topLevelWords(sql);
  if (
    words.some(
      (_, index) =>
        (words[index] === "FETCH" && words[index + 1] === "FIRST") ||
        (words[index] === "FETCH" && words[index + 1] === "NEXT"),
    )
  ) {
    return true;
  }
  const boundaries = new Set([
    "FETCH",
    "FOR",
    "FORMAT",
    "INTO",
    "LIMIT",
    "OFFSET",
    "SETTINGS",
    "UNION",
  ]);
  return words.some((word, index) => {
    if (word !== "LIMIT") {
      return false;
    }
    const following = words.slice(index + 1);
    const boundary = following.findIndex((token) => boundaries.has(token));
    const clause = boundary === -1 ? following : following.slice(0, boundary);
    return !clause.includes("BY") && (clause.length === 0 || !["ALL", "NULL"].includes(clause[0] ?? ""));
  });
}

const SQL_CALL_NAMES = new Set([
  "$executeRaw",
  "$queryRaw",
  "all",
  "any",
  "exec",
  "execute",
  "first",
  "get",
  "many",
  "none",
  "one",
  "prepare",
  "query",
  "raw",
  "run",
  "unsafe",
]);
const SQL_TAG_NAMES = new Set(["sql", "SQL"]);

function callableName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return node.name;
  }
  if (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    node.property.type === AST_NODE_TYPES.Identifier
  ) {
    return node.property.name;
  }
  return null;
}

/** Whether a SQL literal is directly consumed by a runtime query API or SQL tag. */
export function isRuntimeSqlNode(node: TSESTree.Node): boolean {
  let current: TSESTree.Node | undefined = node;
  for (let depth = 0; current !== undefined && depth < 8; depth += 1) {
    const parent: TSESTree.Node | undefined = current.parent;
    if (parent === undefined) {
      return false;
    }
    if (parent.type === AST_NODE_TYPES.TaggedTemplateExpression) {
      const name = callableName(parent.tag);
      return name !== null && (SQL_TAG_NAMES.has(name) || SQL_CALL_NAMES.has(name));
    }
    if (
      parent.type === AST_NODE_TYPES.CallExpression &&
      (parent.arguments as readonly TSESTree.Node[]).includes(current)
    ) {
      const name = callableName(parent.callee);
      return name !== null && SQL_CALL_NAMES.has(name);
    }
    if (
      parent.type !== AST_NODE_TYPES.BinaryExpression &&
      parent.type !== AST_NODE_TYPES.ArrayExpression &&
      parent.type !== AST_NODE_TYPES.CallExpression &&
      parent.type !== AST_NODE_TYPES.MemberExpression &&
      parent.type !== AST_NODE_TYPES.ObjectExpression &&
      parent.type !== AST_NODE_TYPES.Property
    ) {
      return false;
    }
    current = parent;
  }
  return false;
}

/** The parameter marker a `${...}` substitution is replaced with before scanning. */
const SUBSTITUTION_MARKER = "?";

/** Reconstruct static SQL literals, templates, concatenations, and fragment arrays. */
export function sqlTextOf(node: TSESTree.Node): string | null {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return typeof node.value === "string" ? node.value : null;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.quasis.map((q) => q.value.cooked ?? q.value.raw).join(SUBSTITUTION_MARKER);
    case AST_NODE_TYPES.TaggedTemplateExpression:
      return sqlTextOf(node.quasi);
    case AST_NODE_TYPES.BinaryExpression: {
      if (node.operator !== "+") {
        return null;
      }
      const left = sqlTextOf(node.left);
      const right = sqlTextOf(node.right);
      return left !== null && right !== null ? left + right : null;
    }
    case AST_NODE_TYPES.ArrayExpression: {
      const parts: string[] = [];
      for (const element of node.elements) {
        if (element === null) {
          return null;
        }
        const part = sqlTextOf(element);
        if (part === null) {
          return null;
        }
        parts.push(part);
      }
      return parts.length > 0 ? parts.join(" ") : null;
    }
    default:
      return null;
  }
}

/** Return whether an array's fragments are consumed together by `.join(...)`. */
function isJoinedFragmentArray(node: TSESTree.ArrayExpression): boolean {
  const parent = node.parent;
  return (
    parent?.type === AST_NODE_TYPES.MemberExpression &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === AST_NODE_TYPES.Identifier &&
    parent.property.name === "join" &&
    parent.parent?.type === AST_NODE_TYPES.CallExpression
  );
}

/** Every string-bearing descendant that a composite node has already absorbed. */
function markConsumed(node: TSESTree.Node, consumed: WeakSet<TSESTree.Node>): void {
  consumed.add(node);
  for (const key of Object.keys(node)) {
    if (key === "parent") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    for (const child of Array.isArray(value) ? value : [value]) {
      if (child !== null && typeof child === "object" && "type" in child) {
        markConsumed(child as TSESTree.Node, consumed);
      }
    }
  }
}

/** Hand each whole, statically resolvable SQL statement to `handler` once. */
export function createSqlListener(
  handler: (sql: string, node: TSESTree.Node) => void,
): TSESLint.RuleListener {
  const consumed = new WeakSet<TSESTree.Node>();

  const visit = (node: TSESTree.Node): void => {
    if (consumed.has(node)) {
      return;
    }
    const text = sqlTextOf(node);
    if (text === null) {
      return;
    }
    markConsumed(node, consumed);
    handler(stripSqlNoise(text), node);
  };

  return {
    BinaryExpression: (node: TSESTree.BinaryExpression): void => {
      visit(node);
    },
    ArrayExpression: (node: TSESTree.ArrayExpression): void => {
      if (isJoinedFragmentArray(node)) {
        visit(node);
      }
    },
    TemplateLiteral: (node: TSESTree.TemplateLiteral): void => {
      visit(node);
    },
    Literal: (node: TSESTree.Literal): void => {
      visit(node);
    },
  };
}
