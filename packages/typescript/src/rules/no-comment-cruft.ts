/**
 * @fileoverview no-comment-cruft — commented-out code, section banners and file-header preambles are volume the reader pays for and nothing maintains.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-comment-cruft.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import {
  codeTokens,
  contentTokens,
  hasExternalReference,
  isProtected,
  restates,
  restatableStatementBelow,
  restatesStatementHead,
} from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds =
  | "commentedOutCode"
  | "sectionBanner"
  | "fileHeaderPreamble"
  | "commentWall"
  | "redundantNarration"
  | "untrackedTodo";
type Options = readonly [];

const LEADING_PREAMBLE_MIN = 4;
const WALL_MIN_STATEMENTS = 4;
const WALL_MIN_COMMENTS = 3;
const WALL_MIN_COMMENTED_RATIO = 0.6;
const WALL_MIN_WEAK_RATIO = 0.75;
const WALL_MAX_WORDS = 18;
const WALL_MAX_NOVEL_WORDS = 2;
const WALL_NARRATION_RE =
  /^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|now|finally|lastly|add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|count|create|declare|define|delete|extract|fetch|filter|find|format|generate|get|handle|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|store|update|validate|wrap|write)(?:s|es|d|ed|ing)?\b/i;
const WALL_STEP_PREFIX_RE = /^(?:\d+[.)]|(?:phase|step)\s+\d+\s*:)\s*/i;

// Require punctuation after step adverbs so ordinary prose does not match.
const STEP_NARRATION_RE =
  /^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?|finally|lastly|now)\s*[,:]\s*\S/i;

// These phrases name debt; `isBareDeferral` handles content-free `for now` notes.
const META_COMMENTARY_RE =
  /\b(?:keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)|clean (?:this|it) up|not ideal|placeholder for now)\b/i;

const FOR_NOW_RE = /\bfor now\b/i;

// Stopwords do not identify what is deferred.
const DEFERRAL_STOPWORDS: ReadonlySet<string> = new Set([
  "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could", "do",
  "does", "for", "from", "had", "has", "have", "here", "i", "in", "is", "it",
  "its", "just", "may", "might", "no", "not", "now", "of", "on", "only", "our",
  "shall", "should", "so", "still", "that", "the", "then", "there", "this",
  "to", "us", "was", "we", "were", "will", "with", "would", "you", "your",
]);

/** Most content words a `for now` comment may carry and still be pure deferral. */
const DEFERRAL_MAX_CONTENT_WORDS = 2;

