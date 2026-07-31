/**
 * @fileoverview Flag a one-line comment that only re-spells the statement
 * beneath it — the TypeScript twin of Python's SARJ049.
 *
 *     // Login schemas
 *     export const ZLoginResponseSchema = z.object({ … });
 *
 * Every content word of the comment is already an identifier on the line below.
 * It cannot go out of date usefully, only silently, and a reader who scans it
 * learns nothing the code did not already say. Delete it, or replace it with the
 * *why*.
 *
 * **Division of labour with `no-comment-cruft`.** That rule already reports the
 * VERB-LED shape (`// increment the counter` above `counter += 1`), corroborated
 * against the statement *head*. This rule defers to it — `restatesStatementHead`
 * is imported and used as an exemption — so a comment is never reported twice.
 * What is left for this rule is the noun-phrase label whose every word appears
 * anywhere on the line: `// Env badge`, `// OTP schemas`,
 * `// Language enum`.
 *
 * **What makes it safe.** The first attempt at this shape (PR #98) corroborated
 * by substring — `service` matched `locationService` — and produced 933 hits at
 * a ~60% false-positive rate. Coincidental token overlap is the failure mode, so
 * every guard below is load-bearing: zero information (EVERY content token must
 * appear, exact or stemmed, never by prefix); at least two content tokens (one
 * word labels a thing, it does not restate a statement); a single-line comment
 * (a `//` run is a paragraph); a single-line, value-producing statement (a
 * comment above a block labels a region); the statement must invoke something
 * (a comment above a plain data declaration is a group label — that one shape
 * was every false positive left in the Python corpus sweep); and the whole
 * nine-signal protected class from `_comments` is exempt.
 *
 * **Measured.** 1 hit across the five maintained repos (four of them 0, the
 * fifth 1) and 8 across zod / swr / TanStack
 * Query, of which one — zod's `// no issues with confirmPassword or password`
 * over `return payload.issues.every(…)` — was the last false positive and is
 * now guarded by `NEGATION_WORD_RE`. The single-line-statement requirement is
 * what keeps the first-party count at zero: a `// Env badge` comment sits
 * over a multi-line `const renderEnvBadge = () => (`, i.e. it labels
 * a REGION, so this rule leaves it to `no-comment-cruft`'s section-label check.
 * That makes it a preventive ratchet on TypeScript with essentially no
 * migration cost, unlike its Python twin (SARJ049, 29 hits in one first-party
 * repo).
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import {
  codeTokens,
  contentTokens,
  isProtected,
  restatableStatementBelow,
  restates,
  restatesStatementHead,
} from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "restatesLineBelow";
type Options = readonly [];

const MAX_WORDS = 8;
const MIN_CONTENT_TOKENS = 2;

const DIRECTIVE_RE =
  /^(eslint\b|eslint-|sarj-noqa\b|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|todo\b|fixme\b|hack\b|xxx\b)/i;

// Commented-out code and section banners belong to `no-comment-cruft`.
const CODEY_RE = /^[\w.$[\]'"]+\s*[:=]\s*\S|^[\w.$]+\s*\(|^(?:return|throw|await|import|export|const|let|var)\b.*[=()[\]{}]/;
const BANNERISH_RE = /[=\-─-╿*#~_.]{3,}|^[A-Z0-9 _:-]+$/;

// Four shapes that pass the zero-information test and were wrong every time in
// the famous-corpus sweep: modality (`can`, `should`, `must` state a
// possibility or an obligation, which no arrangement of identifiers can say), a
// colon-terminated lead-in (it announces what follows rather than describing the
// line under it), inline emphasis (someone who wrote `*not*` or backticked an
// identifier was making a point about it), and a bare negation — `no`/`not`/
// `never` are stopwords for the tokenizer, so a comment stating a NEGATIVE
// property passes against the positive spelling below it (`// no issues with
// confirmPassword or password` over `return payload.issues.every(…)`,
// zod/packages/zod/src/v4/classic/tests/refine.test.ts:546). Saying what is
// absent is the one thing the code's own words cannot.
const MODALITY_RE = /\b(?:can|could|should|shall|may|might|must|will|would|cannot)\b/i;
const LEAD_IN_RE = /:$/;
const EMPHASIS_RE = /\*\w[^*]*\*|`[^`]+`/;
const NEGATION_WORD_RE = /\b(?:no|not|never|neither|nor|without|none|non)\b/i;

// The statement must *do* something. A comment above a plain data declaration
// labels the datum, and that shape is a series of group labels rather than
// narration — it was every false positive left in the Python corpus sweep.
const ACTION_STMT_RE = /[\w.$\])]\s*\(|^\s*(?:return|throw|await|yield)\b/;

const NON_ASCII_LETTER_RE = /[^\p{ASCII}\p{N}\p{P}\p{Z}]/u;

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
 * True when the statement below the comment heads a run of siblings of the same
 * kind — `// register secrets` over eight `registerSecret(…)` calls. The label
 * provides the grouping, and deleting it loses that.
 */
