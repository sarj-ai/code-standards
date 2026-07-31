/**
 * @fileoverview Flag a JSDoc block whose every word is already in the signature
 * it documents.
 *
 *     /** Get the user by id. *\/
 *     export function getUserById(id: string): User { … }
 *
 * The block costs three lines and a review, survives every rename that matters,
 * and tells the reader nothing. Delete it, or say what the caller cannot read
 * off the name: what it throws, what it assumes, why it exists.
 *
 * **The generated-file sniff is mandatory, not a nicety.** In the 817-block
 * hand-written JSDoc corpus, 87% of the raw hits for this shape came from
 * OpenAPI codegen output, where every `@param id The id.` is emitted by a
 * template and rewritten on the next `openapi-generator` run. Editing them is
 * work that gets reverted; `isGeneratedFile` (path AND header marker) is what
 * takes the count from "hundreds, mostly noise" to a readable handful.
 *
 * **Never flagged**: a block carrying a value tag (`@deprecated`, `@see`,
 * `@example`, `@throws`, `@template`, `@remarks`, `@since`, …) — those are the
 * content the signature cannot hold; a block carrying any tag this rule does not
 * model, because it cannot judge what it cannot read; a `@param` or `@returns`
 * description that adds a word of its own; and anything in the nine-signal
 * protected class from `_comments`.
 *
 * **Autofix is deliberately a SUGGESTION, never `--fix`.** Deleting a doc block
 * in bulk is silent information loss if the judgement is wrong once; a
 * suggestion makes a human accept each one.
 *
 * **Measured.** 40 hits across the five maintained repos (11 in one, 29 in
 * another, 0 in the remaining three) and 5 across zod / swr / TanStack Query
 * (zustand 0). All 45 were read; the only debatable one is zod's
 * `/** The input data *\/` on `readonly input: unknown`, which is a published
 * API doc that nonetheless says nothing the field does not. Everything else is
 * `/** Logout function *\/` on `useLogout`, `/** Base64 encode a string *\/` on
 * `base64Encode(str)`, `/** A list row. *\/` on `ListRow`.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isProtected, splitIdentifier, stem } from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "restatesSignature" | "deleteBlock";
type Options = readonly [];

// Tags that carry something the signature cannot. Any of them and the block stays.
const VALUE_TAGS: ReadonlySet<string> = new Set([
  "alpha", "author", "beta", "category", "copyright", "default", "defaultvalue",
  "deprecated", "example", "experimental", "fileoverview", "fixme", "group",
  "inheritdoc", "internal", "license", "link", "module", "override",
  "packagedocumentation", "remarks", "see", "since", "template", "throws",
  "todo", "typeparam",
]);

// Tags this rule models and can therefore judge. Anything else means the block
// is doing something the rule does not understand, so it is left alone.
const MODELLED_TAGS: ReadonlySet<string> = new Set([
  "arg", "argument", "async", "description", "param", "return", "returns",
]);

const PARAM_TAGS: ReadonlySet<string> = new Set(["arg", "argument", "param"]);
const RETURN_TAGS: ReadonlySet<string> = new Set(["return", "returns"]);

const DIRECTIVE_RE = /^\s*(?:eslint\b|eslint-|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|@vite|webpack|@jsx|@jest-environment|@vitest-environment|#__)/i;

// Prose filler that says nothing about *which* thing is being described. Wider
// than the comment tokenizer's list because JSDoc conventionally repeats the
// vocabulary of the type system itself ("the callback prop", "an optional
// string") without that being a claim about this declaration.
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

const WORD_RE = /[A-Za-z]+/g;

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

/** Every content word of `text`, lowercased, with filler dropped. */
function proseTokens(text: string): string[] {
  return (text.match(WORD_RE) ?? [])
    .map((word) => word.toLowerCase())
    .filter((word) => word.length > 1 && !STOPWORDS.has(word));
}

/** True when every content word of `text` already appears in `known`. */
function covered(text: string, known: ReadonlySet<string>): boolean {
  const stems = new Set<string>();
  for (const token of known) stems.add(stem(token));
  return proseTokens(text).every((word) => known.has(word) || stems.has(stem(word)));
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "jsdoc-restates-signature",
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    docs: {
      description:
        "Flag a JSDoc block whose description and tags only re-spell the signature they document.",
    },
    schema: [],
    messages: {
      restatesSignature:
        "JSDoc only re-spells the signature — delete it, or say what the caller cannot read off the name (what it throws, what it assumes, why it exists).",
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
          if (DIRECTIVE_RE.test(description)) continue;
          const tagNames = new Set(tags.map((tag) => tag.name));
          if ([...tagNames].some((name) => VALUE_TAGS.has(name))) continue;
          if ([...tagNames].some((name) => !MODELLED_TAGS.has(name))) continue;
          if (isProtected(description)) continue;

          const token = sourceCode.getTokenAfter(comment, { includeComments: false });
          if (token === null || token.loc.start.line !== comment.loc.end.line + 1) continue;
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
          if (description.length === 0 && paramTags.length === 0 && returnTags.length === 0) {
            continue;
          }

          const nameTokens = tokensOf([declaration.name]);
          const paramTokens = tokensOf(declaration.params);
          const known = new Set([...nameTokens, ...paramTokens]);

          let addsNothing = covered(description, known);
          for (const tag of paramTags) {
            const text = tag.text.replace(/^\{[^}]*\}\s*/, "");
            const match = /^\[?([A-Za-z_$][\w.$]*)\]?\s*-?\s*([\s\S]*)$/.exec(text);
            if (match === null) {
              addsNothing = false;
              break;
            }
            const own = new Set([...splitIdentifier(match[1]?.split(".").pop() ?? ""), ...nameTokens]);
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
