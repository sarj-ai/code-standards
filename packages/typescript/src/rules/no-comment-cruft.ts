/**
 * @fileoverview Flag comment cruft — commented-out code, section banners,
 * leading file-header comment preambles, and redundant narration. Code carries
 * the *what*; comments are reserved for the *why*. JSDoc (`/** ... *\/`) is
 * never flagged, and directive comments (`eslint-`, `@ts-`, `prettier-`,
 * `biome-`, `c8`, `<reference`, `TODO`, `FIXME`) are ignored.
 *
 * `redundantNarration` covers three shapes: step markers ("First, …", "Step 2:"),
 * self-admitted meta-commentary ("for now", "temporary hack"), and a comment
 * that restates the statement directly below it (`// increment the counter`
 * above `counter += 1`). The third shape is heavily guarded — see
 * `restatesNextLine` — because the first attempt at it (PR #98) corroborated by
 * substring and produced 933 hits at a ~60% false-positive rate. Measured on
 * 7,159 local TS/TSX files: 42 hits, 2 of them wrong (a comment heading a block
 * whose first statement happened to carry every word), and ZERO hits in the
 * maintained repos — it is a preventive ratchet with no migration cost.
 *
 * `fileHeaderPreamble` requires the preamble to contain NO prose sentence. The
 * original "4+ consecutive `//` lines before the first code" test penalised
 * syntax rather than content: on a real 42k-LOC codebase, 11 of 15 hits were the
 * repo's BEST documentation — module headers explaining a stateless idempotency
 * substrate, one citing RFC 9562 §5.7 — which is precisely the "brief doc
 * comment for the why" this rule's own message asks for. Exactly one hit was
 * genuine (an ASCII banner, already covered by `sectionBanner`). What survives
 * is the content-free preamble: a stack of bare labels/fragments with nothing
 * explained. A prose header should be a JSDoc block for tooling reasons, but
 * that is a formatting preference, not cruft, and this rule does not litigate it.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds =
  | "commentedOutCode"
  | "sectionBanner"
  | "fileHeaderPreamble"
  | "redundantNarration";
type Options = readonly [];

const LEADING_PREAMBLE_MIN = 4;

// Step-narration lead-ins ("First, …", "Then, …", "Finally, …", "Step 2:"). A
// trailing comma/colon is required so English adverbs ("finally the invariant
// holds") aren't mistaken for an enumeration marker.
const STEP_NARRATION_RE =
  /^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?|finally|lastly|now)\s*[,:]\s*\S|^step\s+\d+\b/i;

// Self-admitted meta-commentary — the "why later", not the why. `TODO`/`FIXME`/
// `HACK`/`XXX` are handled as directives (kept, with an owner, per convention).
const META_COMMENTARY_RE =
  /\b(?:for now|keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)|clean (?:this|it) up|not ideal|placeholder for now)\b/i;


const DIRECTIVE_RE =
  /^(eslint\b|eslint-|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|todo\b|fixme\b|hack\b|xxx\b)/i;

const LICENSE_RE =
  /copyright|licen[cs]ed?|spdx|permission is hereby granted|all rights reserved/i;

const BANNER_FULL_RE = /^[\s\-=*#~_+.]{4,}$/;
// `={4,}` not `={3,}`: `===` is TS strict-equality and appears in prose comments.
const BANNER_RUN_RE = /={4,}|-{4,}|#{4,}|\*{4,}|~{4,}/;
const REGION_RE = /^#?(?:end)?region\b/i;

const CODE_KEYWORD_RE =
  /^(import |export |const |let |var |function\b|class |interface |type \w|enum |return\b|throw |await |async |if\s*\(|for\s*\(|while\s*\(|switch\s*\(|new |console\.)/;
const CODE_TAIL_RE = /[;{}()]\s*$|=>\s*$|,\s*$/;
// LHS must be a real identifier (not a number literal — `0=Monday` in prose is
// not an assignment) and `=` must not be `==`/`===`/`=>` (comparison/arrow).
// The assignment branch additionally requires a code-tail — the line must end
// with `;`, `)`, `}` or `]` — so plain prose like `count = number of items`
// (which has no code-tail) is not mistaken for commented-out code.
const CALL_OR_ASSIGN_RE =
  /^[A-Za-z_$][\w.$[\]]*\s*(?:=(?![=>])|\+=|-=|\*=)\s*\S.*[;)}\]]\s*$|^[A-Za-z_$][\w.$]*\([^)]*\)\s*;?\s*$/;

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
  return BANNER_FULL_RE.test(t) || BANNER_RUN_RE.test(t) || REGION_RE.test(t);
}

function looksLikeCode(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (CODE_KEYWORD_RE.test(t) && CODE_TAIL_RE.test(t)) return true;
  return CALL_OR_ASSIGN_RE.test(t);
}

function hasPseudocode(text: string): boolean {
  return PSEUDOCODE_RE.test(text);
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

// --- "restates the next line" ---------------------------------------------
// A comment that opens with a narration verb and whose every remaining content
// word already names what the statement below it computes says nothing the code
// does not (`// increment the counter` / `counter += 1`). Three guards keep the
// inference sound, because *coincidental* token overlap is the failure mode that
// sank the first attempt at this shape (PR #98: `service` matching
// `locationService` gave a ~60% false-positive rate):
//
//  1. Total corroboration — one unmatched word (`// guard the race from
//     PLT-812`) means the comment carries something the code does not, so it
//     stays.
//  2. The comment must sit on top of a single-line, value-producing *statement*.
//     A comment above a block, a declaration, a type member or an object-literal
//     entry (`// store state` above `interface SessionState {`) labels a region
//     of code; the words it shares with the first line of that region are
//     incidental.
//  3. Only the head of the statement counts — everything up to the first `(` —
//     so the comment must restate what the statement *computes* (its target and
//     its callee), not merely something it passes as an argument.

const NARRATION_MAX_WORDS = 6;
const NARRATION_MIN_CONTENT = 1;
const TOKEN_PLURAL_MIN = 4;

// Statements that compute something a comment could be restating. A block, a
// class/function/type declaration, an `if`, a `for` — anything whose body the
// comment could be labelling instead — is deliberately absent.
const RESTATABLE_STATEMENTS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.ExpressionStatement,
  AST_NODE_TYPES.ReturnStatement,
  AST_NODE_TYPES.ThrowStatement,
  AST_NODE_TYPES.VariableDeclaration,
]);

// Verbs that describe the mechanics of the next statement. A comment opening
// with anything else (a noun, "because", "we", a ticket id) is not narration.
const NARRATION_VERB_RE =
  /^(?:add|append|assign|build|calculate|call|check|clear|close|compute|convert|copy|count|create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|increment|init|initialise|initialize|insert|iterate|join|load|log|loop|make|map|merge|open|parse|print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|store|update|validate|wrap|write)(?:s|es|d|ed|ing)?$/i;

// Words that carry no information about *which* code the comment describes, so
// they are not required to appear in the line below.
const NARRATION_STOPWORDS: ReadonlySet<string> = new Set([
  "a", "all", "an", "and", "any", "are", "as", "at", "back", "be", "both", "by",
  "each", "for", "from", "here", "if", "in", "into", "is", "it", "its", "just",
  "new", "of", "on", "one", "onto", "or", "our", "out", "over", "so", "that",
  "the", "then", "this", "to", "up", "us", "we", "when", "with",
]);

/** Lowercase, with a single plural `s` folded away so `users` matches `user`. */
function normalizeToken(word: string): string {
  const lower = word.toLowerCase();
  return lower.length > TOKEN_PLURAL_MIN && lower.endsWith("s") && !lower.endsWith("ss")
    ? lower.slice(0, -1)
    : lower;
}

