/**
 * @fileoverview no-trailing-value-narration — a trailing comment must not only restate the line's value and unit.
 *
 * Port of the 18.x `no-trailing-value-narration` rule. The rule is
 * untyped, so the port covers all of it.
 */

import type { Comment, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { trailingCommentRemovalRange } from "../utils/comment-edits.js";
import { codeTokens, hasExternalReference, stem } from "../utils/comments.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-trailing-value-narration";

// A number that is not part of an identifier or a dotted member path.
const NUMBER_RE = /(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])/g;
const WORD_RE = /[\p{L}\p{M}]+(?:'[\p{L}\p{M}]+)?|\d+(?:\.\d+)?/gu;

// Words that name the unit rather than the quantity — the one thing the code
// does not say, and the reason the fix is a *name*, not a deletion.
const UNIT_WORDS: ReadonlySet<string> = new Set([
  "bytes", "characters", "chars", "day", "days", "gb", "hour", "hours", "hr",
  "hrs", "hz", "items", "k", "kb", "khz", "m", "mb", "milliseconds", "min",
  "mins", "minute", "minutes", "ms", "pct", "percent", "px", "retries", "rows",
  "s", "sec", "second", "seconds", "secs", "times", "tokens",
]);

const STOPWORDS: ReadonlySet<string> = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "in", "is", "it",
  "of", "on", "or", "that", "the", "this", "we", "with",
]);

const DIRECTIVE_RE =
  /^\s*(?:eslint\b|eslint-|sarj-noqa\b|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|todo\b|fixme\b|hack\b|xxx\b)/i;

const UNIT_NAME_SUFFIX_RE =
  /(?:_(?:NS|US|MS|S|SEC|SECS|SECOND|SECONDS|MIN|MINS|MINUTE|MINUTES|HOUR|HOURS|DAY|DAYS|BYTE|BYTES|KB|MB|GB|HZ|KHZ|MHZ|PX)|(?:Ns|Us|Ms|Sec|Secs|Second|Seconds|Min|Mins|Minute|Minutes|Hour|Hours|Day|Days|Byte|Bytes|Kb|Mb|Gb|Hz|Khz|Mhz|Px))$/u;

/** A comment body made only of words and numbers that names at least one unit. */
interface Narration {
  readonly words: readonly string[];
  readonly numbers: ReadonlySet<string>;
}

/** Body-only screen, run before any token or AST lookup. */
function narration(body: string): Narration | null {
  if (body.length === 0 || DIRECTIVE_RE.test(body) || hasExternalReference(body)) return null;
  if (/[^\p{L}\p{M}\p{N}\s.,:()_]/u.test(body)) return null;
  const words = (body.match(WORD_RE) ?? []).map((word) => word.toLowerCase());
  const numbers = numbersIn(body);
  return numbers.size > 0 && words.some((word) => UNIT_WORDS.has(word)) ? { words, numbers } : null;
}

function narratesValue({ words, numbers }: Narration, code: string, codeNumbers: ReadonlySet<string>): boolean {
  for (const number of numbers) {
    if (!codeNumbers.has(number)) return false;
  }
  const identifiers = codeTokens(code);
  const stems = new Set<string>();
  for (const token of identifiers) stems.add(stem(token));
  return words.every(
    (word) =>
      STOPWORDS.has(word) ||
      UNIT_WORDS.has(word) ||
      numbers.has(word) ||
      identifiers.has(word) ||
      stems.has(stem(word)),
  );
}

function numbersIn(text: string): Set<string> {
  return new Set(text.match(NUMBER_RE) ?? []);
}

function canonicalUnit(word: string): string {
  switch (word) {
    case "milliseconds": return "ms";
    case "sec": case "secs": case "second": case "seconds": return "s";
    case "mins": case "minute": case "minutes": return "min";
    case "hr": case "hrs": case "hours": return "hour";
    case "days": return "day";
    case "bytes": return "byte";
    default: return word;
  }
}

function identifierUnit(node: Node): string | null {
  if (node.type === "MemberExpression" && !node.computed) return identifierUnit(node.property);
  if (node.type !== "Identifier") return null;
  const suffix = UNIT_NAME_SUFFIX_RE.exec(node.name)?.[0];
  return suffix === undefined ? null : canonicalUnit(suffix.replace(/^_/u, "").toLowerCase());
}

