// Inspect exported configuration without executing repository code.
// eslint-disable-next-line @sarj/prefer-node-fs-promises -- This short-lived adapter performs a bounded synchronous scan and then exits.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";

const CONFIG_NAME =
  /^(?:next|babel|vite|vitest|rsbuild|rspack|app)\.config\.[cm]?[jt]s$|^\.babelrc(?:\.[cm]?js|\.json)?$|^babel\.config\.json$|^app\.json$/;
const COMPILER_PLUGIN = /^(?:babel-plugin-)?react-compiler(?:$|\/)/;

function unwrap(node, bindings) {
  const seen = new Set();
  while (node) {
    if (
      ["TSAsExpression", "TSSatisfiesExpression", "ParenthesizedExpression"].includes(node.type)
    ) {
      node = node.expression;
    } else if (node.type === "Identifier" && bindings.has(node.name) && !seen.has(node.name)) {
      seen.add(node.name);
      node = bindings.get(node.name);
    } else return node;
  }
  return node;
}

function compilerPlugin(node, bindings) {
  node = unwrap(node, bindings);
  if (!node) return false;
  if (node.type === "Literal")
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Raw parser Literal values include strings, numbers, booleans, and null.
    return typeof node.value === "string" && COMPILER_PLUGIN.test(node.value);
  if (node.type === "ArrayExpression")
    return node.elements.some((item) => compilerPlugin(item, bindings));
  if (node.type === "CallExpression")
    return node.arguments.some((item) => compilerPlugin(item, bindings));
  return false;
}

function compilerEnabled(node) {
  if (node?.type === "ObjectExpression") return true;
  // eslint-disable-next-line @sarj/no-runtime-typeof -- Raw parser Literal values must be narrowed before reading a boolean compiler flag.
  if (typeof node?.value === "boolean") return node.value;
  throw new Error("Cannot statically resolve reactCompiler configuration");
}

const CONFIG_PROPERTIES = {
  reactCompiler(value, bindings, features) {
    features.compiler ||= compilerEnabled(value);
  },
  plugins(value, bindings, features) {
    features.compiler ||= compilerPlugin(value, bindings);
  },
  output(value, bindings, features) {
    features.staticExport ||= value?.value === "export";
  },
};

function configFeatures(node, bindings, features) {
  node = unwrap(node, bindings);
  if (!node) return;
  if (node.type === "ObjectExpression") {
    for (const property of node.properties) propertyFeatures(property, bindings, features);
  } else if (node.type === "ConditionalExpression") {
    configFeatures(node.consequent, bindings, features);
    configFeatures(node.alternate, bindings, features);
  } else if (node.type === "CallExpression") {
    for (const argument of node.arguments) configFeatures(argument, bindings, features);
  } else if (
    ["ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration"].includes(node.type)
  ) {
    configFeatures(node.body, bindings, features);
  } else if (node.type === "BlockStatement") {
    returnedFeatures(node.body, bindings, features);
  }
}

function propertyFeatures(property, bindings, features) {
  if (property.type === "SpreadElement")
    return configFeatures(property.argument, bindings, features);
  const name = property.key?.name ?? property.key?.value;
  const value = unwrap(property.value, bindings);
  if (Object.hasOwn(CONFIG_PROPERTIES, name)) CONFIG_PROPERTIES[name](value, bindings, features);
  else configFeatures(value, bindings, features);
}

function returnedFeatures(statements, bindings, features) {
  for (const statement of statements) {
    if (statement.type === "ReturnStatement")
      configFeatures(statement.argument, bindings, features);
  }
}

export function projectConfiguration(root, repositoryRoot, parse) {
  const features = { compiler: false, compilerLint: false, staticExport: false };
  for (let directory = root; ; directory = dirname(directory)) {
    const manifest = join(directory, "package.json");
    if (existsSync(manifest)) {
      const pkg = JSON.parse(readFileSync(manifest, "utf8"));
      const dependencies = { ...pkg.peerDependencies, ...pkg.dependencies, ...pkg.devDependencies };
      features.compiler ||= Boolean(dependencies["react-compiler-runtime"]);
      features.compilerLint ||= Boolean(dependencies["eslint-plugin-react-compiler"]);
      if (pkg.babel) sourceFeaturesFromJson(pkg.babel, parse, features);
    }
    for (const name of readdirSync(directory).filter((name) => CONFIG_NAME.test(name))) {
      sourceFeatures(join(directory, name), parse, features);
    }
    if (directory === repositoryRoot || dirname(directory) === directory) break;
    if (existsSync(join(directory, ".git"))) break;
  }
  return features;
}

function sourceFeatures(path, parse, features) {
  let source = readFileSync(path, "utf8");
  const json = path.endsWith(".json") || path.endsWith(".babelrc");
  if (json) source = `export default (${JSON.stringify(JSON.parse(source))});`;
  const parsed = parse(json ? "config.js" : path, source);
  if (parsed.errors.length) throw new Error(`Cannot parse React project configuration: ${path}`);
  const statements = parsed.program.body;
  exportedFeatures(statements, source, configBindings(statements), features);
}

function configBindings(statements) {
  const bindings = new Map();
  for (const statement of statements) {
    const declaration = statement.declaration ?? statement;
    if (declaration.type === "VariableDeclaration") {
      for (const item of declaration.declarations)
        if (item.id.type === "Identifier") bindings.set(item.id.name, item.init);
    }
  }
  return bindings;
}

function exportedFeatures(statements, source, bindings, features) {
  for (const statement of statements) {
    if (statement.type === "ExportDefaultDeclaration")
      configFeatures(statement.declaration, bindings, features);
    if (
      statement.type === "ExpressionStatement" &&
      statement.expression.type === "AssignmentExpression"
    ) {
      const assignment = statement.expression;
      const left = source.slice(assignment.left.start, assignment.left.end);
      if (["module.exports", "exports.default"].includes(left))
        configFeatures(assignment.right, bindings, features);
    }
  }
}

function sourceFeaturesFromJson(value, parse, features) {
  const node = parse("config.js", `(${JSON.stringify(value)})`).program.body[0].expression;
  configFeatures(node, new Map(), features);
}
