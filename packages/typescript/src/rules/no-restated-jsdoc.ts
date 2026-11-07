/**
 * @fileoverview no-restated-jsdoc — a JSDoc block whose every word is already in the signature costs three lines and a review and says nothing.
 *
 * Port of the 18.x `no-restated-jsdoc` rule. The rule is untyped, so
 * the port covers all of it.
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { commentLineEndings, ownLineCommentRemovalRange } from "../utils/comment-edits.js";
import { isProtected, splitIdentifier, stem } from "../utils/comments.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { documentsTypedFunction } from "../utils/prose-budget.js";

const NAME = "no-restated-jsdoc";

const MODELLED_TAGS: ReadonlySet<string> = new Set([
  "arg", "argument", "description", "param", "return", "returns",
]);

const PARAM_TAGS: ReadonlySet<string> = new Set(["arg", "argument", "param"]);
const RETURN_TAGS: ReadonlySet<string> = new Set(["return", "returns"]);

const DIRECTIVE_RE = /^\s*(?:eslint\b|eslint-|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|@vite|webpack|@jsx|@jest-environment|@vitest-environment|#__)/i;

const STOPWORDS: ReadonlySet<string> = new Set(
  `the a an of to for in on with and or as at by is are was be been being
   this that it its if whether when where which what will would can could should
   must may into from over about not no does do done has have had used use uses
   using given provided specified current new existing all any each per via based
   function method component hook class instance object value values data item
   items element callback handler prop props param parameter argument arg return
   returns returning result optional required default true false null undefined
   string number boolean array list promise`.split(/\s+/),
);

const WORD_RE = /\p{L}+/gu;
const BEHAVIORAL_PROSE_RE = /\b(?:not|no|never|if|when|unless|must|should|may|can|could|would|optional|required|default|true|false|null|undefined|before|after|until|once|again|only|always)\b|\d|["'`<>=+*/%&|!~^-]/i;

