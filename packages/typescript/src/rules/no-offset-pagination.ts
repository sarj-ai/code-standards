/**
 * @fileoverview no-offset-pagination — `OFFSET m` scans and discards m rows per page and shifts under concurrent writes, so rows repeat or vanish.
 *
 * Port of the 18.x `no-offset-pagination` rule. The rule is untyped, so
 * the port covers all of it.
 */

import type { VisitorWithHooks } from "@oxlint/plugins";

import { defineRule, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { createSqlListener } from "../utils/sql.js";

const NAME = "no-offset-pagination";

/** Match pagination across the parameter styles supported by the TS, Python, and SQL rules. */
const OFFSET_PAGINATION = /\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)/i;

const PAGINATION_CONTEXT = /\bSELECT\b[\s\S]*\bFROM\b[\s\S]*\bOFFSET\b|\bLIMIT\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)\s+OFFSET\b/i;

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Prefer keyset pagination for embedded SQL queries using OFFSET.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noOffsetPagination:
        "Review OFFSET pagination for large or changing result sets. If a keyset cursor fits the access pattern, preserve the query's complete ordering, tie-breakers, and filters; bounded pages or random page access may justify OFFSET.",
    },
  },
  createOnce(context): VisitorWithHooks {
    const listener = createSqlListener((sql: string, node: Node): void => {
      if (!PAGINATION_CONTEXT.test(sql) || !OFFSET_PAGINATION.test(sql)) {
        return;
      }
      context.report({ node, messageId: "noOffsetPagination" });
    });
    return {
      ...listener,
      before() {
        listener.before();
        if (isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        return undefined;
      },
    };
  },
});
