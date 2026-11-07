/**
 * @fileoverview duplicate-test-body — sibling tests with the same substantial body are copy-paste cases that should be parameterized.
 *
 * Port of the 18.x `duplicate-test-body` rule. The fingerprint is built as a
 * string in one pass instead of a normalized object tree passed to
 * `JSON.stringify`; it produces the same JSON text, so equal fingerprints match
 * exactly as before. The inline-snapshot check rides along that pass over the
 * test body instead of walking it a second time. Every check that rejects a call
 * is pure, so the cheap ones run first. `duplicateTestBodyCandidate` is exported
 * for repeated-static-call-cases, as in the original.
 */

import { defineRule, type Context, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { staticString } from "../utils/static-string.js";
import { acceptedTestFrameworkName } from "../utils/test-mock-provenance.js";

type TestFunction = ESTree.Function | ESTree.ArrowFunctionExpression;

export interface DuplicateTestBodyCandidate {
  readonly body: TestFunction;
  readonly container: ESTree.Program | ESTree.BlockStatement;
  readonly fingerprint: string;
}

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const ASSERTION_NAMES: ReadonlySet<string> = new Set(["assert", "expect"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const INLINE_SNAPSHOT_MATCHERS: ReadonlySet<string> = new Set(["toMatchInlineSnapshot", "toThrowErrorMatchingInlineSnapshot"]);
const OMITTED_AST_KEYS: ReadonlySet<string> = new Set(["end", "loc", "parent", "range", "raw", "start"]);
const MIN_STATEMENTS = 3;
const MAX_NORMALIZED_STRING_LENGTH = 64;

function staticMemberName(member: ESTree.MemberExpression): string | null {
  const property = member.property as Node;
  if (!member.computed && property.type === "Identifier") return property.name;
  if (member.computed && property.type === "Literal" && typeof property.value === "string") return property.value;
  return null;
}

function isTypeOnlyContractStatement(statement: Node): boolean {
  return statement.type === "TSTypeAliasDeclaration" || statement.type === "TSInterfaceDeclaration";
}

function normalizedStringLiteral(value: string): string {
  return value.includes("\n") || value.length > MAX_NORMALIZED_STRING_LENGTH
    ? `["Literal","string",${JSON.stringify(value)}]`
    : `["Literal","string"]`;
}

interface ShapeField {
  readonly key: string;
  /** `"key":`, the JSON text that precedes the field's value. */
  readonly prefix: string;
  /** The original keeps literal values under property names and member properties. */
  readonly preserveLiteral: boolean;
}

interface Shape {
  readonly keys: readonly string[];
  readonly fields: readonly ShapeField[];
}

// Oxlint builds each node type with the same keys in the same order, so the sorted, filtered field list
// is computed once per key list instead of sorting every node's keys.
const SHAPES = new Map<unknown, Shape[]>();

// The source being linted; set by `duplicateTestBodyCandidate` before any use.
let sourceCode: SourceCode;
// Set while normalizing test statements; the walk stops once it finds an inline snapshot.
let detectInlineSnapshot = false;
let inlineSnapshot = false;

function frameworkName(identifier: ESTree.IdentifierReference, kind: "test" | "assertion", accepted: ReadonlySet<string>): string | null {
  return acceptedTestFrameworkName(sourceCode, identifier, kind, accepted);
}

function isAssertionCall(node: ESTree.CallExpression): boolean {
  const root = rootIdentifier(node.callee);
  return root !== null && frameworkName(root, "assertion", ASSERTION_NAMES) !== null;
}

function rootIdentifier(callee: Node): ESTree.IdentifierReference | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return callee as ESTree.IdentifierReference;
  if (callee.type === "MemberExpression") return rootIdentifier(callee.object);
  if (callee.type === "CallExpression") return rootIdentifier(callee.callee);
  if (callee.type === "TaggedTemplateExpression") return rootIdentifier(callee.tag);
  return null;
}

function isAssertionStatement(statement: Node): boolean {
  return statement.type === "ExpressionStatement" && statement.expression.type === "CallExpression" &&
    isAssertionCall(statement.expression);
}

/** JSON text of the original's normalized AST; `undefined` where `JSON.stringify` drops the value. */
function normalized(value: unknown, preserveLiteral: boolean): string | undefined {
  if (inlineSnapshot) return "";
  if (Array.isArray(value)) return normalizedArray(value, preserveLiteral);
  if (value === null) return "null";
  if (typeof value !== "object") return JSON.stringify(typeof value === "bigint" ? value.toString() : value);
  return normalizedNode(value as Node, preserveLiteral);
}

function normalizedArray(items: readonly unknown[], preserveLiteral: boolean): string {
  const parts: string[] = [];
  for (const item of items) parts.push(normalized(item, preserveLiteral) ?? "null");
  return `[${parts.join(",")}]`;
}

function normalizedNode(node: Node, preserveLiteral: boolean): string {
  switch (node.type) {
    case "TSAsExpression": {
      const literal = constAssertionLiteral(node);
      if (literal !== null) return normalizedNode(literal, preserveLiteral);
      break;
    }
    case "TemplateLiteral": {
      const text = staticString(node);
      if (text !== null) {
        return preserveLiteral ? `{"type":"Literal","value":${JSON.stringify(text)}}` : normalizedStringLiteral(text);
      }
      break;
    }
    case "Literal":
      if (!preserveLiteral) return normalizedLiteral(node);
      break;
    case "MemberExpression":
      if (detectInlineSnapshot && INLINE_SNAPSHOT_MATCHERS.has(staticMemberName(node) ?? "")) {
        inlineSnapshot = true;
      }
      break;
    default:
      break;
  }
  return normalizedRecord(node as unknown as Record<string, unknown>, preserveLiteral);
}

function normalizedLiteral(node: Extract<Node, { type: "Literal" }>): string {
  if ("regex" in node) {
    const regex = node.regex;
    return JSON.stringify(["Literal", "regex", regex.pattern, regex.flags]);
  }
  const value = node.value;
  if (typeof value === "string") return normalizedStringLiteral(value);
  if (value === null) return `["Literal","null"]`;
  return `["Literal",${JSON.stringify(typeof value)}]`;
}

function constAssertionLiteral(node: ESTree.TSAsExpression): Node | null {
  const annotation = node.typeAnnotation;
  if (annotation.type !== "TSTypeReference" ||
    annotation.typeName.type !== "Identifier" || annotation.typeName.name !== "const") return null;
  const expression = node.expression;
  if (expression.type === "Literal") return expression;
  return expression.type === "TemplateLiteral" && expression.expressions.length === 0 ? expression : null;
}

function normalizedRecord(record: Record<string, unknown>, preserveLiteral: boolean): string {
  const preserveAll = preserveLiteral ||
    record["type"] === "CallExpression" && isAssertionCall(record as unknown as ESTree.CallExpression);
  const parts: string[] = [];
  for (const field of recordShape(record)) {
    const item = normalized(record[field.key], preserveAll || field.preserveLiteral);
    if (item !== undefined) parts.push(`${field.prefix}${item}`);
  }
  return `{${parts.join(",")}}`;
}

function recordShape(record: Record<string, unknown>): readonly ShapeField[] {
  const keys = Object.keys(record);
  const type = record["type"];
  let shapes = SHAPES.get(type);
  if (shapes === undefined) {
    shapes = [];
    SHAPES.set(type, shapes);
  }
  for (const shape of shapes) if (sameKeys(shape.keys, keys)) return shape.fields;
  const namesProperty = type === "Property" || type === "MethodDefinition" || type === "PropertyDefinition";
  const fields = keys.filter((key) => !OMITTED_AST_KEYS.has(key)).sort().map((key) => ({
    key,
    prefix: `${JSON.stringify(key)}:`,
    preserveLiteral: key === "key" && namesProperty || key === "property" && type === "MemberExpression",
  }));
  shapes.push({ keys, fields });
  return fields;
}

function sameKeys(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index++) if (left[index] !== right[index]) return false;
  return true;
}

// duplicate-test-body and repeated-static-call-cases ask about the same test calls, so remember the current file's answers.
let candidatesAst: ESTree.Program | null = null;
let candidates = new Map<ESTree.CallExpression, DuplicateTestBodyCandidate | null>();

/** A sibling test call's body and fingerprint, or null when the call is not a substantial test. */
export function duplicateTestBodyCandidate(call: ESTree.CallExpression, source: SourceCode): DuplicateTestBodyCandidate | null {
  if (source.ast !== candidatesAst) {
    candidatesAst = source.ast;
    candidates = new Map();
  }
  let candidate = candidates.get(call);
  if (candidate === undefined) {
    candidate = newCandidate(call, source);
    candidates.set(call, candidate);
  }
  return candidate;
}

function newCandidate(call: ESTree.CallExpression, source: SourceCode): DuplicateTestBodyCandidate | null {
  const statement = call.parent;
  if (statement.type !== "ExpressionStatement") return null;
  const container = statement.parent;
  if (container.type !== "Program" && container.type !== "BlockStatement") return null;
  sourceCode = source;
  const candidate = testBody(call);
  if (candidate === null) return null;
  const text = fingerprint(candidate.body, candidate.signature);
  return text === null ? null : { body: candidate.body, container, fingerprint: text };
}

function fingerprint(body: TestFunction, signature: string): string | null {
  const statements = (body.body as ESTree.BlockStatement).body as Node[];
  if (statements.some(isTypeOnlyContractStatement) || statements.every(isAssertionStatement)) return null;
  // Reset before the params too: a previous call, possibly in a previous
  // file, may have stopped on an inline snapshot.
  inlineSnapshot = false;
  const params = normalized(body.params, false);
  detectInlineSnapshot = true;
  const normalizedStatements = normalized(statements, false);
  detectInlineSnapshot = false;
  if (inlineSnapshot) return null;
  const comments = sourceCode.getCommentsInside(body.body as Node).map((comment) => JSON.stringify([comment.type, comment.value]));
  return `[${JSON.stringify(signature)},${JSON.stringify(body.async) ?? "null"},${JSON.stringify(body.generator) ?? "null"},${params},${normalizedStatements},[${comments.join(",")}]]`;
}

function testBody(call: ESTree.CallExpression): { readonly body: TestFunction; readonly signature: string } | null {
  const args = call.arguments;
  if (args.length !== 2) return null;
  const title = unwrapExpression(args[0] as Node);
  if (title.type !== "Literal" && title.type !== "TemplateLiteral") return null;
  // The title is a literal, so the callback can only be the second argument.
  const callback = unwrapExpression(args[1] as Node);
  if (callback.type !== "FunctionExpression" && callback.type !== "ArrowFunctionExpression") return null;
  const block = callback.body;
  if (block?.type !== "BlockStatement" || block.body.length < MIN_STATEMENTS) return null;
  const callee = unwrapExpression(call.callee);
  const signature = testCallerSignature(callee);
  if (signature === null || hasEachMember(callee)) return null;
  return { body: callback, signature };
}

function hasEachMember(callee: Node): boolean {
  callee = unwrapExpression(callee);
  if (callee.type === "MemberExpression") {
    return staticMemberName(callee) === "each" || hasEachMember(callee.object);
  }
  if (callee.type === "CallExpression") return hasEachMember(callee.callee);
  if (callee.type === "TaggedTemplateExpression") return hasEachMember(callee.tag);
  return false;
}

function testCallerSignature(callee: Node): string | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") {
    return frameworkName(callee as ESTree.IdentifierReference, "test", TEST_CALLERS);
  }
  if (callee.type === "MemberExpression") {
    const base = testCallerSignature(callee.object);
    const member = staticMemberName(callee);
    return base !== null && member !== null && TEST_MODIFIERS.has(member) ? `${base}.${member}` : null;
  }
  if (callee.type === "CallExpression") return testCallerSignature(callee.callee);
  if (callee.type === "TaggedTemplateExpression") return testCallerSignature(callee.tag);
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow substantial sibling tests with the same body shape; express their differing inputs as a parameterized case table.",
      url: docsUrl("duplicate-test-body"),
    },
    schema: [],
    messages: {
      duplicateTestBody:
        "This test duplicates a sibling test's body. Create one named test or subtest per case; use `test.each(...)` or `it.each(...)` where the runner supports it.",
    },
  },
  createOnce(context: Context) {
    let source: SourceCode;
    let siblings = new Map<Node, Set<string>>();

    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        source = context.sourceCode;
        if (!isTestFile(file) || isGeneratedFile(file, source.text)) return false;
        siblings = new Map();
      },
      CallExpression(node: ESTree.CallExpression): void {
        const candidate = duplicateTestBodyCandidate(node, source);
        if (candidate === null) return;
        let fingerprints = siblings.get(candidate.container);
        if (fingerprints === undefined) {
          fingerprints = new Set();
          siblings.set(candidate.container, fingerprints);
        }
        if (fingerprints.has(candidate.fingerprint)) context.report({ node, messageId: "duplicateTestBody" });
        fingerprints.add(candidate.fingerprint);
      },
    };
  },
});
