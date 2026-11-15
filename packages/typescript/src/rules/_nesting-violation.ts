/**
 * @fileoverview _nesting-violation — HTML parser repairs and content-model limits for a known chain of
 * intrinsic ancestors.
 *
 * The parser model follows React DOM's `validateDOMNesting`, which reports only nestings that the
 * HTML parser rebuilds into a different tree. Ancestors are ordered nearest first; an empty chain or
 * a missing parent means the surrounding markup is not visible.
 */

export interface NestingViolation {
  readonly kind: "parserChild" | "parserDescendant" | "contentModel";
  readonly ancestor: string;
}

const SPECIAL_TAGS: ReadonlySet<string> = new Set([
  "address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote",
  "body", "br", "button", "caption", "center", "col", "colgroup", "dd", "details", "dir", "div", "dl",
  "dt", "embed", "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1",
  "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html", "iframe", "img", "input",
  "isindex", "li", "link", "listing", "main", "marquee", "menu", "menuitem", "meta", "nav",
  "noembed", "noframes", "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script",
  "section", "select", "source", "style", "summary", "table", "tbody", "td", "template", "textarea",
  "tfoot", "th", "thead", "title", "tr", "track", "ul", "wbr", "xmp",
]);

const SCOPE_TAGS: ReadonlySet<string> = new Set([
  "applet", "caption", "html", "table", "td", "th", "marquee", "object", "select", "template",
  "foreignObject", "desc", "title",
]);

const BUTTON_SCOPE_TAGS: ReadonlySet<string> = new Set([...SCOPE_TAGS, "button"]);

const LIST_ITEM_SCOPE_TAGS: ReadonlySet<string> = new Set(
  [...SPECIAL_TAGS].filter((tag) => tag !== "address" && tag !== "div" && tag !== "p"),
);

const IMPLIED_END_TAGS: ReadonlySet<string> = new Set(["dd", "dt", "li", "option", "optgroup", "p", "rp", "rt"]);

const HEADINGS: ReadonlySet<string> = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);

const CLOSES_OPEN_PARAGRAPH: ReadonlySet<string> = new Set([
  "address", "article", "aside", "blockquote", "center", "details", "dialog", "dir", "div", "dl",
  "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "main", "menu", "nav", "ol", "p",
  "section", "summary", "ul", "pre", "listing", "table", "hr", "xmp", ...HEADINGS,
]);

const TABLE_SECTION_CHILDREN: ReadonlySet<string> = new Set(["tr", "style", "script", "template"]);

const PARENT_CONTENT: Readonly<Record<string, ReadonlySet<string>>> = {
  tr: new Set(["th", "td", "style", "script", "template"]),
  tbody: TABLE_SECTION_CHILDREN,
  thead: TABLE_SECTION_CHILDREN,
  tfoot: TABLE_SECTION_CHILDREN,
  colgroup: new Set(["col", "template"]),
  table: new Set(["caption", "colgroup", "tbody", "tfoot", "thead", "style", "script", "template"]),
  head: new Set([
    "base", "basefont", "bgsound", "link", "meta", "title", "noscript", "noframes", "style", "script",
    "template",
  ]),
  html: new Set(["head", "body", "frameset"]),
  frameset: new Set(["frame"]),
};

const TABLE_PARTS: ReadonlySet<string> = new Set(["frameset", "frame", "tbody", "td", "tfoot", "th", "thead", "tr"]);

const DOCUMENT_SECTIONS: ReadonlySet<string> = new Set(["head", "html", "body"]);

const CLOSED_BY_SELECT: ReadonlySet<string> = new Set(["caption", "col", "colgroup", "input"]);

const LIST_CONTAINERS: ReadonlySet<string> = new Set(["ul", "ol", "menu"]);

const UNSCOPED: ReadonlySet<string> = new Set();

export function nestingViolation(
  tag: string,
  ancestors: readonly string[],
  isInteractive: boolean,
): NestingViolation | null {
  const parent = ancestors[0];
  if (parent !== undefined && !isValidChild(tag, parent)) return { kind: "parserChild", ancestor: parent };
  const repairing = repairingAncestor(tag, ancestors);
  if (repairing !== undefined) return { kind: "parserDescendant", ancestor: repairing };
  const forbidding = contentModelAncestor(tag, ancestors, isInteractive);
  return forbidding === undefined ? null : { kind: "contentModel", ancestor: forbidding };
}

function isValidChild(tag: string, parent: string): boolean {
  const allowed = PARENT_CONTENT[parent];
  if (allowed !== undefined) return allowed.has(tag);
  if (HEADINGS.has(tag)) return !HEADINGS.has(parent);
  if (tag === "rp" || tag === "rt") return !IMPLIED_END_TAGS.has(parent);
  if (CLOSED_BY_SELECT.has(tag)) return parent !== "select";
  return !TABLE_PARTS.has(tag) && !DOCUMENT_SECTIONS.has(tag);
}

function repairingAncestor(tag: string, ancestors: readonly string[]): string | undefined {
  if (CLOSES_OPEN_PARAGRAPH.has(tag)) return inScope(ancestors, ["p"], BUTTON_SCOPE_TAGS);
  switch (tag) {
    case "form":
      return inScope(ancestors, ["form"], UNSCOPED) ?? inScope(ancestors, ["p"], BUTTON_SCOPE_TAGS);
    case "li":
      return inScope(ancestors, ["li"], LIST_ITEM_SCOPE_TAGS);
    case "dd":
    case "dt":
      return inScope(ancestors, ["dd", "dt"], LIST_ITEM_SCOPE_TAGS);
    case "a":
    case "button":
    case "nobr":
      return inScope(ancestors, [tag], SCOPE_TAGS);
    default:
      return undefined;
  }
}

function contentModelAncestor(tag: string, ancestors: readonly string[], isInteractive: boolean): string | undefined {
  if (tag === "li") {
    const parent = ancestors[0];
    return parent === undefined || LIST_CONTAINERS.has(parent) ? undefined : parent;
  }
  if (tag === "label") return ancestors.find((ancestor) => ancestor === "label" || ancestor === "a" || ancestor === "button");
  if (isInteractive) return ancestors.find((ancestor) => ancestor === "a" || ancestor === "button");
  return undefined;
}

function inScope(ancestors: readonly string[], targets: readonly string[], boundaries: ReadonlySet<string>): string | undefined {
  for (const ancestor of ancestors) {
    if (targets.includes(ancestor)) return ancestor;
    if (boundaries.has(ancestor)) return undefined;
  }
  return undefined;
}