/** Match `for now` only when at most two content words identify the deferral. */
function isBareDeferral(text: string): boolean {
  if (!FOR_NOW_RE.test(text)) return false;
  const rest = text.replace(FOR_NOW_RE, " ");
  const content = (rest.match(/[A-Za-z][\w']*/g) ?? []).filter(
    (word) => !DEFERRAL_STOPWORDS.has(word.toLowerCase()),
  );
  return content.length <= DEFERRAL_MAX_CONTENT_WORDS;
}

// Suppression and tool directives are instructions, not prose.
const DIRECTIVE_RE =
  /^(eslint\b|eslint-|sarj-noqa\b|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|hack\b|xxx\b)/i;

const LICENSE_RE =
  /copyright|licen[cs]ed?|spdx|permission is hereby granted|all rights reserved/i;

// Multiple explanatory list items form a walkthrough, not a content-free preamble.
const ENUMERATED_ITEM_RE = /^(?:\d+[.):]|[-*•])\s+\S/;
const ENUMERATED_ITEM_MIN_WORDS = 3;
const ENUMERATED_PREAMBLE_MIN_ITEMS = 2;

const BANNER_FULL_RE = /^[\s\-=*#~_+.]{4,}$/;
const BANNER_RUN_RE = /={4,}|-{4,}|#{4,}|\*{4,}|~{4,}|[\u2500-\u257f]{4,}/;

const REGION_MARKER_RE = /^#?(?:end)?region\b(.*)$/i;
const REGION_TITLE_RE = /^[\s:\-\u2013\u2014]*\w[\w \-/&+]*$/;
const REGION_TITLE_MAX_WORDS = 5;

function isRegionMarker(text: string): boolean {
  const match = REGION_MARKER_RE.exec(text);
  if (match === null) return false;
  const title = (match[1] ?? "").trim();
  if (title.length === 0) return true;
  if (!REGION_TITLE_RE.test(title)) return false;
  return title.split(/\s+/).length <= REGION_TITLE_MAX_WORDS;
}

const SECTION_LABEL_WORDS: ReadonlySet<string> = new Set([
  "actions", "components", "config", "configuration", "constant", "constants",
  "enums", "exports", "fixtures", "getters", "globals", "handler", "handlers",
  "helper", "helpers", "hook", "hooks", "imports", "interfaces", "main",
  "mocks", "models", "mutations", "props", "queries", "reducers", "routes",
  "schemas", "selectors", "setters", "setup", "state", "styles", "teardown",
  "type", "types", "util", "utilities", "utils",
]);
const SECTION_LABEL_RE = /^([A-Za-z]+)\s*:?\s*$/;

function isSectionLabel(text: string): boolean {
  const match = SECTION_LABEL_RE.exec(text);
  return match !== null && SECTION_LABEL_WORDS.has((match[1] ?? "").toLowerCase());
}

// Match two-to-four shouted words; preserve acronyms and numbered standards.
const SHOUTED_LABEL_RE = /^[A-Z]{2,}(?:[ -][A-Z]{2,}){1,3}$/;

const HELPER_OPENER_RE = /^(?:a\s+)?helper\s+(?:function|method|component|hook|class|type|util(?:ity)?)\b/i;

// Match walkthrough `let's`, but preserve third-person `lets` explanations.
const LETS_RE =
  /^let'?s\s+(?:not\s+|just\s+|now\s+|first\s+)?(?:add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|count|create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|increment|init|initialise|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|store|update|validate|wrap|write)(?:s|es|ed|ing)?\b/i;

// Flag an isolated numbered step; preserve walkthrough runs and JSX labels.
const ENUMERATION_RE = /^(?:\d+[.)]\s+\S|(?:phase|step)\s+\d+\b)/i;

// Dummy translational comments: ultra-short comments that just restate the code.
// Corroborated against the statement below by `restatesWholeStatement` — the
// lexical match alone is NOT evidence. See that function.
const DUMMY_TRANSLATION_RE = /^(?:increment|return|returns|get|gets|set\b(?! up\b)|sets\b(?! up\b)|function to|method to)\b/i;

const DIAGRAM_ARROW_RE = /[-=~]{2,}>|<[-=~]{2,}/;

const CODE_KEYWORD_RE =
  /^(import |export |const |let |var |function\b|class |interface |type \w|enum |return\b|throw |await |async |if\s*\(|for\s*\(|while\s*\(|switch\s*\(|new |console\.)/;
const CODE_TAIL_RE = /[;{}()]\s*$|=>\s*$|,\s*$/;
// Require an identifier LHS and code tail so prose equations do not match.
const ASSIGN_RE = /^[A-Za-z_$][\w.$[\]]*\s*(?:=(?![=>])|\+=|-=|\*=)\s*\S.*[;)}\]]\s*$/;
const CALL_RE = /^[A-Za-z_$][\w.$]*\([^)]*\)\s*;?\s*$/;

// Placeholders that only appear in grammar productions / desugaring examples,
// never in real code: `%sent%`, `[opt]`, a standalone `<FunctionBody>`, `…` / `...`.
const PSEUDOCODE_RE = /%\w+%|\[opt\]|(?:^|\s)<[A-Za-z]\w*>|…|\.\.\./;

// A triple-slash `///` directive keeps its third `/` after ESLint strips the
// leading `//`, so strip 1–2 leading slashes (not exactly two) for `<reference`.
function stripCommentMarker(line: string): string {
  return line.replace(/^\s*\/{1,2}/, "").replace(/^\s*\*+/, "").trim();
}

function isDirective(text: string): boolean {
  return DIRECTIVE_RE.test(text.trim());
}

function isBanner(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (BANNER_FULL_RE.test(t) || isRegionMarker(t)) return true;
  return BANNER_RUN_RE.test(t) && !DIAGRAM_ARROW_RE.test(t);
}

/**
 * `allowCall` is false where a bare statement cannot legally appear — inside an
 * interface body or a type literal. See `TYPE_MEMBER_CONTAINERS`.
 */
function looksLikeCode(text: string, allowCall = true): boolean {
  const t = text.trim();
  if (!t) return false;
  if (CODE_KEYWORD_RE.test(t) && CODE_TAIL_RE.test(t)) return true;
  if (ASSIGN_RE.test(t)) return true;
  return allowCall && CALL_RE.test(t);
}

function hasPseudocode(text: string): boolean {
  return PSEUDOCODE_RE.test(text);
}

/** An explanatory item of a numbered/bulleted walkthrough. */
function isEnumeratedProseItem(text: string): boolean {
  const t = text.trim();
  return ENUMERATED_ITEM_RE.test(t) && t.split(/\s+/).length >= ENUMERATED_ITEM_MIN_WORDS;
}

// A prose lead-in preceding a code-shaped line marks that line as an
// illustration (`// For example:`, a grammar production `FunctionExpression:`),
// not commented-out code.
function isProse(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (t.endsWith(":")) return true;
  if (
    /[.!?]$/.test(t) &&
    /\s/.test(t) &&
    /[a-z]/.test(t) &&
    !looksLikeCode(t) &&
    t.split(/\s+/).length >= 3
  ) {
    return true;
  }
  return false;
}

const JUSTIFICATION_RE =
  /\b(?:because|since|until|due to|so that|so we|so it|so the|otherwise|which is why|in order to|to avoid|to work around|to prevent|backwards? compat(?:ibility)?|for compatibility)\b/i;

/** Apply total corroboration to the whole statement, including call arguments. */
function restatesWholeStatement(body: string, statement: string | null): boolean {
  return statement !== null && restatesStatementHead(body, statement.replaceAll("(", " "));
}

/**
 * Whether a single-line comment merely narrates the code rather than explaining
 * the *why*. Three deterministic shapes: step narration ("First, …"), self-
 * admitted meta-commentary ("keeping it simple"), and a restatement of the very
 * next line (`// increment the counter` above `counter += 1`).
 */
function isRedundantNarration(
  body: string,
  statementBelow: string | null,
  standalone: boolean,
  isolatedEnumeration: boolean,
  nested: boolean,
): boolean {
  const t = body.trim();
  if (!t || looksLikeCode(t) || hasPseudocode(t)) return false;
  if (standalone) {
    const justified = JUSTIFICATION_RE.test(t);
    if (STEP_NARRATION_RE.test(t) && !justified) return true;
    if (META_COMMENTARY_RE.test(t) && !justified) return true;
    if (isBareDeferral(t) && !justified) return true;
    if (HELPER_OPENER_RE.test(t) || LETS_RE.test(t)) return true;

    const words = t.split(/\s+/);
    if (words.length > 1 && words.length <= 4 && DUMMY_TRANSLATION_RE.test(t) && !/[():=]/.test(t)) {
      const lowerT = t.toLowerCase();
      const rationaleWords = ["when", "because", "if", "so that", "due to", "for", "instead of", "to prevent", "to avoid", "only"];
      if (!rationaleWords.some((w) => lowerT.includes(w)) && restatesWholeStatement(t, statementBelow)) {
        return true;
      }
    }

    if (!nested && isSectionLabel(t)) return true;
    if (isolatedEnumeration && ENUMERATION_RE.test(t)) return true;
  }
  return restatesStatementHead(t, statementBelow);
}

// Outside these containers, a short label groups expression elements.
const STATEMENT_CONTAINERS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.Program,
  AST_NODE_TYPES.BlockStatement,
  AST_NODE_TYPES.ClassBody,
  AST_NODE_TYPES.StaticBlock,
  AST_NODE_TYPES.SwitchCase,
  AST_NODE_TYPES.TSModuleBlock,
  AST_NODE_TYPES.TSInterfaceBody,
]);

