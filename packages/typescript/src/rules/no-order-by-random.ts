/**
 * @fileoverview no-order-by-random — avoid sorting an entire candidate set by a random function.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-order-by-random.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener, isRuntimeSqlNode } from "./_sql.js";

type MessageIds = "noOrderByRandom";
type Options = readonly [];

const SELECT = /\bSELECT\b[\s\S]*?\bFROM\b/i;
const RANDOM_ORDER =
  /\bORDER\s+BY\b(?:(?!\b(?:LIMIT|FETCH|OFFSET|FOR)\b)[\s\S])*?\b(?:RANDOM|RAND)\s*\(/i;

export default createRule<Options, MessageIds>({
  name: "no-order-by-random",
  meta: {
    type: "suggestion",
    docs: { description: "Warn when embedded SQL sorts a full candidate set randomly." },
    schema: [],
    messages: {
      noOrderByRandom:
        "ORDER BY RANDOM()/RAND() evaluates and sorts the full candidate set. Use a precomputed sampling key or bounded sampling strategy.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!isRuntimeSqlNode(node)) {
        return;
      }
      if (SELECT.test(sql) && RANDOM_ORDER.test(sql)) {
        context.report({ node, messageId: "noOrderByRandom" });
      }
    });
  },
});
