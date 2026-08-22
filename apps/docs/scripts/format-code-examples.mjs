import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, extname, resolve } from 'node:path';
import process from 'node:process';

import { format as prettierFormat } from 'prettier';
import * as prettierPluginSh from 'prettier-plugin-sh';
import prettierPluginToml from 'prettier-plugin-toml';
import { format as sqlFormat } from 'sql-formatter';

const appRoot = resolve(import.meta.dirname, '..');
const repositoryRoot = resolve(appRoot, '../..');
const catalogPath = resolve(
  repositoryRoot,
  'packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json',
);
const cliPath = resolve(
  repositoryRoot,
  'packages/standards/src/sarj_standards/configs/cli-reference.v1.json',
);
const docsProjectionPath = resolve(appRoot, 'src/generated/formatted-code.v1.json');
const mode = process.argv[2];

if (mode !== '--check' && mode !== '--write') {
  throw new Error('usage: node scripts/format-code-examples.mjs --check|--write');
}

const catalogSource = readFileSync(catalogPath, 'utf8');
const cliSource = readFileSync(cliPath, 'utf8');
const catalog = JSON.parse(catalogSource);
const cli = JSON.parse(cliSource);
const cache = new Map();

assert.match(
  execFileSync(resolve(repositoryRoot, 'packages/standards/.venv/bin/ruff'), ['--version'], { encoding: 'utf8' }),
  /^ruff 0\.16\.3\b/u,
  'formatted code requires repository-pinned Ruff 0.16.3',
);
assert.match(
  execFileSync('terraform', ['version'], { encoding: 'utf8' }),
  /^Terraform v1\.15\.8\b/u,
  'formatted code requires Terraform 1.15.8',
);

function sha256(source) {
  return createHash('sha256').update(source).digest('hex');
}

function normalize(source) {
  return `${source.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trimEnd()}\n`;
}

// eslint-disable-next-line @sarj/stepdown -- adapter helpers precede the dispatcher they make readable.
function runFormatter(command, args, source, label) {
  try {
    return execFileSync(command, args, {
      cwd: repositoryRoot,
      encoding: 'utf8',
      input: normalize(source),
      maxBuffer: 1024 * 1024,
      timeout: 30_000,
    });
  } catch (error) {
    const stderr = error && typeof error === 'object' && 'stderr' in error ? String(error.stderr).trim() : '';
    throw new Error(`${label} formatter failed${stderr ? `: ${stderr}` : ''}`, { cause: error });
  }
}

// eslint-disable-next-line @sarj/stepdown -- path normalization is part of the formatter dispatch table.
function virtualPath(path) {
  const lower = path.toLowerCase();
  if (lower.endsWith('.tftest.hcl')) return 'example.tftest.hcl';
  const extension = extname(lower);
  return `example${extension || '.txt'}`;
}

// eslint-disable-next-line @sarj/stepdown -- the Markdown adapter keeps its language table adjacent.
function languageForFence(language) {
  return {
    bash: 'example.sh',
    hcl: 'example.hcl',
    javascript: 'example.js',
    js: 'example.js',
    json: 'example.json',
    markdown: 'example.md',
    md: 'example.md',
    python: 'example.py',
    py: 'example.py',
    sh: 'example.sh',
    shell: 'example.sh',
    sql: 'example.sql',
    terraform: 'example.tf',
    toml: 'example.toml',
    ts: 'example.ts',
    tsx: 'example.tsx',
    typescript: 'example.ts',
    yaml: 'example.yml',
    yml: 'example.yml',
  }[language.toLowerCase()];
}

