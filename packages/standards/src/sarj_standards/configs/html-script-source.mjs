// Feed executable HTML scripts to Oxlint's Astro loader. Preserve byte offsets
// so diagnostics still refer to the original HTML, including non-ASCII text.
export function htmlScriptSource(content, parse) {
  const masked = Buffer.from(content);
  visit(parse(content, { sourceCodeLocationInfo: true }));
  const frontmatter = content.match(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/);
  if (frontmatter) mask(0, frontmatter[0].length);
  return masked;

  function visit(node, template = false) {
    template ||= node.tagName === "template";
    if (node.tagName === "script") maskScript(node, template);
    for (const child of node.childNodes ?? []) visit(child, template);
    if (node.content) visit(node.content, template);
  }

  function maskScript(node, template) {
    if (!template && executable(node)) return;
    const location = node.sourceCodeLocation;
    if (location?.startTag) mask(location.startTag.endOffset, location.endTag?.startOffset ?? content.length);
  }

  function executable(node) {
    const attributes = Object.fromEntries(node.attrs.map(({ name, value }) => [name, value]));
    if (attributes.src !== undefined) return false;
    const type = attributes.type?.split(";")[0].trim().toLowerCase();
    if (type) return type === "module" || /^(?:text|application)\/(?:x-)?(?:java|ecma)script$/.test(type);
    const language = attributes.language?.trim().toLowerCase();
    return !language || /^(?:java|ecma)script(?:1\.[0-5])?$/.test(language);
  }

  function mask(start, end) {
    const first = Buffer.byteLength(content.slice(0, start));
    const last = Buffer.byteLength(content.slice(0, end));
    for (let offset = first; offset < last; offset++) {
      if (masked[offset] !== 10 && masked[offset] !== 13) masked[offset] = 32;
    }
  }
}
