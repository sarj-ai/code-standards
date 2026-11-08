// Neutralize only public PEM headers proven to be removal-regex tokens. The official
// artifact callback still scans every other byte, including later keys in the same file.
const HEADER = "-----BEGIN PRIVATE KEY-----";
const FUNCTIONS = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);
const WRITE_TARGETS = {
  VariableDeclarator: "id",
  AssignmentExpression: "left",
  UpdateExpression: "argument",
  ForInStatement: "left",
  ForOfStatement: "left",
  CatchClause: "param",
  ClassDeclaration: "id",
  FunctionDeclaration: "id",
};

export function reactDoctorArtifactPem(file, parser) {
  if (!parser || !file.content.includes("PRIVATE KEY")) return file.content;
  try {
    if (file.relativePath.endsWith(".map")) return mapHeaders(file.content, parser);
    if (!/\.[cm]?[jt]sx?$/.test(file.relativePath)) return file.content;
    return maskHeaders(file.content, headerSpans(file.relativePath, file.content, parser));
  } catch {
    // Unsupported syntax, malformed maps and parser failures keep the original scan.
    return file.content;
  }
}

function maskHeaders(content, spans) {
  const fragments = [];
  let offset = 0;
  // Only ASCII hyphens need masking; UTF-8 byte offsets, UTF-16 positions and
  // newlines all remain identical, even when earlier source contains Unicode.
  for (const [start, end] of spans) {
    fragments.push(content.slice(offset, start), content.slice(start, end).replaceAll("-", "x"));
    offset = end;
  }
  fragments.push(content.slice(offset));
  return fragments.join("");
}

function mapHeaders(content, parser) {
  const map = JSON.parse(content);
  if (map.version !== 3 || !Array.isArray(map.sources) || !Array.isArray(map.sourcesContent))
    return content;
  const edits = mapHeaderEdits(content, map, sourceMapLiterals(content, parser), parser);
  const fragments = [];
  let offset = 0;
  for (const [start, end, masked] of edits) {
    fragments.push(content.slice(offset, start), masked);
    offset = end;
  }
  fragments.push(content.slice(offset));
  return fragments.join("");
}

function sourceMapLiterals(content, parser) {
  const parsed = parser.parseSync("artifact.js", `(${content})`);
  if (parsed.errors.length) return [];
  const object = parsed.program.body[0]?.expression?.expression;
  if (object?.type !== "ObjectExpression") return [];
  const properties = object.properties.filter(
    (property) => property.key?.value === "sourcesContent",
  );
  if (properties.length !== 1 || properties[0].value.type !== "ArrayExpression") return [];
  return properties[0].value.elements;
}

function mapHeaderEdits(content, map, literals, parser) {
  const edits = [];
  for (const [index, node] of literals.entries()) {
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Oxc literal values are raw parser unions; only decoded string literals can map code spans.
    if (node?.type !== "Literal" || typeof node.value !== "string") continue;
    const filename = map.sources[index];
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Source-map JSON is untrusted input; source names must be strings before selecting a parser.
    if (typeof filename !== "string" || !/\.[cm]?[jt]sx?$/.test(filename)) continue;
    const spans = headerSpans(filename, node.value, parser);
    const raw = content.slice(node.start - 1, node.end - 1);
    const masked = maskEncodedHeaders(raw, spans);
    if (masked !== raw) edits.push([node.start - 1, node.end - 1, masked]);
  }
  return edits;
}

function headerSpans(filename, content, parser) {
  const parsed = parser.parseSync(filename, content);
  if (parsed.errors.length) return [];
  const candidates = [];
  const written = new Set();
  let dynamic = false;
  for (const [node, strings, writing] of sourceNodes(parsed.program, parser)) {
    if (writing && node.type === "Identifier") written.add(node.name);
    if (
      node.type === "CallExpression" &&
      node.callee.type === "Identifier" &&
      node.callee.name === "eval"
    )
      dynamic = true;
    const pattern = removalPattern(node);
    if (pattern) candidates.push({ pattern, receiver: node.callee.object, strings });
  }
  return candidates
    .filter(({ receiver, strings }) => stringReceiver(receiver, strings, written, dynamic))
    .map(({ pattern }) => [pattern.start, pattern.end])
    .sort((a, b) => a[0] - b[0]);
}

function* sourceNodes(program, parser) {
  const pending = [[program, new Set(), false]];
  let visited = 0;
  while (pending.length) {
    if (++visited > 250000) throw new Error("PEM source traversal budget exceeded");
    const [node, inherited, writing] = pending.pop();
    const strings = FUNCTIONS.has(node.type) ? stringParameters(node) : inherited;
    yield [node, strings, writing];
    for (const key of parser.visitorKeys[node.type] ?? []) {
      const child = node[key];
      const childWriting = writing || key === WRITE_TARGETS[node.type];
      if (Array.isArray(child))
        pending.push(...child.filter(Boolean).map((value) => [value, strings, childWriting]));
      else if (child) pending.push([child, strings, childWriting]);
    }
  }
}

function stringParameters(node) {
  return new Set(
    node.params
      .filter(
        (parameter) =>
          parameter.type === "Identifier" &&
          !parameter.optional &&
          parameter.typeAnnotation?.typeAnnotation?.type === "TSStringKeyword",
      )
      .map((parameter) => parameter.name),
  );
}

function stringReceiver(node, strings, written, dynamic) {
  if (dynamic || written.has("String") || written.has("replace") || written.has("arguments"))
    return false;
  if (primitiveString(node)) return true;
  return node.type === "Identifier" && strings.has(node.name) && !written.has(node.name);
}

function primitiveString(node) {
  return (
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Literal parser values are raw unions; only primitive strings have the built-in removal contract.
    (node.type === "Literal" && typeof node.value === "string") || node.type === "TemplateLiteral"
  );
}

function removalPattern(node) {
  if (node.type !== "CallExpression" || node.arguments.length !== 2) return null;
  const member = node.callee;
  if (member.type !== "MemberExpression" || member.computed || member.optional) return null;
  if (!["replace", "replaceAll"].includes(member.property.name)) return null;
  const [pattern, replacement] = node.arguments;
  if (replacement.type !== "Literal" || replacement.value !== "") return null;
  return pattern.regex?.pattern === HEADER ? pattern : null;
}

function maskEncodedHeaders(raw, spans) {
  if (!spans.length) return raw;
  let offset = 0;
  let spanIndex = 0;
  return raw.replace(/\\u[\da-fA-F]{4}|\\.|[^"\\]/g, (token) => {
    const decoded = JSON.parse(`"${token}"`);
    const start = offset;
    offset += decoded.length;
    while (spanIndex < spans.length && spans[spanIndex][1] <= start) spanIndex++;
    if (decoded !== "-" || !spans[spanIndex] || spans[spanIndex][0] > start) return token;
    return token.length === 6 ? "\\u0078" : "x";
  });
}