const TYPE_PREFIX_RE = /^\{[^}]*\}\s*/;
const TYPED_TAG_RE = /^\s*\{/;
const NESTED_PARAM_TAG_RE = /^\s*(?:\[|[A-Za-z_$][\w$]*\.)/;
const PARAM_TAG_RE = /^\[?([A-Za-z_$][\w.$]*)\]?\s*-?\s*([\s\S]*)$/;

interface JsDocTag {
  readonly name: string;
  readonly text: string;
}

/** The prose a JSDoc block claims: its description and its untyped, top-level param/return tags. */
interface JsDocClaims {
  readonly describedText: string;
  readonly paramTags: readonly JsDocTag[];
  readonly returnTags: readonly JsDocTag[];
}

interface DeclarationNames {
  readonly name: string;
  readonly params: readonly string[];
}

function paramNames(params: readonly ESTree.ParamPattern[]): string[] {
  const names: string[] = [];
  for (const param of params) {
    const target = param.type === "AssignmentPattern" ? param.left : param;
    if (target.type === "Identifier") names.push(target.name);
  }
  return names;
}

/** The claims of a JSDoc block that uses only modelled tags and says something, or null. */
function modelledJsDoc(comment: Comment): JsDocClaims | null {
  if (comment.type !== "Block" || !comment.value.startsWith("*")) return null;
  const { description, tags } = parseJsDoc(comment.value);
  const describedText = [
    description,
    ...tags.filter((tag) => tag.name === "description").map((tag) => tag.text),
  ].filter((text) => text.length > 0).join("\n");
  if (DIRECTIVE_RE.test(describedText) || tags.some((tag) => !MODELLED_TAGS.has(tag.name)) || isProtected(describedText)) return null;
  const paramTags = tags.filter((tag) => PARAM_TAGS.has(tag.name));
  const returnTags = tags.filter((tag) => RETURN_TAGS.has(tag.name));
  if ([...paramTags, ...returnTags].some((tag) => TYPED_TAG_RE.test(tag.text)) ||
    paramTags.some((tag) => NESTED_PARAM_TAG_RE.test(tag.text))) return null;
  return describedText.length === 0 && paramTags.length === 0 && returnTags.length === 0
    ? null
    : { describedText, paramTags, returnTags };
}

/** Split a JSDoc block into its free description and its tags. */
function parseJsDoc(value: string): { description: string; tags: JsDocTag[] } {
  const lines = value.replace(/^\*/, "").split("\n").map((line) => line.replace(/^\s*\*?\s?/, ""));
  const description: string[] = [];
  const tags: { name: string; text: string }[] = [];
  let current: { name: string; text: string } | null = null;
  for (const line of lines) {
    const match = /^\s*@(\w[\w-]*)\s*(.*)$/.exec(line);
    if (match) {
      current = { name: (match[1] ?? "").toLowerCase(), text: match[2] ?? "" };
      tags.push(current);
    } else if (current !== null) {
      current.text += ` ${line.trim()}`;
    } else {
      description.push(line);
    }
  }
  return { description: description.join("\n").trim(), tags };
}

export default defineRule({
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    fixable: "code",
    docs: {
      description:
        "Flag JSDoc prose that appears to repeat declaration names without adding behavioral information.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      restatesSignature:
        "JSDoc appears to repeat declaration names — consider removing repetition. Keep type contracts, constraints, failures, and rationale.",
      deleteBlock: "Delete the JSDoc block.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;

    function checkJsDoc(comment: Comment): void {
      const claims = modelledJsDoc(comment);
      if (claims === null) return;
      const token = sourceCode.getTokenAfter(comment, { includeComments: true });
      if (token === null || token.loc.start.line !== comment.loc.end.line + 1 ||
        token.type === "Line" || token.type === "Block") return;
      const declaration = enclosingDeclarationNames(sourceCode.getNodeByRangeIndex(token.range[0]));
      if (declaration === null) return;
      // `no-typed-doc-sections` owns @param/@returns repetition on fully
      // typed signatures. Keeping one owner prevents duplicate diagnostics.
      if ((claims.paramTags.length > 0 || claims.returnTags.length > 0) && documentsTypedFunction(sourceCode, comment)) return;
      if (repeatsDeclaration(claims, declaration)) reportRestated(comment);
    }

    function reportRestated(comment: Comment): void {
      const text = sourceCode.text;
      const removal = ownLineCommentRemovalRange(text, comment);
      if (removal === null) {
        context.report({ node: comment, messageId: "restatesSignature", suggest: [] });
        return;
      }
      context.report({
        node: comment,
        messageId: "restatesSignature",
        fix: (fixer) => {
          const endings = commentLineEndings(text, removal);
          return endings === null ? null : fixer.replaceTextRange([removal.range[0], removal.range[1]], endings);
        },
        suggest: [
          {
            messageId: "deleteBlock",
            fix: (fixer) => fixer.removeRange([removal.range[0], removal.range[1]]),
          },
        ],
      });
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        return undefined;
      },
      Program(): void {
        for (const comment of sourceCode.getAllComments()) { checkJsDoc(comment); }
      },
    };
  },
});

function enclosingDeclarationNames(node: Node | null): DeclarationNames | null {
  for (let current = node; current !== null && current.type !== "Program"; current = parentOf(current)) {
    const declaration = declarationNames(current);
    if (declaration !== null) return declaration;
  }
  return null;
}

/** The declared name and parameter names of the node a JSDoc block sits above. */
function declarationNames(node: Node): DeclarationNames | null {
  switch (node.type) {
    // `export function f()` — the JSDoc sits above the `export`, so the token
    // after it resolves to the wrapper, not to the thing being documented.
    case "ExportNamedDeclaration":
    case "ExportDefaultDeclaration":
      return node.declaration == null ? null : declarationNames(node.declaration);
    case "FunctionDeclaration":
    case "TSDeclareFunction":
      return node.id === null ? null : { name: node.id.name, params: paramNames(node.params) };
    case "ClassDeclaration":
    case "TSInterfaceDeclaration":
    case "TSTypeAliasDeclaration":
    case "TSEnumDeclaration":
      return node.id === null ? null : { name: node.id.name, params: [] };
    case "VariableDeclaration":
      return variableDeclarationNames(node);
    default:
      return memberNames(node);
  }
}

/** The name and parameter names of a class or interface member. */
function memberNames(node: Node): DeclarationNames | null {
  switch (node.type) {
    case "MethodDefinition":
      return keyedNames(node.key, node.value.params);
    case "TSMethodSignature":
      return keyedNames(node.key, node.params);
    case "PropertyDefinition":
    case "TSPropertySignature":
      return keyedNames(node.key, []);
    default:
      return null;
  }
}

function keyedNames(key: Node, params: readonly ESTree.ParamPattern[]): DeclarationNames | null {
  return key.type === "Identifier" ? { name: key.name, params: paramNames(params) } : null;
}

function variableDeclarationNames(node: ESTree.VariableDeclaration): DeclarationNames | null {
  const declarator = node.declarations[0];
  if (declarator === undefined || declarator.id.type !== "Identifier") return null;
  const init = declarator.init;
  const params = init?.type === "ArrowFunctionExpression" || init?.type === "FunctionExpression" ? paramNames(init.params) : [];
  return { name: declarator.id.name, params };
}

/** True when the description and every param/return tag only reuse words from the declaration's names. */
function repeatsDeclaration({ describedText, paramTags, returnTags }: JsDocClaims, declaration: DeclarationNames): boolean {
  const nameTokens = tokensOf([declaration.name]);
  const known = new Set([...nameTokens, ...tokensOf(declaration.params)]);
  if (!covered(describedText, known)) return false;
  for (const tag of paramTags) {
    const match = PARAM_TAG_RE.exec(tag.text.replace(TYPE_PREFIX_RE, ""));
    if (match === null) return false;
    const path = match[1] ?? "";
    if (!declaration.params.includes(path.split(".")[0] ?? "")) return false;
    const leaf = splitIdentifier(path.split(".").pop() ?? "");
    if (!covered(match[2] ?? "", new Set([...leaf, ...nameTokens]))) return false;
    for (const part of leaf) known.add(part);
  }
  return returnTags.every((tag) => covered(tag.text.replace(TYPE_PREFIX_RE, ""), known));
}

function tokensOf(names: readonly string[]): Set<string> {
  const tokens = new Set<string>();
  for (const name of names) for (const part of splitIdentifier(name)) tokens.add(part);
  return tokens;
}


/** True when every content word of `text` already appears in `known`. */
function covered(text: string, known: ReadonlySet<string>): boolean {
  if (BEHAVIORAL_PROSE_RE.test(text)) return false;
  const stems = new Set<string>();
  for (const token of known) stems.add(stem(token));
  return proseTokens(text).every((word) => known.has(word) || stems.has(stem(word)));
}


/** Every content word of `text`, lowercased, with filler dropped. */
function proseTokens(text: string): string[] {
  return (text.match(WORD_RE) ?? [])
    .map((word) => word.toLowerCase())
    .filter((word) => !STOPWORDS.has(word));
}