interface CommentWall {
  readonly leader: TSESTree.Comment;
  readonly members: ReadonlySet<TSESTree.Comment>;
}

interface WallAttachment {
  readonly container: TSESTree.Node;
  readonly index: number;
  readonly statement: string;
}

function directStatements(container: TSESTree.Node): readonly TSESTree.Node[] {
  switch (container.type) {
    case AST_NODE_TYPES.Program:
    case AST_NODE_TYPES.BlockStatement:
    case AST_NODE_TYPES.ClassBody:
    case AST_NODE_TYPES.StaticBlock:
    case AST_NODE_TYPES.TSModuleBlock:
      return container.body;
    case AST_NODE_TYPES.SwitchCase:
      return container.consequent;
    case AST_NODE_TYPES.TSInterfaceBody:
      return container.body;
    default:
      return [];
  }
}

const WALL_STATEMENTS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.ExpressionStatement,
  AST_NODE_TYPES.ReturnStatement,
  AST_NODE_TYPES.ThrowStatement,
  AST_NODE_TYPES.VariableDeclaration,
  AST_NODE_TYPES.IfStatement,
  AST_NODE_TYPES.ForStatement,
  AST_NODE_TYPES.ForOfStatement,
  AST_NODE_TYPES.ForInStatement,
  AST_NODE_TYPES.WhileStatement,
  AST_NODE_TYPES.DoWhileStatement,
  AST_NODE_TYPES.SwitchStatement,
  AST_NODE_TYPES.TryStatement,
]);

