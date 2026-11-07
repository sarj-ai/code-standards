/**
 * @fileoverview directive-disable-enable-pair — every block disable directive has a matching enable directive.
 *
 * Port of `@eslint-community/eslint-comments/disable-enable-pair` 4.8.1 that
 * also reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, lte, ruleIdLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-disable-enable-pair";

interface RuleOptions {
  readonly allowWholeFile?: boolean;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require an `eslint-enable` directive for every block `eslint-disable` or `oxlint-disable` directive.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          allowWholeFile: {
            description: "Allow an unpaired disable directive before the file's first token.",
            type: "boolean",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      missingPair: "Requires 'eslint-enable' directive.",
      missingRulePair: "Requires 'eslint-enable' directive for '{{ruleId}}'.",
    },
  },
  createOnce(context) {
    return {
      Program(program): void {
        const allowWholeFile = (context.options[0] as RuleOptions | undefined)?.allowWholeFile === true;
        const { sourceCode } = context;
        // With `allowWholeFile`, disables before the first token cover the whole file; a file without tokens has nothing to pair.
        const firstToken = allowWholeFile ? sourceCode.getFirstToken(program) : null;
        if (allowWholeFile && firstToken === null) return;
        for (const area of directiveAreas(sourceCode).areas) {
          if (area.end !== null) continue;
          if (firstToken !== null && lte(area.start, firstToken.loc.start)) continue;
          context.report({
            loc: ruleIdLocation(sourceCode, area.comment, area.ruleId),
            ...(area.ruleId === null ? { messageId: "missingPair" } : { messageId: "missingRulePair", data: { ruleId: area.ruleId } }),
          });
        }
      },
    };
  },
});