export default defineRule({
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    fixable: "code",
    docs: {
      description:
        "Flag a trailing comment that repeats the line's numeric value only to name its unit.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      deleteNarration:
        "Trailing comment restates the literal and the identifier already names its unit — delete the comment so it cannot drift.",
      narratesValue:
        "Consider putting the unit in the name if this comment only narrates the value; keep conversion details and constraints.",
      removeNarration: "Delete the redundant trailing narration.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;

    function checkTrailingComment(comment: Comment): void {
      const body = comment.value.replace(/^\*+/, "").replace(/\*+$/, "").trim();
      const candidate = narration(body);
      if (candidate === null || !isTrailing(comment) || isInsideBrackets(comment)) return;
      const attached = attachedValue(comment);
      if (attached === null) return;
      const code = `${sourceCode.getText(attached.name)} ${sourceCode.getText(attached.value)}`;
      const codeNumbers = new Set(sourceCode.getTokens(attached.value)
        .filter((token) => token.type === "Numeric")
        .flatMap((token) => [...numbersIn(token.value)]));
      if (!narratesValue(candidate, code, codeNumbers)) return;
      const namedUnit = identifierUnit(attached.name);
      if (namedUnit === null) {
        context.report({ node: comment, messageId: "narratesValue" });
        return;
      }
      if (attached.value.type !== "Literal" || typeof attached.value.value !== "number" ||
          !candidate.words.every((word) => !UNIT_WORDS.has(word) || canonicalUnit(word) === namedUnit)) return;
      const removal = trailingCommentRemovalRange(sourceCode.text, comment);
      context.report({
        node: comment,
        messageId: "deleteNarration",
        ...(removal !== null && {
          fix: (fixer: Fixer) => fixer.removeRange([...removal.range]),
          suggest: [{ messageId: "removeNarration", fix: (fixer: Fixer) => fixer.removeRange([...removal.range]) }],
        }),
      });
    }

    function isTrailing(comment: Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return before !== null && before.loc.end.line === comment.loc.start.line;
    }

    function isInsideBrackets(comment: Comment): boolean {
      let node: Node | null | undefined = sourceCode.getNodeByRangeIndex(comment.range[0]);
      while (node != null) {
        if (node.type === "BlockStatement" || node.type === "Program") return false;
        if (
          node.type === "ArrayExpression" ||
          node.type === "CallExpression" ||
          node.type === "NewExpression"
        ) {
          return true;
        }
        node = node.parent;
      }
      return false;
    }

    function attachedValue(comment: Comment): NamedValue | null {
      let token = sourceCode.getTokenBefore(comment);
      if (token?.value === ";" || token?.value === ",") token = sourceCode.getTokenBefore(token);
      if (token === null) return null;
      let node = sourceCode.getNodeByRangeIndex(token.range[0]);
      while (node !== null && node.type !== "Program") {
        if (node.range[1] <= comment.range[0]) {
          const value = namedValue(node);
          if (value !== undefined) return value;
        }
        node = node.parent ?? null;
      }
      return null;
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        return undefined;
      },
      Program(): void {
        for (const comment of sourceCode.getAllComments()) checkTrailingComment(comment);
      },
    };
  },
});

/** The name and value a trailing comment can narrate. */
interface NamedValue {
  readonly name: Node;
  readonly value: Node;
}

/** The narratable pair at `node`; `null` stops the walk at an unnamed assignment target. */
function namedValue(node: Node): NamedValue | null | undefined {
  switch (node.type) {
    case "VariableDeclarator":
      return node.id.type === "Identifier" && node.init !== null ? { name: node.id, value: node.init } : undefined;
    case "Property":
      return !node.computed && node.kind === "init" && node.parent.type === "ObjectExpression" ? { name: node.key, value: node.value } : undefined;
    case "PropertyDefinition":
      return !node.computed && node.value !== null ? { name: node.key, value: node.value } : undefined;
    case "AssignmentExpression":
      return node.operator === "=" ? assignedValue(node) : undefined;
    default:
      return undefined;
  }
}

function assignedValue(node: ESTree.AssignmentExpression): NamedValue | null {
  const target = node.left;
  return target.type === "Identifier" || (target.type === "MemberExpression" && !target.computed)
    ? { name: target, value: node.right }
    : null;
}
