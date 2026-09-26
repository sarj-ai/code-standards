import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(resolve("package.json"));
const ts = require("typescript");
process.stdin.setEncoding("utf8");
let source = "";
for await (const chunk of process.stdin) source += chunk;
const level = process.argv[2];
const tree = ts.createSourceFile("rule.ts", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
if (tree.parseDiagnostics.length) throw new Error("TypeScript rule source must parse before editing its severity");
const declarations = [];
function collect(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text.endsWith("DOCUMENTATION")) {
    declarations.push(node);
  }
  ts.forEachChild(node, collect);
}
collect(tree);
if (declarations.length !== 1) throw new Error("TypeScript rule source must contain one documentation declaration");
let object = declarations[0].initializer;
while (object && (ts.isSatisfiesExpression(object) || ts.isAsExpression(object) || ts.isParenthesizedExpression(object))) {
  object = object.expression;
}
if (!object || !ts.isObjectLiteralExpression(object)) throw new Error("TypeScript rule documentation must be an object literal");
function propertyName(property) {
  const name = property.name;
  if (!name) return undefined;
  if (!ts.isComputedPropertyName(name)) return name.text;
  return ts.isStringLiteralLike(name.expression) || ts.isNumericLiteral(name.expression)
    ? name.expression.text : undefined;
}
const fields = object.properties.filter((property) => propertyName(property) === "defaultLevel");
if (fields.length > 1) throw new Error("TypeScript rule documentation must contain at most one defaultLevel");
const field = fields[0];
const fieldIndex = object.properties.indexOf(field);
if (object.properties.some((property, index) => index > fieldIndex && (
  ts.isSpreadAssignment(property) ||
  (property.name && ts.isComputedPropertyName(property.name) && propertyName(property) === undefined)
))) {
  throw new Error("TypeScript rule documentation has ambiguous defaultLevel ownership from a spread or computed property");
}
if (field && (!ts.isPropertyAssignment(field) || !ts.isStringLiteral(field.initializer))) {
  throw new Error("TypeScript rule documentation must declare a literal defaultLevel");
}
const current = field?.initializer.text ?? "error";
if (!["error", "warning"].includes(current) || !["error", "warning"].includes(level)) {
  throw new Error("TypeScript rule defaultLevel must be error or warning");
}
if (current !== level) {
  if (field) {
    const value = field.initializer;
    const quote = source[value.getStart(tree)];
    source = source.slice(0, value.getStart(tree)) + quote + level + quote + source.slice(value.end);
  } else {
    const position = object.properties[0]?.getStart(tree) ?? object.getStart(tree) + 1;
    const indent = source.slice(source.lastIndexOf("\n", position - 1) + 1, position);
    const separator = indent.trim() ? " " : "\n" + indent;
    source = source.slice(0, position) + 'defaultLevel: "warning",' + separator + source.slice(position);
  }
}
process.stdout.write(JSON.stringify({ source, current }));