function statementAttachmentBelow(
  comment: TSESTree.Comment,
  sourceCode: Readonly<{
    getNodeByRangeIndex(index: number): TSESTree.Node | null;
    getTokenAfter(
      node: TSESTree.Comment,
      options: { includeComments: boolean },
    ): TSESTree.Token | null;
    getText(node: TSESTree.Node): string;
  }>,
): WallAttachment | null {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (
    token === null ||
    token.loc.start.line !== comment.loc.end.line + 1 ||
    token.loc.start.column !== comment.loc.start.column
  ) {
    return null;
  }
  for (
    let node: TSESTree.Node | null | undefined = sourceCode.getNodeByRangeIndex(token.range[0]);
    node?.parent != null;
    node = node.parent
  ) {
    if (!STATEMENT_CONTAINERS.has(node.parent.type) || !WALL_STATEMENTS.has(node.type)) {
      continue;
    }
    const siblings = directStatements(node.parent);
    const index = siblings.indexOf(node);
    return index < 0
      ? null
      : { container: node.parent, index, statement: sourceCode.getText(node) };
  }
  return null;
}

function isWeakWalkthroughComment(body: string, statement: string): boolean {
  const normalized = body.replace(WALL_STEP_PREFIX_RE, "");
  if (
    normalized.length === 0 ||
    normalized.endsWith("?") ||
    normalized.split(/\s+/).length > WALL_MAX_WORDS ||
    isDirective(normalized) ||
    isProtected(normalized) ||
    !WALL_NARRATION_RE.test(normalized)
  ) {
    return false;
  }
  const words = contentTokens(normalized);
  const described = words.slice(1);
  if (described.length === 0) return false;
  const code = codeTokens(statement);
  const matched = described.filter((word) => restates([word], code)).length;
  return (
    matched / described.length >= 0.5 &&
    described.length - matched <= WALL_MAX_NOVEL_WORDS
  );
}

/** Type-member containers cannot contain bare call statements. */
const TYPE_MEMBER_CONTAINERS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.TSInterfaceBody,
  AST_NODE_TYPES.TSTypeLiteral,
]);

/** Preserve an entire contiguous comment run when any line cites a reference. */
function runCitesAReference(comments: readonly TSESTree.Comment[], index: number): boolean {
  for (let i = index; i >= 0; i--) {
    if (i < index && !areAdjacentLineComments(comments[i], comments[i + 1])) break;
    if (hasExternalReference(stripCommentMarker(comments[i]?.value ?? ""))) return true;
  }
  for (let i = index + 1; i < comments.length; i++) {
    if (!areAdjacentLineComments(comments[i - 1], comments[i])) break;
    if (hasExternalReference(stripCommentMarker(comments[i]?.value ?? ""))) return true;
  }
  return false;
}

/** True when `a` and `b` are `//` comments on consecutive lines. */
function areAdjacentLineComments(
  a: TSESTree.Comment | undefined,
  b: TSESTree.Comment | undefined,
): boolean {
  return (
    a !== undefined &&
    b !== undefined &&
    a.type === "Line" &&
    b.type === "Line" &&
    b.loc.start.line === a.loc.end.line + 1
  );
}

/**
 * True when the comment at `index` is one line of a contiguous `//` block rather
 * than a lone annotation.
 */
function isInsideCommentRun(comments: readonly TSESTree.Comment[], index: number): boolean {
  const comment = comments[index];
  return (
    areAdjacentLineComments(comments[index - 1], comment) ||
    areAdjacentLineComments(comment, comments[index + 1])
  );
}

/** How far back the illustration lead-in scan walks within one `//` block. */
const LEAD_IN_SCAN_LIMIT = 24;

