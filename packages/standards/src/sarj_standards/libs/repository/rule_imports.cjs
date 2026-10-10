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
  const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true);
  if (file.parseDiagnostics.length) { output[name] = { imports: [], error: `Malformed TypeScript source: ${name}` }; continue; }
  const references = [];
  const commonJsReferences = new Set();
  let checker;
  let nativeRequire;
  function assignedNames(node, targets) {
    if (ts.isIdentifier(node)) targets.push(node);
    else if (ts.isParenthesizedExpression(node)) assignedNames(node.expression, targets);
    else if (ts.isArrayLiteralExpression(node)) node.elements.forEach(element => assignedNames(element, targets));
    else if (ts.isSpreadElement(node) || ts.isSpreadAssignment(node)) assignedNames(node.expression, targets);
    else if (ts.isObjectLiteralExpression(node)) node.properties.forEach(property => {
      if (ts.isShorthandPropertyAssignment(property)) targets.push(property.name);
      else if (ts.isPropertyAssignment(property)) assignedNames(property.initializer, targets);
      else if (ts.isSpreadAssignment(property)) assignedNames(property.expression, targets);
    });
    else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) assignedNames(node.left, targets);
  }
  function isNativeRequire(node) {
    // Only .cjs has a native wrapper binding without package-type provenance.
    if (!name.endsWith('.cjs') || !ts.isIdentifier(node) || node.text !== 'require') return false;
    for (let parent = node.parent; parent; parent = parent.parent) if (ts.isWithStatement(parent)) return false;
    if (!checker) {
      const bindingOptions = { allowJs: true, noLib: true, noResolve: true, noEmit: true };
      const bindingHost = {
        ...host, getSourceFile: target => target === name || target === absolute(name) ? file : undefined,
        getDefaultLibFileName: () => '', writeFile: () => {},
        getCanonicalFileName: value => value, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
      };
      checker = ts.createProgram([name], bindingOptions, bindingHost).getTypeChecker();
      const writes = [];
      let dynamicScope = false;
      function collectWrites(current) {
        if (ts.isCallExpression(current) && !current.questionDotToken && ts.isIdentifier(current.expression) && current.expression.text === 'eval' && !checker.getSymbolAtLocation(current.expression)?.declarations?.length) dynamicScope = true;
        if (ts.isBinaryExpression(current) && current.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && current.operatorToken.kind <= ts.SyntaxKind.LastAssignment) assignedNames(current.left, writes);
        if ((ts.isPrefixUnaryExpression(current) || ts.isPostfixUnaryExpression(current)) && (current.operator === ts.SyntaxKind.PlusPlusToken || current.operator === ts.SyntaxKind.MinusMinusToken)) assignedNames(current.operand, writes);
        ts.forEachChild(current, collectWrites);
      }
      collectWrites(file);
      nativeRequire = candidate => {
        const symbol = checker.getSymbolAtLocation(candidate);
        return !dynamicScope && symbol && !symbol.declarations?.length && !writes.some(write => {
          const binding = ts.isShorthandPropertyAssignment(write.parent) ? checker.getShorthandAssignmentValueSymbol(write.parent) : checker.getSymbolAtLocation(write);
          return write.text === 'require' && !binding?.declarations?.length;
        });
      };
    }
    return nativeRequire(node);
  }
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
    } else if (ts.isCallExpression(node) && node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0]) &&
      node.arguments[0].text.startsWith('.') && ['.js', '.mjs', '.cjs', '.ts', '.json'].includes(path.extname(node.arguments[0].text)) && isNativeRequire(node.expression)) {
      references.push(node.arguments[0].text);
      commonJsReferences.add(node.arguments[0].text);
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments.length >= 1 && node.arguments.length <= 2 && ts.isStringLiteral(node.arguments[0])) {
      references.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  output[name] = { error: null, imports: [...new Set(references)].sort().map(reference => {
    if (!reference.startsWith('.')) return { specifier: reference, resolved: null };
    if (path.extname(reference) === '.json') {
      // Exact JSON filenames are bounded immutable data leaves, not code modules.
      return { specifier: reference, resolved: path.relative(virtualRoot, path.join(path.dirname(absolute(name)), reference)) };
    }
    if (commonJsReferences.has(reference)) {
      // Native require loads explicit code filenames without TypeScript extension substitution.
      const target = path.join(path.dirname(absolute(name)), reference);
      return { specifier: reference, resolved: files.has(target) ? path.relative(virtualRoot, target) : null };
    }
    const result = ts.resolveModuleName(reference, absolute(name), options, host, cache).resolvedModule;
    return { specifier: reference, resolved: result ? path.relative(virtualRoot, result.resolvedFileName) : null };
  }) };
}
process.stdout.write(JSON.stringify(output));
