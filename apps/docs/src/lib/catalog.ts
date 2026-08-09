import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export const ENGINES = ['eslint', 'iac', 'python', 'sql', 'text'] as const;
export type Engine = (typeof ENGINES)[number];
export type DefaultLevel = 'error' | 'off' | 'warning';
export type Autofix = 'none' | 'safe' | 'suggestion';
export type Category =
  | 'architecture'
  | 'correctness'
  | 'maintainability'
  | 'performance'
  | 'security'
  | 'style'
  | 'testing';
export type Language = 'config' | 'iac' | 'markdown' | 'python' | 'sql' | 'typescript';

export interface ExampleFile {
  path: string;
  source: string;
}

export interface RuleExample {
  id: string;
  title: string;
  outcome: 'accept' | 'reject';
  focusPath: string;
  expectedCount: number;
  files: ExampleFile[];
  fixedFiles: ExampleFile[];
}

export interface Rule {
  key: string;
  engine: Engine;
  id: string;
  code: string | null;
  summary: string;
  rationale: string;
  remediation: string;
  category: Category;
  languages: Language[];
  defaultLevel: DefaultLevel;
  autofix: Autofix;
  status: 'active';
  aliases: string[];
  limitations: string[];
  filePatterns: string[];
  messageIds: string[];
  optionsSchema: Record<string, unknown> | null;
  references: string[];
  since: string | null;
  source: string;
  test: string;
  examples: RuleExample[];
}

export interface Catalog {
  schemaVersion: 1;
  rules: Rule[];
}

const catalogPath = resolve(
  process.cwd(),
  '../../packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json',
);
const schemaPath = resolve(process.cwd(), '../../packages/standards/src/sarj_standards/schemas/rule-catalog.v1.schema.json');

