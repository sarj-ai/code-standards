/** @fileoverview docs-url — each rule's page on the code-standards documentation site. */

import { CATALOG_ENGINE } from "../documentation.js";

/** The rule's documentation page, published as `meta.docs.url`. */
export function docsUrl(name: string): string {
  return `https://code-standards.sarj.ai/rules/${CATALOG_ENGINE}/${name}/`;
}