function headsSiblingRun(node: TSESTree.Node): boolean {
  const parent = node.parent;
  if (parent === undefined) return false;
  const body: readonly TSESTree.Node[] | undefined =
    "body" in parent && Array.isArray(parent.body)
      ? (parent.body as readonly TSESTree.Node[])
      : undefined;
  if (body === undefined) return false;
  const index = body.indexOf(node);
  const next = index >= 0 ? body[index + 1] : undefined;
  return next !== undefined && next.type === node.type;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-restated-comment",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag a single-line comment whose every word already appears on the statement below it.",
    },
    schema: [],
    messages: {
      restatesLineBelow:
        "Comment restates the statement below it — delete it, or replace it with the *why*; the code already carries the *what*.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;
    const lines = sourceCode.lines;

    function isStandalone(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function labelsASiblingRun(comment: TSESTree.Comment): boolean {
      const token = sourceCode.getTokenAfter(comment, { includeComments: false });
      if (token === null) return false;
      // Walk out to the STATEMENT, not merely to the first node starting on that
      // line. Stopping early looked at the innermost `Identifier`, whose parent
      // is an expression rather than a block, so the sibling test silently never
      // ran — zod's `assignability.test.ts` alone contributed 89 hits, a table
      // of one-line `z.string() satisfies z.core.$ZodString;` assertions each
      // labelled with the type it checks.
      for (
        let node: TSESTree.Node | undefined | null = sourceCode.getNodeByRangeIndex(token.range[0]);
        node != null && node.type !== AST_NODE_TYPES.Program;
        node = node.parent
      ) {
        if (headsSiblingRun(node)) return true;
      }
      return false;
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined || comment.type !== "Line") continue;
          if (!isStandalone(comment)) continue;
          if (
            areAdjacentLineComments(comments[i - 1], comment) ||
            areAdjacentLineComments(comment, comments[i + 1])
          ) {
            continue; // one line of a paragraph, not a label for the next statement
          }
          const body = comment.value.replace(/^\/*/, "").trim();
          if (body.length === 0 || body.endsWith("?")) continue;
          if (DIRECTIVE_RE.test(body) || CODEY_RE.test(body) || BANNERISH_RE.test(body)) continue;
          if (NON_ASCII_LETTER_RE.test(body) || isProtected(body)) continue;
          if (MODALITY_RE.test(body) || LEAD_IN_RE.test(body) || EMPHASIS_RE.test(body)) continue;
          if (NEGATION_WORD_RE.test(body)) continue;
          if (body.split(/\s+/).length > MAX_WORDS) continue;

          const tokens = contentTokens(body);
          if (tokens.length < MIN_CONTENT_TOKENS) continue;

          const statement = restatableStatementBelow(comment, sourceCode);
          if (statement === null) continue;
          if (restatesStatementHead(body, statement)) continue; // `no-comment-cruft` owns it

          const line = lines[comment.loc.start.line] ?? "";
          if (!ACTION_STMT_RE.test(line)) continue;

          if (labelsASiblingRun(comment)) continue;

          if (restates(tokens, codeTokens(line))) {
            context.report({ node: comment, messageId: "restatesLineBelow" });
          }
        }
      },
    };
  },
});
