const fs = require('node:fs');
const compilerPath = fs.realpathSync(process.argv[2]);
const compilerPackage = require(require('node:path').join(require('node:path').dirname(compilerPath), '../package.json'));
const ts = require(compilerPath);
if (process.version !== process.argv[3] || compilerPackage.version !== process.argv[4] || ts.version !== process.argv[5]) {
  throw new Error('Rule comparison parser does not match documented preinstalled Node/compiler package/runtime pins');
}
const inputs = JSON.parse(fs.readFileSync(0, 'utf8'));
const output = {};
const path = require('node:path').posix;
const virtualRoot = '/snapshot';
const absolute = name => path.join(virtualRoot, name);
const files = new Map(Object.entries(inputs).map(([name, source]) => [absolute(name), source]));
const directories = new Set();
for (const name of files.keys()) {
  for (let directory = path.dirname(name); directory !== '/'; directory = path.dirname(directory)) directories.add(directory);
}
const options = { moduleResolution: ts.ModuleResolutionKind.NodeNext, module: ts.ModuleKind.NodeNext, allowJs: true };
const host = {
  fileExists: name => files.has(name), readFile: name => files.get(name),
  directoryExists: name => directories.has(name), getCurrentDirectory: () => virtualRoot,
  getDirectories: name => [...directories].filter(value => path.dirname(value) === name).map(value => path.basename(value)),
};
const cache = ts.createModuleResolutionCache(virtualRoot, value => value, options);
for (const [name, source] of Object.entries(inputs)) {
  const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true,
    name.endsWith('.tsx') ? ts.ScriptKind.TSX : name.endsWith('.js') ? ts.ScriptKind.JS : ts.ScriptKind.TS);
  if (file.parseDiagnostics.length) { output[name] = { imports: [], error: `Malformed TypeScript source: ${name}` }; continue; }
  const references = [];
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = ts.isImportDeclaration(node) ? node.importClause : null;
      const bindings = clause && clause.namedBindings;
      const typeOnly = ts.isExportDeclaration(node) ? (node.isTypeOnly || (node.exportClause && ts.isNamedExports(node.exportClause) && node.exportClause.elements.length && node.exportClause.elements.every(element => element.isTypeOnly))) : Boolean(clause &&
        (clause.isTypeOnly || (!clause.name && bindings && ts.isNamedImports(bindings) &&
         bindings.elements.length && bindings.elements.every(element => element.isTypeOnly))));
      if (!typeOnly) references.push(node.moduleSpecifier.text);
    } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference) && ts.isStringLiteral(node.moduleReference.expression)) {
      if (!node.isTypeOnly) references.push(node.moduleReference.expression.text);
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0])) {
      references.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  output[name] = { error: null, imports: [...new Set(references)].sort().map(reference => {
    if (!reference.startsWith('.')) return { specifier: reference, resolved: null };
    const result = ts.resolveModuleName(reference, absolute(name), options, host, cache).resolvedModule;
    return { specifier: reference, resolved: result ? path.relative(virtualRoot, result.resolvedFileName) : null };
  }) };
}
process.stdout.write(JSON.stringify(output));
