/**
 * @fileoverview no-restated-jsdoc — a JSDoc block whose every word is already in the signature costs three lines and a review and says nothing.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-restated-jsdoc.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isProtected, splitIdentifier, stem } from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";
import { documentsTypedFunction } from "./_prose-budget.js";

type MessageIds = "restatesSignature" | "deleteBlock";
type Options = readonly [];

export const NO_RESTATED_JSDOC_DOCUMENTATION = {
  summary: "Flag JSDoc prose that appears to repeat declaration names without adding behavioral information.",
  rationale: "Signature-only JSDoc duplicates type information and drifts without helping callers.",
  remediation: "Delete the block or document behavior, constraints, failures, or context the signature cannot express.",
  category: "maintainability",
  aliases: ["jsdoc-restates-signature"],
  autofix: "suggestion",
  limitations: ["Generated files, detached blocks, intervening comments, unknown tags, explicit JSDoc type payloads, empty blocks, and JSDoc with information absent from the signature are excluded.", "Negation, conditions, constraints, sentinel values, numeric details, and quoted text conservatively preserve the block, even when a declaration name contains the same words."],
  examples: [
    { id: "behavioral-jsdoc", title: "Document behavior absent from the signature", outcome: "no-match", files: [{ path: "src/users.ts", source: "/** Get the user while bypassing the read replica. */\nexport function getUser(id: string) { return id; }" }], focusPath: "src/users.ts", expectedCount: 0, public: true },
    { id: "signature-jsdoc", title: "Remove JSDoc that only repeats the signature", outcome: "match", files: [{ path: "src/users.ts", source: "/** Get the user by id. */\nexport function getUserById(id: string) { return id; }" }], focusPath: "src/users.ts", expectedCount: 1, public: true },
    { id: "negated-behavior", scenarioId: "negation", title: "Keep behavior even when its words resemble the declaration", outcome: "no-match", files: [{ path: "src/users.ts", source: "/** Does not cache the user. */\nexport function cacheUser(user: unknown) { return user; }" }], focusPath: "src/users.ts", expectedCount: 0, public: true },
    { id: "repeated-behavior-name", scenarioId: "negation", title: "Review prose that merely repeats the declaration name", outcome: "match", files: [{ path: "src/users.ts", source: "/** Cache the user. */\nexport function cacheUser(user: unknown) { return user; }" }], focusPath: "src/users.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

interface JsDocTag {
  readonly name: string;
  readonly text: string;
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

/** The declared name and parameter names of the node a JSDoc block sits above. */
function declarationNames(node: TSESTree.Node): { name: string; params: string[] } | null {
  switch (node.type) {
    // `export function f()` — the JSDoc sits above the `export`, so the token
    // after it resolves to the wrapper, not to the thing being documented.
    case AST_NODE_TYPES.ExportNamedDeclaration:
    case AST_NODE_TYPES.ExportDefaultDeclaration:
      return node.declaration == null ? null : declarationNames(node.declaration);
    case AST_NODE_TYPES.FunctionDeclaration:
    case AST_NODE_TYPES.TSDeclareFunction:
      return node.id === null ? null : { name: node.id.name, params: paramNames(node.params) };
    case AST_NODE_TYPES.ClassDeclaration:
    case AST_NODE_TYPES.TSInterfaceDeclaration:
    case AST_NODE_TYPES.TSTypeAliasDeclaration:
    case AST_NODE_TYPES.TSEnumDeclaration:
      return node.id === null ? null : { name: node.id.name, params: [] };
    case AST_NODE_TYPES.VariableDeclaration: {
      const declarator = node.declarations[0];
      if (declarator === undefined || declarator.id.type !== AST_NODE_TYPES.Identifier) return null;
      const init = declarator.init;
      const params =
        init != null &&
        (init.type === AST_NODE_TYPES.ArrowFunctionExpression ||
          init.type === AST_NODE_TYPES.FunctionExpression)
          ? paramNames(init.params)
          : [];
      return { name: declarator.id.name, params };
    }
    case AST_NODE_TYPES.MethodDefinition:
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.TSMethodSignature:
    case AST_NODE_TYPES.TSPropertySignature: {
      if (node.key.type !== AST_NODE_TYPES.Identifier) return null;
      const params =
        node.type === AST_NODE_TYPES.MethodDefinition
          ? paramNames(node.value.params)
          : node.type === AST_NODE_TYPES.TSMethodSignature
            ? paramNames(node.params)
            : [];
      return { name: node.key.name, params };
    }
    default:
      return null;
  }
}

function paramNames(params: readonly TSESTree.Parameter[]): string[] {
  const names: string[] = [];
  for (const param of params) {
    const target = param.type === AST_NODE_TYPES.AssignmentPattern ? param.left : param;
    if (target.type === AST_NODE_TYPES.Identifier) names.push(target.name);
    else if (target.type === AST_NODE_TYPES.TSParameterProperty) continue;
  }
  return names;
}

function tokensOf(names: readonly string[]): Set<string> {
  const tokens = new Set<string>();
  for (const name of names) for (const part of splitIdentifier(name)) tokens.add(part);
  return tokens;
}

export default createRule<Options, MessageIds>({
  name: "no-restated-jsdoc",
  documentation: NO_RESTATED_JSDOC_DOCUMENTATION,
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    docs: {
      description:
        "Flag JSDoc prose that appears to repeat declaration names without adding behavioral information.",
    },
    schema: [],
    messages: {
      restatesSignature:
        "JSDoc appears to repeat declaration names — consider removing repetition. Keep type contracts, constraints, failures, and rationale.",
      deleteBlock: "Delete the JSDoc block.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;

    return {
      Program(): void {
        for (const comment of sourceCode.getAllComments()) {
          if (comment.type !== "Block" || !comment.value.startsWith("*")) continue;
          const { description, tags } = parseJsDoc(comment.value);
          const describedText = [
            description,
            ...tags.filter((tag) => tag.name === "description").map((tag) => tag.text),
          ].filter((text) => text.length > 0).join("\n");
          if (DIRECTIVE_RE.test(describedText)) continue;
          const tagNames = new Set(tags.map((tag) => tag.name));
          if ([...tagNames].some((name) => !MODELLED_TAGS.has(name))) continue;
          if (isProtected(describedText)) continue;

          const token = sourceCode.getTokenAfter(comment, { includeComments: true });
          if (token === null || token.loc.start.line !== comment.loc.end.line + 1) continue;
          if (token.type === "Line" || token.type === "Block") continue;
          let node = sourceCode.getNodeByRangeIndex(token.range[0]);
          let declaration: { name: string; params: string[] } | null = null;
          while (node != null && node.type !== AST_NODE_TYPES.Program) {
            declaration = declarationNames(node);
            if (declaration !== null) break;
            node = node.parent ?? null;
          }
          if (declaration === null) continue;

          const paramTags = tags.filter((tag) => PARAM_TAGS.has(tag.name));
          const returnTags = tags.filter((tag) => RETURN_TAGS.has(tag.name));
          if ([...paramTags, ...returnTags].some((tag) => /^\s*\{/.test(tag.text))) continue;
          if (paramTags.some((tag) => /^\s*(?:\[|[A-Za-z_$][\w$]*\.)/.test(tag.text))) continue;
          if (describedText.length === 0 && paramTags.length === 0 && returnTags.length === 0) {
            continue;
          }
          // `no-typed-doc-sections` owns @param/@returns repetition on fully
          // typed signatures. Keeping one owner prevents duplicate diagnostics.
          if (
            (paramTags.length > 0 || returnTags.length > 0) &&
            documentsTypedFunction(sourceCode, comment)
          ) continue;

          const nameTokens = tokensOf([declaration.name]);
          const paramTokens = tokensOf(declaration.params);
          const known = new Set([...nameTokens, ...paramTokens]);

          let addsNothing = covered(describedText, known);
          for (const tag of paramTags) {
            const text = tag.text.replace(/^\{[^}]*\}\s*/, "");
            const match = /^\[?([A-Za-z_$][\w.$]*)\]?\s*-?\s*([\s\S]*)$/.exec(text);
            if (match === null) {
              addsNothing = false;
              break;
            }
            const path = match[1] ?? "";
            const root = path.split(".")[0] ?? "";
            if (!declaration.params.includes(root)) {
              addsNothing = false;
              break;
            }
            const own = new Set([...splitIdentifier(path.split(".").pop() ?? ""), ...nameTokens]);
            if (!covered(match[2] ?? "", own)) {
              addsNothing = false;
              break;
            }
            for (const part of splitIdentifier(match[1]?.split(".").pop() ?? "")) known.add(part);
          }
          if (addsNothing) {
            for (const tag of returnTags) {
              if (!covered(tag.text.replace(/^\{[^}]*\}\s*/, ""), known)) {
                addsNothing = false;
                break;
              }
            }
          }
          if (!addsNothing) continue;

          context.report({
            node: comment,
            messageId: "restatesSignature",
            suggest: [
              {
                messageId: "deleteBlock",
                fix: (fixer) => fixer.removeRange([comment.range[0], token.range[0]]),
              },
            ],
          });
        }
      },
    };
  },
});
