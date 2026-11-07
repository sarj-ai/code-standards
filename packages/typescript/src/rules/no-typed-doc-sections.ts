/**
 * @fileoverview no-typed-doc-sections — typed signatures do not need parameter or return tables.
 *
 * Port of the 18.x `no-typed-doc-sections` rule. Untyped. Oxlint sets an
 * absent `returnType`/`typeAnnotation` to `null` where TS-ESTree leaves it
 * `undefined`; the checks below treat both as absent, as the original does
 * under ESLint.
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { commentLineEndings, ownLineCommentRemovalRange } from "../utils/comment-edits.js";
import { docsUrl } from "../utils/docs-url.js";
import { proseGroups } from "../utils/prose-budget.js";

const NAME = "no-typed-doc-sections";

const TYPED_TAG_RE = /^\s*@(arg|argument|param|return|returns|yield|yields)\b(.*)$/iu;
const PARAM_TAGS: ReadonlySet<string> = new Set(["arg", "argument", "param"]);
const PARAMETER_FILLER: ReadonlySet<string> = new Set([
  "a", "an", "argument", "given", "input", "parameter", "passed", "provided", "the", "value",
]);
const ID_WORDS: ReadonlySet<string> = new Set(["identifier", "identifiers", "ids"]);
const RESULT_FILLER: ReadonlySet<string> = new Set([
  "a", "an", "array", "boolean", "generator", "number", "object", "output", "promise", "result",
  "return", "returned", "returns", "string", "the", "value",
]);

interface TypedTag {
  readonly kind: string;
  readonly name: string | null;
  readonly description: string;
  readonly explicitType: string | null;
}

type Signature = ESTree.Function | ESTree.ArrowFunctionExpression | ESTree.TSMethodSignature;

function parameterTarget(parameter: ESTree.ParamPattern | ESTree.TSParameterProperty): Node {
  if (parameter.type === "TSParameterProperty") return parameterTarget(parameter.parameter);
  return parameter.type === "AssignmentPattern" ? parameter.left : parameter;
}

function documentedSignature(sourceCode: Readonly<SourceCode>, comment: Comment): Signature | null {
  const before = sourceCode.getTokenBefore(comment);
  if (before?.loc.end.line === comment.loc.start.line) return null;
  const token = sourceCode.getTokenAfter(comment);
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return null;
  let node = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node !== null && node.type !== "Program" && node.type !== "BlockStatement" && node.type !== "ClassBody") {
    const signature = functionSignature(node);
    if (signature !== null) {
      return signature.returnType != null && signature.params.every((parameter) => {
        const target = parameterTarget(parameter);
        return "typeAnnotation" in target && target.typeAnnotation != null;
      }) ? signature : null;
    }
    node = parentOf(node);
  }
  return null;
}

function functionSignature(node: Node): Signature | null {
  switch (node.type) {
    case "ExportNamedDeclaration":
    case "ExportDefaultDeclaration":
      return node.declaration === null ? null : functionSignature(node.declaration);
    case "FunctionDeclaration":
    case "FunctionExpression":
    case "ArrowFunctionExpression":
    case "TSDeclareFunction":
    case "TSMethodSignature":
      return node;
    case "MethodDefinition":
      return node.value;
    case "VariableDeclaration":
      return soleFunctionInit(node);
    default:
      return null;
  }
}

/** `const f = () => …` or `const f = function …` with exactly one declarator. */
function soleFunctionInit(node: ESTree.VariableDeclaration): Signature | null {
  const init = node.declarations.length === 1 ? node.declarations[0]?.init : null;
  return init?.type === "ArrowFunctionExpression" || init?.type === "FunctionExpression" ? init : null;
}

function typedTags(text: string): TypedTag[] {
  const tags: Array<{ kind: string; payload: string }> = [];
  for (const raw of text.split("\n")) {
    const match = TYPED_TAG_RE.exec(raw);
    const last = tags.at(-1);
    const line = raw.trim();
    if (match !== null) {
      tags.push({ kind: (match[1] ?? "").toLowerCase(), payload: (match[2] ?? "").trim() });
    } else if (last !== undefined && line.length > 0 && !line.startsWith("@")) {
      last.payload = `${last.payload} ${line}`.trim();
    }
  }
  return tags.map(({ kind, payload }) => {
    const typeMatch = /^\{([^}\n]+)\}\s*/u.exec(payload);
    const explicitType = typeMatch?.[1]?.trim() ?? null;
    let rest = payload.slice(typeMatch?.[0].length ?? 0).trim();
    if (!PARAM_TAGS.has(kind)) {
      return { kind, name: null, description: rest.replace(/^-\s+/u, "").trim(), explicitType };
    }
    const match = /^(\[[^\]]+\]|[A-Za-z_$][\w$.[\]-]*)(?:\s+-\s+|\s+)?(.*)$/u.exec(rest);
    const rawName = match?.[1] ?? "";
    if (match === null || !/^[A-Za-z_$][\w$]*$/u.test(rawName)) return { kind, name: null, description: rest, explicitType };
    rest = (match[2] ?? "").trim();
    return { kind, name: rawName, description: rest, explicitType };
  });
}

