/**
 * @fileoverview directive-no-use — only the allowed kinds of directive comments.
 *
 * Port of `@eslint-community/eslint-comments/no-use` 4.8.1 that also reads
 * `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, directiveComments, directiveLocation, eslintSpelling, lte, ruleIdLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-no-use";

interface RuleOptions {
  readonly allow?: readonly string[];
  readonly allowWholeFile?: boolean;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow directive comments, `eslint-*` or `oxlint-*`, except the allowed kinds, and check block-directive pairing.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          allow: {
            description: "Directive kinds to allow, such as `eslint-disable-next-line`; an `oxlint-*` directive follows its `eslint-*` kind.",
            type: "array",
            items: { type: "string" },
            uniqueItems: true,
          },
          allowWholeFile: {
            description: "Allow an unpaired disable directive before the file's first token.",
            type: "boolean",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      disallow: "Unexpected `{{kind}}` directive comment.",
      missingPair: "Requires 'eslint-enable' directive.",
      missingRulePair: "Requires 'eslint-enable' directive for '{{ruleId}}'.",
      aggregatingEnable:
        "This `eslint-enable` comment affects {{count}} `eslint-disable` comments. An `eslint-enable` comment should be for an `eslint-disable` comment.",
      unused: "Rules are re-enabled but those have not been disabled.",
      unusedRule: "'{{ruleId}}' rule is re-enabled but it has not been disabled.",
    },
  },
  createOnce(context) {
    return {
      Program(program): void {
        const allowed = new Set((context.options[0] as RuleOptions | undefined)?.allow ?? []);
        const { sourceCode } = context;
        for (const directive of directiveComments(sourceCode)) {
          if (allowed.has(eslintSpelling(directive.kind))) continue;
          context.report({
            loc: directiveLocation(sourceCode, directive.comment),
            messageId: "disallow",
            data: { kind: directive.kind },
          });
        }
        const allowWholeFile = (context.options[0] as RuleOptions | undefined)?.allowWholeFile === true;
        const firstToken = allowWholeFile ? sourceCode.getFirstToken(program) : null;
        const pairAreas = allowWholeFile && firstToken === null ? [] : directiveAreas(sourceCode).areas;
        for (const area of pairAreas) {
          if (area.end !== null) continue;
          if (firstToken !== null && lte(area.start, firstToken.loc.start)) continue;
          context.report({
            loc: ruleIdLocation(sourceCode, area.comment, area.ruleId),
            ...(area.ruleId === null ? { messageId: "missingPair" } : { messageId: "missingRulePair", data: { ruleId: area.ruleId } }),
          });
        }
        for (const [comment, count] of directiveAreas(sourceCode).closedDisables) {
          if (count < 2) continue;
          context.report({
            loc: directiveLocation(sourceCode, comment),
            messageId: "aggregatingEnable",
            data: { count: String(count) },
          });
        }
        for (const { comment, ruleId } of directiveAreas(sourceCode).unusedEnables) {
          context.report({
            loc: ruleIdLocation(sourceCode, comment, ruleId),
            ...(ruleId === null ? { messageId: "unused" } : { messageId: "unusedRule", data: { ruleId } }),
          });
        }
      },
    };
  },
});