/** Every identifier in a slice of source, plus its camelCase / snake_case parts. */
function codeTokens(source: string): ReadonlySet<string> {
  const tokens = new Set<string>();
  for (const identifier of source.match(/[A-Za-z_$][\w$]*/g) ?? []) {
    tokens.add(normalizeToken(identifier));
    for (const part of identifier.split(/[_$]+|(?<=[a-z0-9])(?=[A-Z])/)) {
      if (part.length > 0) tokens.add(normalizeToken(part));
    }
  }
  return tokens;
}

/** The slice of ESLint's `SourceCode` this shape reads. */
interface StatementReader {
  getTokenAfter: (
    node: TSESTree.Comment,
    options: { includeComments: boolean },
  ) => TSESTree.Token | null;
  getNodeByRangeIndex: (index: number) => TSESTree.Node | null;
  getText: (node: TSESTree.Node) => string;
}

/** A declaration with nothing but a zero/empty seed computes nothing to restate. */
function isTrivialInitializer(node: TSESTree.VariableDeclaration): boolean {
  return node.declarations.every((declarator) => {
    const init = declarator.init;
    if (init == null || init.type === AST_NODE_TYPES.Literal) return true;
    return (
      (init.type === AST_NODE_TYPES.ArrayExpression && init.elements.length === 0) ||
      (init.type === AST_NODE_TYPES.ObjectExpression && init.properties.length === 0)
    );
  });
}

