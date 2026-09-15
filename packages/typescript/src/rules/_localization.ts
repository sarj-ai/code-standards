/**
 * @fileoverview _localization — localization policies share opt-in and translation-boundary semantics.
 */

import {
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import {
  attributeText,
  COMPONENT_IMPORT_SCHEMA,
  type ComponentImport,
  importedComponent,
} from "./_jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

export interface LocalizationOptions {
  readonly enabled?: boolean;
  readonly allowText?: readonly string[];
  readonly translationComponents?: readonly ComponentImport[];
}

export const LOCALIZATION_PROPERTIES = {
  enabled: { type: "boolean" },
  allowText: { type: "array", items: { type: "string" }, uniqueItems: true },
  translationComponents: COMPONENT_IMPORT_SCHEMA,
} as const;

export function localizationExcluded(
  filename: string,
  source: string,
  options: LocalizationOptions | undefined,
): boolean {
  return (
    options?.enabled === false ||
    isGeneratedFile(filename, source) ||
    isTestFile(filename) ||
    isStoryFile(filename)
  );
}

export function needsTranslation(
  text: string,
  options: LocalizationOptions | undefined,
): boolean {
  const normalized = text.replace(/\s+/gu, " ").trim();
  return /\p{L}/u.test(normalized) && !options?.allowText?.includes(normalized);
}

export function withinTranslation(
  node: TSESTree.Node,
  source: TSESLint.SourceCode,
  options: LocalizationOptions | undefined,
): boolean {
  const isText =
    node.type === AST_NODE_TYPES.JSXText ||
    node.type === AST_NODE_TYPES.JSXExpressionContainer;
  let translateResolved = false;
  for (const current of [node, ...source.getAncestors(node).toReversed()]) {
    if (current.type === AST_NODE_TYPES.JSXElement) {
      const opening = current.openingElement;
      if (
        opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
        ["script", "style"].includes(opening.name.name)
      )
        return true;
      if (
        isText &&
        opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
        ["code", "samp"].includes(opening.name.name)
      )
        return true;
      if (!translateResolved) {
        const translate = attributeText(opening, "translate");
        if (translate === "no" || translate === null) return true;
        if (translate === "yes") translateResolved = true;
      }
      const imported = importedComponent(opening.name, source);
      if (
        options?.translationComponents?.some(
          (component) =>
            component.module === imported?.module &&
            component.export === imported.export,
        )
      )
        return true;
    }
  }
  return false;
}
