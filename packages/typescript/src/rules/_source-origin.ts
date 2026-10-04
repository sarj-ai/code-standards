/** @fileoverview _source-origin — map genuine native documents to their authored source. */

import { hash } from "node:crypto";
import type { Context, SourceCode } from "@oxlint/plugins";

/** Compiler provenance for a real virtual document; native nodes and scopes remain untouched. */
export interface SourceOrigin {
  readonly filename: string;
  readonly text: string;
  readonly region?: "client-script";
}

export interface AuthoredSpan {
  readonly virtual: readonly [number, number];
  readonly original: readonly [number, number];
  readonly exact: boolean;
}

export interface SourceDocument extends SourceOrigin {
  readonly virtualHash: string;
  readonly spans: readonly AuthoredSpan[];
  readonly elements?: readonly AstroElement[];
}

export interface AstroElement {
  readonly name: string;
  readonly start: number;
  readonly end?: number;
  readonly attributes: readonly {
    readonly name: string;
    readonly kind: string;
    readonly value?: string;
    readonly start: number;
    readonly end?: number;
  }[];
  readonly children: readonly {
    readonly type: string;
    readonly value?: string;
    readonly start: number;
    readonly end?: number;
  }[];
}

const documents = new WeakMap<SourceCode, SourceDocument | null>();

function document(context: Context): SourceDocument | null {
  const cached = documents.get(context.sourceCode);
  if (cached !== undefined) return cached;
  const configured = context.settings["sarjSourceDocuments"];
  if (configured === undefined) {
    documents.set(context.sourceCode, null);
    return null;
  }
  if (configured === null || typeof configured !== "object" || Array.isArray(configured)) {
    throw new Error("sarjSourceDocuments must contain compiler provenance keyed by filename");
  }
  const value: unknown = configured[context.filename];
  if (value === undefined) {
    documents.set(context.sourceCode, null);
    return null;
  }
  if (value === null || typeof value !== "object" || Array.isArray(value) ||
    !("filename" in value) || typeof value.filename !== "string" ||
    !("text" in value) || typeof value.text !== "string" ||
    !("virtualHash" in value) || typeof value.virtualHash !== "string" ||
    !("spans" in value) || !Array.isArray(value.spans)) {
    throw new Error("Invalid compiler source provenance");
  }
  if (hash("sha256", context.sourceCode.text, "hex") !== value.virtualHash) {
    throw new Error("Compiler source provenance does not match the linted document");
  }
  const originalText = value.text;
  const spans: AuthoredSpan[] = value.spans.map((span: unknown) => {
    if (span === null || typeof span !== "object" ||
      !("virtual" in span) || !Array.isArray(span.virtual) || span.virtual.length !== 2 ||
      !("original" in span) || !Array.isArray(span.original) || span.original.length !== 2 ||
      !("exact" in span) || typeof span.exact !== "boolean" ||
      !span.virtual.every(Number.isSafeInteger) || !span.original.every(Number.isSafeInteger)) {
      throw new Error("Invalid compiler source span");
    }
    const [start, end] = span.virtual;
    const [originalStart, originalEnd] = span.original;
    if (start < 0 || end < start || end > context.sourceCode.text.length ||
      originalStart < 0 || originalEnd < originalStart || originalEnd > originalText.length ||
      (span.exact && (end - start !== originalEnd - originalStart ||
        context.sourceCode.text.slice(start, end) !== originalText.slice(originalStart, originalEnd)))) {
      throw new Error("Compiler source span is outside its source document");
    }
    return { virtual: [start, end], original: [originalStart, originalEnd], exact: span.exact };
  });
  const elements = astroElements(value);
  const region = "region" in value ? value.region : undefined;
  if (region !== undefined && region !== "client-script") throw new Error("Invalid compiler source region");
  const origin = { filename: value.filename, text: value.text, virtualHash: value.virtualHash, spans, elements,
    ...(region === "client-script" && { region: "client-script" as const }),
  };
  documents.set(context.sourceCode, origin);
  return origin;
}

function astroElements(value: object): readonly AstroElement[] {
  if (!("elements" in value)) return [];
  if (!Array.isArray(value.elements)) throw new Error("Invalid Astro source facts");
  const elements: AstroElement[] = [];
  for (const element of value.elements) {
    if (element === null || typeof element !== "object" ||
      typeof element.name !== "string" || !Number.isSafeInteger(element.start) ||
      (element.end !== undefined && !Number.isSafeInteger(element.end)) || !Array.isArray(element.attributes) ||
      !Array.isArray(element.children)) throw new Error("Invalid Astro element facts");
    elements.push(element);
  }
  return elements;
}

export function astroElement(
  context: Context,
  range: readonly [number, number],
): AstroElement | null {
  const origin = document(context);
  if (origin === null) return null;
  const original = authoredRange(context, range);
  return original === null ? null : origin.elements?.find((element) => element.start === original.start) ?? null;
}

export function sourceOrigin(context: Context): SourceOrigin {
  return document(context) ?? { filename: context.filename, text: context.sourceCode.text };
}

/** Diagnostics may own a structural span; edits require a proven identical span. */
export function authoredRange(
  context: Context,
  range: readonly [number, number],
  exact = false,
): { readonly start: number; readonly end: number } | null {
  const origin = document(context);
  if (origin === null) return { start: range[0], end: range[1] };
  const span = origin.spans
    .filter((candidate) => candidate.virtual[0] <= range[0] && candidate.virtual[1] >= range[1] &&
      (!exact || candidate.exact))
    .sort((left, right) => left.virtual[1] - left.virtual[0] - (right.virtual[1] - right.virtual[0]))[0];
  if (span === undefined) return null;
  return span.exact
    ? { start: span.original[0] + range[0] - span.virtual[0], end: span.original[0] + range[1] - span.virtual[0] }
    : { start: span.original[0], end: span.original[1] };
}