async function formatMarkdownFences(source, context) {
  const fencePattern = /```([A-Za-z0-9_-]*)\n([\s\S]*?)```/gu;
  const output = [];
  let offset = 0;
  for (const match of source.matchAll(fencePattern)) {
    output.push(source.slice(offset, match.index));
    const language = match[1];
    if (!language) throw new Error(`${context}: nonempty Markdown code fences require a language`);
    const path = languageForFence(language);
    if (!path) throw new Error(`${context}: unsupported Markdown fence language ${language}`);
    const formatted = await formatCode(match[2], path, `${context} fenced ${language}`);
    output.push(`\`\`\`${language}\n${formatted}\`\`\``);
    offset = match.index + match[0].length;
  }
  output.push(source.slice(offset));
  return output.join('');
}

async function formatCode(source, path, context) {
  if (typeof source !== 'string' || source.length === 0) throw new TypeError(`${context}: source must be nonempty`);
  if (source.length > 64 * 1024) throw new Error(`${context}: source exceeds the 64 KiB display limit`);
  if (path.includes('\0')) throw new Error(`${context}: path contains a NUL byte`);
  const lower = path.toLowerCase();
  const cacheKey = `${lower}\0${source}`;
  const cached = cache.get(cacheKey);
  if (cached !== undefined) return cached;

  let formatted;
  if (lower.endsWith('/.git/keep') || lower === '.git/keep') {
    formatted = normalize(source);
  } else if (lower.endsWith('.py') || lower.endsWith('.pyi')) {
    formatted = runFormatter(
      resolve(repositoryRoot, 'packages/standards/.venv/bin/ruff'),
      [
        'format',
        '--isolated',
        '--stdin-filename',
        virtualPath(path),
        '-',
      ],
      source,
      context,
    );
  } else if (
    lower.endsWith('.tf')
    || lower.endsWith('.tfvars')
    || lower.endsWith('.hcl')
    || lower.endsWith('.tftest.hcl')
  ) {
    formatted = runFormatter('terraform', ['fmt', '-'], source, context);
  } else if (lower.endsWith('.sql')) {
    formatted = sqlFormat(normalize(source), {
      language: 'postgresql',
      keywordCase: 'upper',
      tabWidth: 2,
    });
  } else {
    let parser;
    let plugins = [];
    if (/\.(?:ts|cts|mts)$/u.test(lower)) parser = 'typescript';
    else if (lower.endsWith('.tsx')) parser = 'typescript';
    else if (/\.(?:js|cjs|mjs)$/u.test(lower)) parser = 'babel';
    else if (lower.endsWith('.jsx')) parser = 'babel';
    else if (lower.endsWith('.json')) parser = 'json';
    else if (lower.endsWith('.jsonc')) parser = 'json-stringify';
    else if (/\.(?:yaml|yml)$/u.test(lower)) parser = 'yaml';
    else if (/\.(?:md|mdx)$/u.test(lower)) {
      parser = lower.endsWith('.mdx') ? 'mdx' : 'markdown';
      source = await formatMarkdownFences(source, context);
    } else if (lower.endsWith('.toml')) {
      parser = 'toml';
      plugins = [prettierPluginToml];
    } else if (/\.(?:sh|bash|zsh)$/u.test(lower)) {
      parser = 'sh';
      plugins = [prettierPluginSh];
    }
    if (!parser) throw new Error(`${context}: no formatter is registered for ${basename(path)}`);
    formatted = await prettierFormat(normalize(source), {
      filepath: virtualPath(path),
      parser,
      plugins,
      printWidth: 88,
      tabWidth: 2,
    });
  }

  const normalized = normalize(formatted);
  cache.set(cacheKey, normalized);
  return normalized;
}

async function formatFile(file, context) {
  const source = await formatCode(file.source, file.path, `${context} (${file.path})`);
  const secondPass = await formatCode(source, file.path, `${context} idempotence (${file.path})`);
  assert.equal(secondPass, source, `${context} (${file.path}): formatter is not idempotent`);
  return {
    ...file,
    source,
  };
}

async function formatExample(rule, example) {
  const context = `${rule.key}/${example.id}/${example.outcome}`;
  return {
    ...example,
    files: await Promise.all(example.files.map((file) => formatFile(file, `${context}/files`))),
    fixedFiles: await Promise.all(example.fixedFiles.map((file) => formatFile(file, `${context}/fixedFiles`))),
  };
}

