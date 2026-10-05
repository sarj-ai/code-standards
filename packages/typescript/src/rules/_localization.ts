/**
 * @fileoverview _localization — localization policies share opt-in and translation-boundary semantics.
 */

import { nodeAncestors } from "./_scope.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";


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
  node: ESTree.Node,
  source: SourceCode,
  options: LocalizationOptions | undefined,
): boolean {
  const isText =
    node.type === "JSXText" ||
    node.type === "JSXExpressionContainer";
  let translateResolved = false;
  for (const current of [node, ...nodeAncestors(node).toReversed()]) {
    if (current.type !== "JSXElement") continue;
    const opening = current.openingElement;
    if (translationExemptElement(opening, isText)) return true;
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
  return false;
}

function translationExemptElement(opening: ESTree.JSXOpeningElement, isText: boolean): boolean {
  if (opening.name.type !== "JSXIdentifier") return false;
  if (["script", "style"].includes(opening.name.name)) return true;
  return isText && ["code", "samp"].includes(opening.name.name);
}