/**
 * The source of the single-line statement a comment sits directly above, or null
 * when what follows is a block, a declaration, a type member or anything else
 * the comment could be *labelling* rather than restating.
 */
function restatableStatementBelow(comment: TSESTree.Comment, sourceCode: StatementReader): string | null {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return null;
  for (
    let node: TSESTree.Node | undefined | null = sourceCode.getNodeByRangeIndex(token.range[0]);
    node != null && node.type !== AST_NODE_TYPES.Program;
    node = node.parent
  ) {
    if (!RESTATABLE_STATEMENTS.has(node.type)) continue;
    if (node.loc.start.line !== token.loc.start.line || node.loc.end.line !== node.loc.start.line) {
      return null;
    }
    if (node.type === AST_NODE_TYPES.VariableDeclaration && isTrivialInitializer(node)) {
      return null;
    }
    return sourceCode.getText(node);
  }
  return null;
}

/**
 * True when a short verb-led comment adds nothing to the statement beneath it:
 * every content word after the opening verb already appears in that statement's
 * head — its assignment target or its callee.
 */
function restatesNextLine(body: string, statement: string | null): boolean {
  if (statement === null) return false;
  const words = body.match(/[A-Za-z][\w$]*/g) ?? [];
  const opener = words[0];
  if (opener === undefined || words.length > NARRATION_MAX_WORDS) return false;
  if (!NARRATION_VERB_RE.test(opener)) return false;
  const content = words
    .slice(1)
    .map(normalizeToken)
    .filter((word) => !NARRATION_STOPWORDS.has(word));
  if (content.length < NARRATION_MIN_CONTENT) return false;
  const head = statement.split("(")[0] ?? statement;
  const code = codeTokens(head);
  return content.every((word) => code.has(word));
}

/**
 * Whether a single-line comment merely narrates the code rather than explaining
 * the *why*. Three deterministic shapes: step narration ("First, …"), self-
 * admitted meta-commentary ("keeping it simple"), and a restatement of the very
 * next line (`// increment the counter` above `counter += 1`).
 */
function isRedundantNarration(body: string, statementBelow: string | null): boolean {
  const t = body.trim();
  if (!t || looksLikeCode(t) || hasPseudocode(t)) return false;
  if (STEP_NARRATION_RE.test(t)) return true;
  if (META_COMMENTARY_RE.test(t)) return true;
  return restatesNextLine(t, statementBelow);
}

function hasCommentedOutCode(
  texts: readonly string[],
  precedingProse: boolean,
): boolean {
  for (let i = 0; i < texts.length; i++) {
    const line = texts[i];
    if (line === undefined || !looksLikeCode(line) || hasPseudocode(line)) {
      continue;
    }
    const prev = i > 0 ? texts[i - 1] : undefined;
    if (prev !== undefined ? isProse(prev) : precedingProse) continue;
    return true;
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
      redundantNarration:
        "Comment narrates the code — delete it or say *why*, not *what*. Code is self-documenting.",
    },
  },
  defaultOptions: [],
  create(context) {
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
      context.report({ node: first, messageId: "fileHeaderPreamble" });
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        const firstCodeLine =
          sourceCode.ast.tokens[0]?.loc.start.line ?? Number.MAX_SAFE_INTEGER;

        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined) continue;
          if (isJsDoc(comment) || !isStandalone(comment)) continue;
          if (LICENSE_RE.test(comment.value)) continue;
          const texts = comment.value
            .split("\n")
            .map(stripCommentMarker)
            .filter((l) => l.length > 0 && !isDirective(l));
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
          if (hasCommentedOutCode(texts, precedingProse)) {
            context.report({ node: comment, messageId: "commentedOutCode" });
            continue;
          }
          // Narration only for single-line comments (a multi-line block is
          // usually a real doc).
          if (comment.type === "Line" && texts.length === 1) {
            const body = texts[0];
            const statement = restatableStatementBelow(comment, sourceCode);
            if (body !== undefined && isRedundantNarration(body, statement)) {
              context.report({ node: comment, messageId: "redundantNarration" });
            }
          }
        }

        reportLeadingPreamble(comments, firstCodeLine);
      },
    };
  },
});