function isVacuousTag(tag: TypedTag, signature: Signature, sourceCode: Readonly<SourceCode>): boolean {
  let annotation = signature.returnType;
  if (PARAM_TAGS.has(tag.kind)) {
    const parameter = signature.params.map(parameterTarget).find((node) => node.type === "Identifier" && node.name === tag.name);
    if (parameter?.type !== "Identifier") return false;
    annotation = parameter.typeAnnotation;
  }
  if (annotation == null) return false;
  if (tag.explicitType !== null && (
    !/^(?:string|number|boolean|bigint|symbol|unknown|never|void|null|undefined)$/u.test(tag.explicitType) ||
    sourceCode.getText(annotation.typeAnnotation) !== tag.explicitType
  )) return false;
  if (/[^\p{L}\p{M}\s.,]/u.test(tag.description)) return false;
  const description = words(tag.description).map(canonicalWord);
  if (description.length === 0) return tag.description.length === 0;
  if (tag.name === null) return description.every((word) => RESULT_FILLER.has(word));
  const nameWords = new Set(words(tag.name).map(canonicalWord));
  return description.every((word) => PARAMETER_FILLER.has(word) || nameWords.has(word));
}

function words(text: string): string[] {
  return text
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .toLowerCase()
    .match(/[\p{L}\p{M}][\p{L}\p{M}\p{N}]*/gu) ?? [];
}

function canonicalWord(word: string): string {
  if (ID_WORDS.has(word)) return "id";
  if (word.endsWith("s") && word.length > 3) return word.slice(0, -1);
  return word;
}

/** Remove only independently parsed vacuous tags from an own-line JSDoc block. */
function typedTagEdit(
  comment: Comment,
  signature: Signature,
  sourceCode: Readonly<SourceCode>,
): { readonly range: readonly [number, number]; readonly text: string } | null {
  if (comment.type !== "Block" || !comment.value.startsWith("*")) return null;
  const removal = ownLineCommentRemovalRange(sourceCode.text, comment);
  if (removal === null || /(?:eslint|@ts-|prettier|biome-|istanbul|[cv]8 ignore)/iu.test(comment.value)) return null;
  let removed = false;
  const retained = tagChunks(comment).flatMap((chunk) => {
    const [tag, ...others] = typedTags(chunk.join("\n"));
    if (tag !== undefined && others.length === 0 && isVacuousTag(tag, signature, sourceCode)) {
      removed = true;
      return [];
    }
    return chunk;
  });
  if (!removed) return null;
  while (retained[0]?.trim() === "") retained.shift();
  while (retained.at(-1)?.trim() === "") retained.pop();
  if (retained.length === 0) {
    const endings = commentLineEndings(sourceCode.text, removal);
    return endings === null ? null : { range: removal.range, text: endings };
  }
  const eol = sourceCode.text.includes("\r\n") ? "\r\n" : "\n";
  const indent = " ".repeat(comment.loc.start.column);
  return {
    range: comment.range,
    text: ["/**", ...retained.map((line) => `${indent} *${line.length === 0 ? "" : ` ${line}`}`), `${indent} */`].join(eol),
  };
}

/** A JSDoc block's content lines, split into the lead text and one chunk per `@` tag. */
function tagChunks(comment: Comment): string[][] {
  const chunks: string[][] = [];
  for (const raw of comment.value.replace(/^\*/u, "").split("\n")) {
    const line = raw.replace(/^[\t ]*\*?[\t ]?/u, "").replace(/\r$/u, "");
    const last = chunks.at(-1);
    if (last === undefined || line.trimStart().startsWith("@")) chunks.push([line]);
    else last.push(line);
  }
  return chunks;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Reject typed-signature repetition while preserving behavior that types cannot express.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      typedSection:
        "Typed JSDoc repeats parameters or returns — delete the repeated tags; if the signature still needs explanation, improve its names or types. Keep constraints and rationale.",
    },
  },
  createOnce(context) {
    return {
      Program() {
        const sourceCode = context.sourceCode;
        for (const group of proseGroups({ filename: context.filename, cwd: context.cwd }, sourceCode, true)) {
          if (!group.hasTypedTags) continue;
          const signature = documentedSignature(sourceCode, group.comment);
          if (
            signature !== null &&
            typedTags(group.text).some((tag) => isVacuousTag(tag, signature, sourceCode))
          ) {
            const edit = typedTagEdit(group.comment, signature, sourceCode);
            context.report({
              node: group.comment,
              messageId: "typedSection",
              ...(edit !== null && { fix: (fixer) => fixer.replaceTextRange([...edit.range], edit.text) }),
            });
          }
        }
      },
    };
  },
});
