/**
 * @fileoverview _docs — a rule's documentation links are DERIVED from its name, so a rename breaks a test instead of leaving a dead URL.
 *
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_docs.md
 */

import { ESLintUtils } from "@typescript-eslint/utils";

export const REPO_BLOB = "https://github.com/sarj-ai/standards/blob/main";
export const TESTS_DIR = "packages/typescript/tests/rules";
export const EVIDENCE_DIR = "docs/rules";

export const examplesPath = (name: string): string =>
  `${TESTS_DIR}/${name}.test.ts`;

export const evidencePath = (name: string): string =>
  `${EVIDENCE_DIR}/${name}.md`;

export const examplesUrl = (name: string): string =>
  `${REPO_BLOB}/${examplesPath(name)}`;

export const evidenceUrl = (name: string): string =>
  `${REPO_BLOB}/${evidencePath(name)}`;

export const createRule = ESLintUtils.RuleCreator(evidenceUrl);