function flattenCommands(commands) {
  return commands.flatMap((command) => [command, ...flattenCommands(command.commands)]);
}

const rules = {};
let formattedFileCount = 0;
const sourceFileCount = catalog.rules.reduce(
  (ruleCount, rule) => ruleCount + rule.examples.reduce(
    (exampleCount, example) => exampleCount + example.files.length + example.fixedFiles.length,
    0,
  ),
  0,
);
for (const rule of catalog.rules) {
  const examples = await Promise.all(rule.examples.map((example) => formatExample(rule, example)));
  formattedFileCount += examples.reduce(
    (count, example) => count + example.files.length + example.fixedFiles.length,
    0,
  );
  for (const scenarioId of new Set(examples.map((example) => example.scenarioId))) {
    const before = examples.find((example) => example.scenarioId === scenarioId && example.outcome === 'reject');
    const after = examples.find((example) => example.scenarioId === scenarioId && example.outcome === 'accept');
    assert(before && after, `${rule.key}/${scenarioId}: incomplete comparison`);
    assert.notDeepEqual(
      before.files.map(({ path, source }) => ({ path, source })),
      after.files.map(({ path, source }) => ({ path, source })),
      `${rule.key}/${scenarioId}: formatting collapses before and after to the same code`,
    );
  }
  rules[rule.key] = {
    examples,
    optionsSchemaSource: rule.optionsSchema === null
      ? null
      : await formatCode(JSON.stringify(rule.optionsSchema), 'options.json', `${rule.key}/optionsSchema`),
  };
}
assert.equal(formattedFileCount, sourceFileCount, 'the formatted projection must cover every catalog file');

for (const [ruleKey, displayed] of Object.entries(rules)) {
  for (const example of displayed.examples) {
    for (const file of [...example.files, ...example.fixedFiles]) {
      assert(file.source.endsWith('\n'), `${ruleKey}/${example.id}/${file.path}: missing final newline`);
      if (file.path.endsWith('.sql') && file.source.includes('cursor')) {
        assert.doesNotMatch(file.source, /:\s+cursor\b/u, `${ruleKey}/${example.id}: SQL placeholder was split`);
      }
    }
  }
}

const quickSetupSource = [
  cli.launcher.install,
  `${cli.program} setup`,
  `${cli.program} doctor`,
  `${cli.program} check`,
].join('\n');
const usage = {};
for (const command of flattenCommands(cli.commands)) {
  usage[command.path.join('/')] = normalize(command.usage);
}

const docsProjection = {
  schemaVersion: 1,
  catalogSha256: sha256(catalogSource),
  cliSha256: sha256(cliSource),
  formatterVersions: {
    prettier: '3.9.6',
    prettierPluginSh: '0.19.0',
    prettierPluginToml: '2.0.6',
    ruff: '0.16.3',
    sqlFormatter: '15.8.2',
    terraform: '1.15.8',
  },
  rules,
  static: {
    quickSetup: await formatCode(quickSetupSource, 'quick-setup.sh', 'home/quickSetup'),
    runOnce: await formatCode(`${cli.launcher.runLatest} setup`, 'run-once.sh', 'cli/runOnce'),
    bootstrap: await formatCode(
      '[ci]\nbootstrap = ["yarn generate", "uv run --project python generate-api"]',
      'bootstrap.toml',
      'cli/bootstrap',
    ),
    usage,
  },
};

function render(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function sync(path, expected) {
  let current = '';
  try {
    current = readFileSync(path, 'utf8');
  } catch (error) {
    if (!(error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT')) throw error;
  }
  if (current === expected) return;
  if (mode === '--check') throw new Error(`${path} is stale; run npm run code-examples:sync`);
  mkdirSync(resolve(path, '..'), { recursive: true });
  writeFileSync(path, expected);
}

sync(docsProjectionPath, render(docsProjection));
