/**
 * @fileoverview _docs — a rule links directly to executable examples derived from its name.
 *
 */

import { ESLintUtils } from "@typescript-eslint/utils";

export const REPO_BLOB = "https://github.com/sarj-ai/standards/blob/main";
export const TESTS_DIR = "packages/typescript/tests/rules";

export const examplesPath = (name: string): string =>
  `${TESTS_DIR}/${name}.test.ts`;

export const examplesUrl = (name: string): string =>
  `${REPO_BLOB}/${examplesPath(name)}`;

export const createRule = ESLintUtils.RuleCreator(examplesUrl);