function readGeneratedJson(path: string, label: string): unknown {
  let source: string;
  try {
    source = readFileSync(path, 'utf8');
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') {
      throw new Error(
        `${label} is missing at ${path}. Generate the repository catalog before building apps/docs.`,
        { cause: error },
      );
    }
    throw error;
  }
  try {
    return JSON.parse(source) as unknown;
  } catch (error) {
    throw new Error(`${label} is not valid JSON at ${path}.`, { cause: error });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireString(record: Record<string, unknown>, key: string, context: string): string {
  const value = record[key];
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${context}.${key} must be a non-empty string.`);
  }
  return value;
}

function requireStringArray(record: Record<string, unknown>, key: string, context: string): string[] {
  const value = record[key];
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new TypeError(`${context}.${key} must be a string array.`);
  }
  return value;
}

function validateExampleFile(value: unknown, context: string): asserts value is ExampleFile {
  if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
  requireString(value, 'path', context);
  requireString(value, 'source', context);
}

function validateExample(value: unknown, context: string): asserts value is RuleExample {
  if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
  for (const field of ['id', 'title', 'focusPath']) requireString(value, field, context);
  if (value.outcome !== 'accept' && value.outcome !== 'reject') {
    throw new TypeError(`${context}.outcome must be accept or reject.`);
  }
  if (typeof value.expectedCount !== 'number' || !Number.isInteger(value.expectedCount) || value.expectedCount < 0) {
    throw new TypeError(`${context}.expectedCount must be a non-negative integer.`);
  }
  for (const field of ['files', 'fixedFiles']) {
    const files = value[field];
    if (!Array.isArray(files)) throw new TypeError(`${context}.${field} must be an array.`);
    files.forEach((file, index) => validateExampleFile(file, `${context}.${field}[${index}]`));
  }
  if ((value.files as unknown[]).length === 0) throw new TypeError(`${context}.files must not be empty.`);
}

function validateRule(value: unknown, index: number): asserts value is Rule {
  if (!isRecord(value)) throw new TypeError(`rule catalog rules[${index}] must be an object.`);
  const context = `rule catalog rules[${index}]`;
  const key = requireString(value, 'key', context);
  const engine = requireString(value, 'engine', context);
  const id = requireString(value, 'id', context);
  if (!ENGINES.includes(engine as Engine)) throw new TypeError(`${context}.engine is unsupported: ${engine}.`);
  if (key !== `${engine}:${id}`) throw new TypeError(`${context}.key must equal ${engine}:${id}.`);
  for (const field of ['summary', 'rationale', 'remediation', 'category', 'defaultLevel', 'autofix', 'status', 'source', 'test']) {
    requireString(value, field, context);
  }
  const languages = requireStringArray(value, 'languages', context);
  for (const language of languages) {
    if (!['config', 'iac', 'markdown', 'python', 'sql', 'typescript'].includes(language)) {
      throw new TypeError(`${context}.languages contains unsupported value ${language}.`);
    }
  }
  for (const field of ['aliases', 'limitations', 'filePatterns', 'messageIds']) requireStringArray(value, field, context);
  const references = requireStringArray(value, 'references', context);
  if (references.some((reference) => !reference.startsWith('https://'))) {
    throw new TypeError(`${context}.references must contain only HTTPS URLs.`);
  }
  if (!Array.isArray(value.examples)) throw new TypeError(`${context}.examples must be an array.`);
  value.examples.forEach((example, exampleIndex) => validateExample(example, `${context}.examples[${exampleIndex}]`));
  if (value.code !== null && typeof value.code !== 'string') throw new TypeError(`${context}.code must be a string or null.`);
  if (value.optionsSchema !== null && !isRecord(value.optionsSchema)) {
    throw new TypeError(`${context}.optionsSchema must be an object or null.`);
  }
  if (value.since !== null && typeof value.since !== 'string') {
    throw new TypeError(`${context}.since must be a string or null.`);
  }
  if (!['error', 'off', 'warning'].includes(String(value.defaultLevel))) {
    throw new TypeError(`${context}.defaultLevel is invalid.`);
  }
  if (!['none', 'safe', 'suggestion'].includes(String(value.autofix))) {
    throw new TypeError(`${context}.autofix is invalid.`);
  }
  if (!['architecture', 'correctness', 'maintainability', 'performance', 'security', 'style', 'testing'].includes(String(value.category))) {
    throw new TypeError(`${context}.category is invalid.`);
  }
  if (value.status !== 'active') throw new TypeError(`${context}.status must be active.`);
}

function validateCatalog(value: unknown): asserts value is Catalog {
  if (!isRecord(value) || value.schemaVersion !== 1 || !Array.isArray(value.rules)) {
    throw new TypeError('rule catalog must contain schemaVersion 1 and a rules array.');
  }
  const keys = new Set<string>();
  value.rules.forEach((rule, index) => {
    validateRule(rule, index);
    if (keys.has(rule.key)) throw new TypeError(`rule catalog contains duplicate key ${rule.key}.`);
    keys.add(rule.key);
  });
  const activeIds = new Set(value.rules.map((rule) => rule.key));
  const aliases = new Set<string>();
  for (const rule of value.rules) {
    for (const alias of rule.aliases) {
      const aliasKey = `${rule.engine}:${alias}`;
      if (activeIds.has(aliasKey)) throw new TypeError(`rule alias ${aliasKey} shadows an active rule.`);
      if (aliases.has(aliasKey)) throw new TypeError(`rule alias ${aliasKey} has multiple targets.`);
      aliases.add(aliasKey);
    }
  }
}

const rawCatalog = readGeneratedJson(catalogPath, 'Generated rule catalog');
validateCatalog(rawCatalog);

export const catalog: Catalog = rawCatalog;
export const catalogSchema = readGeneratedJson(schemaPath, 'Rule catalog schema');

export function engineLabel(engine: Engine): string {
  return { eslint: 'TypeScript', iac: 'IaC', python: 'Python', sql: 'SQL', text: 'Text' }[engine];
}

export function ruleHref(rule: Pick<Rule, 'engine' | 'id'>): string {
  return `/rules/${rule.engine}/${rule.id}/`;
}

export function rulesForEngine(engine: Engine): Rule[] {
  return catalog.rules.filter((rule) => rule.engine === engine);
}

export function sourceUrl(path: string): string {
  return `https://github.com/sarj-ai/standards/blob/main/${path.split('/').map(encodeURIComponent).join('/')}`;
}

export function titleFromId(id: string): string {
  return id.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