function hasIllustrationLeadInAbove(
  comments: readonly TSESTree.Comment[],
  index: number,
): boolean {
  for (let i = index - 1; i >= 0 && index - i <= LEAD_IN_SCAN_LIMIT; i--) {
    if (!areAdjacentLineComments(comments[i], comments[i + 1])) return false;
    const body = stripCommentMarker(comments[i]?.value ?? "");
    if (body.length > 0 && body.endsWith(":")) return true;
  }
  return false;
}

function hasCommentedOutCode(
  texts: readonly string[],
  precedingProse: boolean,
  allowCall: boolean,
): boolean {
  for (let i = 0; i < texts.length; i++) {
    const line = texts[i];
    if (line === undefined || !looksLikeCode(line, allowCall) || hasPseudocode(line)) {
      continue;
    }
    const prev = i > 0 ? texts[i - 1] : undefined;
    if (prev !== undefined ? isProse(prev) : precedingProse) continue;
    return true;
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "no-comment-cruft",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag commented-out code, section-banner comments, and leading file-header comment preambles.",
    },
    schema: [],
    messages: {
      commentedOutCode:
        "Commented-out code — delete it; git history remembers.",
      sectionBanner:
        "Section-banner / region comment — structure code with functions, not ASCII rules.",
      fileHeaderPreamble:
        "File-header comment preamble — use a brief doc comment for the why, not a block of `//` lines.",
      commentWall:
        "Statement comment wall ({{count}} narrated steps) — delete the walkthrough and name the operations in code; keep only constraints or rationale.",
      redundantNarration:
        "Comment narrates the code — delete it or say *why*, not *what*. Code is self-documenting.",
      untrackedTodo:
        "Untracked TODO/FIXME marker — add an issue ticket or context link.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const sourceCode = context.sourceCode;

    function isStandalone(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, {
        includeComments: false,
      });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function isJsDoc(comment: TSESTree.Comment): boolean {
      return comment.type === "Block" && /^\*/.test(comment.value);
    }

    function findCommentWalls(comments: readonly TSESTree.Comment[]): CommentWall[] {
      const attached = new Map<
        TSESTree.Node,
        Array<{ comment: TSESTree.Comment; index: number; weak: boolean }>
      >();
      for (const comment of comments) {
        if (comment.type !== "Line" || !isStandalone(comment)) continue;
        const attachment = statementAttachmentBelow(comment, sourceCode);
        if (attachment === null) continue;
        const body = stripCommentMarker(comment.value);
        const entries = attached.get(attachment.container) ?? [];
        entries.push({
          comment,
          index: attachment.index,
          weak: isWeakWalkthroughComment(body, attachment.statement),
        });
        attached.set(attachment.container, entries);
      }

      const walls: CommentWall[] = [];
      for (const entries of attached.values()) {
        const sorted = entries.toSorted((left, right) => left.index - right.index);
        const clusters: Array<typeof sorted> = [];
        for (const entry of sorted) {
          const cluster = clusters.at(-1);
          if (cluster !== undefined && entry.index <= (cluster.at(-1)?.index ?? 0) + 2) {
            cluster.push(entry);
          } else {
            clusters.push([entry]);
          }
        }
        for (const cluster of clusters) {
          const firstIndex = cluster[0]?.index;
          const lastIndex = cluster.at(-1)?.index;
          if (firstIndex === undefined || lastIndex === undefined) continue;
          const span = lastIndex - firstIndex + 1;
          const weak = cluster.filter((entry) => entry.weak).map((entry) => entry.comment);
          if (
            span < WALL_MIN_STATEMENTS ||
            weak.length < WALL_MIN_COMMENTS ||
            cluster.length / span < WALL_MIN_COMMENTED_RATIO ||
            weak.length / cluster.length < WALL_MIN_WEAK_RATIO
          ) {
            continue;
          }
          const leader = weak[0];
          if (leader !== undefined) walls.push({ leader, members: new Set(weak) });
        }
      }
      return walls;
    }

    /** True when every content line of a JSDoc block is a banner or a section title. */
    function isSectionJsDoc(comment: TSESTree.Comment): boolean {
      const texts = comment.value
        .split("\n")
        .map(stripCommentMarker)
        .filter((line) => line.length > 0 && !isDirective(line));
      return (
        texts.length > 0 &&
        texts.every(
          (text) =>
            !isProtected(text) &&
            (isBanner(text) ||
              isSectionLabel(text) ||
              SHOUTED_LABEL_RE.test(text.replace(/[.:]$/, ""))),
        )
      );
    }

    function reportLeadingPreamble(
      comments: readonly TSESTree.Comment[],
      firstCodeLine: number,
    ): void {
      const leading: TSESTree.Comment[] = [];
      let prevLine: number | null = null;
      for (const comment of comments) {
        if (comment.type !== "Line") break;
        if (comment.loc.start.line >= firstCodeLine) break;
        if (!isStandalone(comment)) break;
        const body = stripCommentMarker(comment.value);
        if (isDirective(body) || body.startsWith("!")) continue;
        if (prevLine !== null && comment.loc.start.line !== prevLine + 1) break;
        leading.push(comment);
        prevLine = comment.loc.start.line;
      }
      const first = leading[0];
      if (first === undefined || leading.length < LEADING_PREAMBLE_MIN) return;
      const bodies = leading.map((c) => stripCommentMarker(c.value));
      if (bodies.some((body) => LICENSE_RE.test(body))) return;
      // A preamble carrying at least one prose sentence is documentation — the
      // "why" the rule wants — regardless of which comment syntax carries it.
      if (bodies.some((body) => isProse(body))) return;
      if (bodies.filter(isEnumeratedProseItem).length >= ENUMERATED_PREAMBLE_MIN_ITEMS) {
        return;
      }
      context.report({ node: first, messageId: "fileHeaderPreamble" });
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        const walls = findCommentWalls(comments);
        const wallByLeader = new Map(walls.map((wall) => [wall.leader, wall]));
        const wallMembers = new Set(walls.flatMap((wall) => [...wall.members]));
        const firstCodeLine =
          sourceCode.ast.tokens[0]?.loc.start.line ?? Number.MAX_SAFE_INTEGER;
        const enumerated = comments.filter(
          (c) => c.type === "Line" && ENUMERATION_RE.test(stripCommentMarker(c.value)),
        );

        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined) continue;
          const wall = wallByLeader.get(comment);
          if (wall !== undefined) {
            context.report({
              node: comment,
              messageId: "commentWall",
              data: { count: String(wall.members.size) },
            });
            continue;
          }
          if (wallMembers.has(comment)) continue;
          if (isJsDoc(comment)) {
            // JSDoc is preserved unless its entire body is a section signpost.
            if (isStandalone(comment) && isSectionJsDoc(comment)) {
              context.report({ node: comment, messageId: "sectionBanner" });
            }
            continue;
          }
          if (!isStandalone(comment)) continue;
          if (LICENSE_RE.test(comment.value)) continue;
          const texts = comment.value
            .split("\n")
            .map(stripCommentMarker)
            .filter((l) => l.length > 0 && !isDirective(l));

          const firstText = texts[0];
          if (firstText !== undefined && /^(?:todo|fixme)\b/i.test(firstText)) {
            if (!runCitesAReference(comments, i)) {
              context.report({
                node: comment,
                messageId: "untrackedTodo",
              });
            }
            continue;
          }

          if (texts.some(isBanner)) {
            context.report({ node: comment, messageId: "sectionBanner" });
            continue;
          }
          const prev = comments[i - 1];
          const precedingProse =
            prev !== undefined &&
            prev.type === "Line" &&
            prev.loc.end.line === comment.loc.start.line - 1 &&
            isProse(stripCommentMarker(prev.value));
          const container = sourceCode.getNodeByRangeIndex(comment.range[0]);
          const inTypeMembers = container !== null && TYPE_MEMBER_CONTAINERS.has(container.type);
          if (
            hasCommentedOutCode(texts, precedingProse, !inTypeMembers) &&
            !hasIllustrationLeadInAbove(comments, i)
          ) {
            context.report({ node: comment, messageId: "commentedOutCode" });
            continue;
          }
          // Narration only for single-line comments (a multi-line block is
          // usually a real doc).
          if (comment.type === "Line" && texts.length === 1) {
            const body = texts[0];
            const statement = restatableStatementBelow(comment, sourceCode);
            const standalone = !isInsideCommentRun(comments, i);
            const nested = container !== null && !STATEMENT_CONTAINERS.has(container.type);
            if (
              body !== undefined &&
              !runCitesAReference(comments, i) &&
              isRedundantNarration(body, statement, standalone, enumerated.length === 1, nested)
            ) {
              context.report({ node: comment, messageId: "redundantNarration" });
            }
          }
        }

        reportLeadingPreamble(comments, firstCodeLine);
      },
    };
  },
});
